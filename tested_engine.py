#!/usr/bin/env python3
"""App audio -> chirp start in global UTC.

Twin of the ublox-audio parser, for the gabai phone-app output. Maps the app's
own global-time anchors to a per-sample UTC (linear), cross-correlates the
chirp template against the recorded WAV to find where the chirp starts, then
emits that start in global UTC.

Per-sample UTC is two stacked affine fits (the app's design, TIME-FLOW-ONEPAGE):
    audioFit:     sample(frame) -> bootNs        (audio_anchor_*.txt)
    recordingFit: bootNs        -> UTC seconds   (recording_*.txt)
    UTC(sample) = recordingFit(audioFit(sample))

Both fits are robust OLS about the means (MAD outlier rejection), self-contained
here so the script runs anywhere with just numpy + scipy + ffmpeg on PATH.

Session inputs (auto-globbed from a session dir):
    audio_*.wav         48 kHz mono PCM16, sample N == frame N
    audio_anchor_*.txt  "framePosition,bootNs"        (~5 Hz)
    recording_*.txt     "bootNs,UTC[,uncertaintyNs]"  (fmt-2 or old 3-col UTC,UTC)
    marker.mp3           reference chirp (any rate; resampled to the WAV rate)

Output:
    <session>/chirp_picks_utc.csv : pick_index,start_sample,start_offset_s,start_bootNs,start_utc

Usage:
    python tested_engine.py SESSION_DIR [--chirp marker.mp3] [--out file.csv]
    python tested_engine.py --selftest
"""
import argparse
import datetime as dt
import glob
import os
import re
import subprocess
import sys
import wave

import numpy as np

# --------------------------------------------------------------------------
# Robust affine fit  y = ymean + slope*(x - xmean)   (OLS about means + MAD)
# --------------------------------------------------------------------------


class AffineFit:
    __slots__ = ("slope", "xmean", "ymean", "n", "n_rejected", "rmse")

    def __init__(self, slope, xmean, ymean, n, n_rejected, rmse):
        self.slope = slope
        self.xmean = xmean
        self.ymean = ymean
        self.n = n
        self.n_rejected = n_rejected
        self.rmse = rmse

    def __call__(self, x):
        return self.ymean + self.slope * (np.asarray(x, dtype=np.float64) - self.xmean)


def _ols(xs, ys, w=None):
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    if w is None:
        xm = x.mean()
        ym = y.mean()
        xc = x - xm
        sxx = float(np.sum(xc * xc))
        if sxx <= 0.0:
            raise ValueError("all x identical; cannot fit")
        slope = float(np.sum(xc * (y - ym)) / sxx)
    else:
        w = np.asarray(w, dtype=np.float64)
        W = float(np.sum(w))
        xm = float(np.sum(w * x) / W)
        ym = float(np.sum(w * y) / W)
        xc = x - xm
        sxx = float(np.sum(w * xc * xc))
        if sxx <= 0.0:
            raise ValueError("all x identical; cannot fit")
        slope = float(np.sum(w * xc * (y - ym)) / sxx)
    resid = y - (ym + slope * xc)
    return slope, xm, ym, resid


def robust_fit(xs, ys, mad_threshold=5.0, max_iter=3, weights=None):
    """OLS y=a+b*x with iterative MAD outlier rejection. >=2 points.

    `weights` (optional, same length as xs) does WEIGHTED least squares -- pass
    1/uncertainty^2 so noisy anchors don't drag the fit (the app's design).
    Outlier detection still uses the unweighted residual magnitude vs MAD."""
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    good = np.isfinite(x) & np.isfinite(y)
    if weights is not None:
        w = np.asarray(weights, dtype=np.float64)
        good = good & np.isfinite(w) & (w > 0)
        w = w[good]
    else:
        w = None
    x, y = x[good], y[good]
    n0 = x.size
    if n0 < 2:
        raise ValueError(f"need >=2 points, got {n0}")
    slope, xm, ym, resid = _ols(x, y, w)
    keep_x, keep_y, keep_w = x, y, w
    for _ in range(max_iter):
        mad = float(np.median(np.abs(resid)))
        if mad <= 0.0:
            break
        mask = np.abs(resid) <= mad_threshold * mad
        if mask.sum() < 2 or mask.all():
            break
        keep_x, keep_y = keep_x[mask], keep_y[mask]
        keep_w = keep_w[mask] if keep_w is not None else None
        slope, xm, ym, resid = _ols(keep_x, keep_y, keep_w)
    rmse = float(np.sqrt(np.mean(resid * resid))) if resid.size else 0.0
    return AffineFit(slope, xm, ym, keep_x.size, n0 - keep_x.size, rmse)


# --------------------------------------------------------------------------
# UTC parsing (ISO-8601, Z or +HH:MM, up to 9 fractional digits) -> POSIX s
# --------------------------------------------------------------------------

_TZ_TAIL = re.compile(r"([+-]\d{2}:?\d{2})$")
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def parse_utc_seconds(iso):
    s = iso.strip()
    tz = ""
    if s.endswith("Z"):
        s = s[:-1]
    else:
        m = _TZ_TAIL.search(s)
        if m:
            tz = m.group(1)
            s = s[: m.start()]
    if "." in s:
        base, frac = s.split(".", 1)
        s = f"{base}.{(frac + '000000')[:6]}"
    naive = dt.datetime.fromisoformat(s)
    aware = naive.replace(tzinfo=dt.timezone.utc)
    if tz and tz not in ("+0000", "+00:00", "-0000", "-00:00"):
        if ":" not in tz:
            tz = tz[:3] + ":" + tz[3:]
        sign = 1 if tz[0] == "+" else -1
        hh, mm = tz[1:].split(":")
        aware = aware - dt.timedelta(seconds=sign * (int(hh) * 3600 + int(mm) * 60))
    return (aware - _EPOCH).total_seconds()


def utc_seconds_to_iso(utc_s):
    d = _EPOCH + dt.timedelta(seconds=float(utc_s))
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  # ms precision


# --------------------------------------------------------------------------
# Session file readers
# --------------------------------------------------------------------------


def _to_int(s):
    """Exact int from a numeric string. Plain integers (bootNs ~1e15) exceed
    float64's 2^53 exact range, so int(float(s)) would round them -- parse the
    integer form directly, falling back to float only for sci-notation."""
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        return int(float(s))


def read_anchor_pairs(path):
    """audio_anchor_*.txt -> (frames[], bootNs[]).  'framePosition,bootNs'."""
    frames, boots = [], []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                frames.append(_to_int(parts[0]))
                boots.append(_to_int(parts[1]))
            except ValueError:
                continue
    return frames, boots


def read_recording_pairs(path):
    """recording_*.txt -> (bootNs[], utc_s[], unc_ns[]).  'bootNs,UTC[,unc|UTC]'.

    unc_ns is the 3rd column when it is the numeric uncertaintyNs (fmt-2). The
    legacy 3-col form repeats UTC there (non-numeric) -> unc is None for that row.
    Used to WEIGHT the boot->UTC fit (1/unc^2) like the app's own pipeline."""
    boots, utcs, uncs = [], [], []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                b = _to_int(parts[0])
                u = parse_utc_seconds(parts[1])
            except (ValueError, IndexError):
                continue
            unc = None
            if len(parts) >= 3:
                try:
                    unc = float(parts[2])   # numeric => uncertaintyNs (fmt-2)
                except ValueError:
                    unc = None              # ISO string => legacy 3-col
            boots.append(b)
            utcs.append(u)
            uncs.append(unc)
    return boots, utcs, uncs


GPS_EPOCH_POSIX = 315964800  # 1980-01-06 in POSIX seconds


def weights_from_unc(uncs):
    """1/uncertainty^2 weights, or None if any uncertainty is missing/invalid
    (then the caller falls back to unweighted OLS)."""
    if not uncs or any(u is None for u in uncs):
        return None
    w = [(1.0 / (u * u)) if u > 0 else 0.0 for u in uncs]
    if not any(v > 0 for v in w):
        return None
    return w


def read_measurements_pairs(path):
    """GnssLogger measurements_*.txt 'Raw' rows -> (bootNs[], utc_s[]).

    Used when recording_*.txt is empty (this phone build logs the time bridge
    only in measurements). bootNs = ChipsetElapsedRealtimeNanos (last column).
    UTC from the GNSS hardware clock:
        gps_ns = TimeNanos - FullBiasNanos - BiasNanos
        UTC_s  = GPS_EPOCH + gps_ns/1e9 - leapSeconds
    FullBiasNanos magnitude exceeds 2^53, so it MUST be parsed as int (float
    would lose hundreds of ns). One pair per epoch (dedup by bootNs)."""
    seen = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("Raw,"):
                continue
            p = line.rstrip("\n").split(",")
            try:
                time_nanos = int(p[2])
                leap = int(p[3])
                full_bias = int(p[5])
                bias = float(p[6]) if p[6] else 0.0
                boot = int(p[-1])
            except (ValueError, IndexError):
                continue
            if leap <= 0 or leap == -2147483648:
                leap = 18  # GPS-UTC leap seconds (no leap added since 2017)
            gps_ns = time_nanos - full_bias                  # exact (python int)
            seen[boot] = GPS_EPOCH_POSIX + gps_ns / 1e9 - bias / 1e9 - leap
    boots = sorted(seen)
    return boots, [seen[b] for b in boots]


def read_wav_mono(path):
    """Return (samples float64 in [-1,1], sample_rate)."""
    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        fs = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError(f"expected PCM16, got sampwidth={sw}")
    a = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if nch > 1:
        a = a.reshape(-1, nch).mean(axis=1)
    return a / 32768.0, fs


def decode_to_samples(path, target_fs):
    """Decode any audio (mp3/wav/...) via ffmpeg to mono float32 at target_fs."""
    cmd = [
        "ffmpeg", "-v", "error", "-i", path,
        "-ac", "1", "-ar", str(target_fs), "-f", "f32le", "-",
    ]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return np.frombuffer(out.stdout, dtype="<f4").astype(np.float64)


def audio_start_time_s(path):
    """Container start_time (s) of the first audio stream. ffmpeg raw-decodes
    from this PTS, so decoded sample 0 sits at container time start_time, NOT 0.
    mp4 audio commonly starts a few ms after t=0 (encoder priming / edit list);
    ignoring it biases OLD-format UTC by that offset. 0.0 if unavailable."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=start_time", "-of", "default=nk=1:nw=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        v = out.stdout.decode().strip()
        return float(v) if v and v != "N/A" else 0.0
    except Exception:
        return 0.0


# --------------------------------------------------------------------------
# Multi-pick normalized cross-correlation (chirp loops in the recording)
# --------------------------------------------------------------------------


def normalized_xcorr(signal, template):
    from scipy.signal import fftconvolve
    sig = signal - signal.mean()
    tpl = template - template.mean()
    m = tpl.size
    if sig.size < m:
        raise ValueError("signal shorter than chirp template")
    num = fftconvolve(sig, tpl[::-1], mode="valid")
    e = np.empty(sig.size + 1)
    e[0] = 0.0
    np.cumsum(sig * sig, out=e[1:])
    win_e = e[m:] - e[:-m]
    denom = np.sqrt(np.maximum(win_e, 1e-12)) * (float(np.sqrt(np.sum(tpl * tpl))) + 1e-12)
    return num / denom


def find_chirps_multi(signal, template, threshold, min_sep):
    """All chirp starts: NCC local maxima >= threshold, >= min_sep apart.
    Uses scipy.find_peaks (O(n); the old greedy was O(cand*min_sep), pathological
    on a 35-min signal). Returns ([(start_sample, ncc), ...], ncc_array)."""
    from scipy.signal import find_peaks
    ncc = normalized_xcorr(signal, template)
    peaks, _ = find_peaks(ncc, height=threshold, distance=max(1, int(min_sep)))
    return [(int(p), float(ncc[p])) for p in peaks], ncc


# --------------------------------------------------------------------------
# Session glob + main flow
# --------------------------------------------------------------------------


def _one(session, pattern):
    hits = sorted(glob.glob(os.path.join(session, pattern)))
    if not hits:
        raise FileNotFoundError(f"no {pattern} in {session}")
    return hits[0]


def _maybe_one(session, pattern):
    hits = sorted(glob.glob(os.path.join(session, pattern)))
    return hits[0] if hits else None


def process_session(session, chirp_path, out_path=None, threshold=0.15, min_sep_s=1.0):
    wav_path = _one(session, "audio_*.wav")
    anchor_path = _one(session, "audio_anchor_*.txt")

    frames, boots = read_anchor_pairs(anchor_path)
    if len(frames) < 2:
        raise ValueError(
            f"audio_anchor has <2 entries ({os.path.basename(anchor_path)}, "
            f"{len(frames)}). WAV samples carry no timestamps, so sample->UTC is "
            "impossible without it. The phone must export a non-empty audio_anchor "
            "(framePosition,bootNs) AND recording_*.txt/measurements for this to work.")
    audio_fit = robust_fit(frames, boots)                  # frame -> bootNs

    # bootNs -> UTC: recording_*.txt if it has anchors, else measurements_*.txt.
    rec_path = _maybe_one(session, "recording_*.txt")
    rboots, rutcs, runc, utc_src = [], [], None, None
    if rec_path:
        rboots, rutcs, runc = read_recording_pairs(rec_path)
        utc_src = "recording"
    if len(rboots) < 2:
        meas_path = _one(session, "measurements_*.txt")
        rboots, rutcs = read_measurements_pairs(meas_path)
        runc = None
        utc_src = "measurements"
    rec_fit = robust_fit(rboots, rutcs, weights=weights_from_unc(runc))  # bootNs->UTC

    def sample_to_utc(sample):
        return float(rec_fit(audio_fit(sample)))

    signal, fs = read_wav_mono(wav_path)
    template = decode_to_samples(chirp_path, fs)
    picks, ncc = find_chirps_multi(signal, template, threshold, int(min_sep_s * fs))

    rows = []
    for i, (start, peak) in enumerate(picks):
        rows.append({
            "pick_index": i,
            "start_sample": start,
            "start_offset_s": start / fs,
            "start_utc": utc_seconds_to_iso(sample_to_utc(start)),
            "ncc": round(peak, 3),
        })

    if out_path is None:
        out_path = os.path.join(session, "chirp_picks_utc.csv")
    cols = ["pick_index", "start_sample", "start_offset_s", "start_utc", "ncc"]
    with open(out_path, "w", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(r[c]) for c in cols) + "\n")

    print(f"wav={os.path.basename(wav_path)} fs={fs} samples={signal.size} "
          f"({signal.size/fs:.1f}s)")
    print(f"audioFit (frame->boot): n={audio_fit.n} rej={audio_fit.n_rejected} "
          f"rmse={audio_fit.rmse:.0f}ns")
    print(f"recFit   (boot->UTC) via {utc_src}: n={rec_fit.n} rej={rec_fit.n_rejected} "
          f"rmse={rec_fit.rmse*1e3:.3f}ms")
    print(f"chirps found: {len(picks)} (thr={threshold} min_sep={min_sep_s}s)")
    for r in rows[:8]:
        print(f"  #{r['pick_index']} sample={r['start_sample']} "
              f"+{r['start_offset_s']:.3f}s ncc={r['ncc']} -> {r['start_utc']}")
    if len(rows) > 8:
        print(f"  ... ({len(rows)-8} more)")
    print(f"-> {out_path}")
    return rows


def process_old_format(media_path, recording_path, chirp_path, fs=48000,
                       threshold=0.15, min_sep_s=1.0, out_path=None):
    """OLD phone format: audio is INSIDE the mp4 (no separate WAV / audio_anchor).

    The time bridge `recording_*.txt` maps VIDEO presentation time (ns) -> UTC
    (col0 = video_ns, col1 = UTC; the legacy GnssLogger format also used by
    phone_pipeline/time_sync.py). The mp4 audio track shares the container
    timeline, so a chirp at audio offset t_s sits at video_ns = t_s*1e9.

    chain: decode mp4 audio -> chirp start sample -> video_ns -> recordingFit -> UTC.
    No audioFit: this format has no per-sample hardware anchors (that absence is
    exactly the legacy timing error this measures)."""
    signal = decode_to_samples(media_path, fs)          # mp4 audio track -> mono
    a0 = audio_start_time_s(media_path)                 # container offset of sample 0
    template = decode_to_samples(chirp_path, fs)
    picks, ncc = find_chirps_multi(signal, template, threshold, int(min_sep_s * fs))

    vboots, vutcs, _ = read_recording_pairs(recording_path)   # video_ns -> UTC
    if len(vboots) < 2:
        raise ValueError(f"recording_*.txt needs >=2 (video_ns,UTC) anchors, "
                         f"got {len(vboots)}")
    rec_fit = robust_fit(vboots, vutcs)

    rows = []
    for i, (start, peak) in enumerate(picks):
        video_ns = (a0 + start / fs) * 1e9
        rows.append({
            "pick_index": i, "start_sample": start, "start_offset_s": round(start / fs, 4),
            "start_utc": utc_seconds_to_iso(float(rec_fit(video_ns))),
            "ncc": round(peak, 3),
        })

    if out_path is None:
        out_path = os.path.splitext(media_path)[0] + ".chirp_picks_utc.csv"
    cols = ["pick_index", "start_sample", "start_offset_s", "start_utc", "ncc"]
    with open(out_path, "w", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(r[c]) for c in cols) + "\n")

    print(f"OLD format media={os.path.basename(media_path)} fs={fs} samples={signal.size} "
          f"({signal.size/fs:.1f}s)")
    print(f"recFit (video_ns->UTC): n={rec_fit.n} rej={rec_fit.n_rejected} "
          f"rmse={rec_fit.rmse*1e3:.3f}ms")
    print(f"chirps found: {len(picks)}")
    for r in rows[:8]:
        print(f"  #{r['pick_index']} +{r['start_offset_s']:.3f}s ncc={r['ncc']} -> {r['start_utc']}")
    print(f"-> {out_path}")
    return rows


# --------------------------------------------------------------------------
# Self-test: synthetic session with a KNOWN chirp start; assert recovery.
# --------------------------------------------------------------------------


def selftest():
    import tempfile

    fs = 48000
    dur_s = 20
    n = fs * dur_s
    rng = np.random.default_rng(0)
    sig = (0.01 * rng.standard_normal(n))                  # quiet noise floor

    # build a 2 s linear chirp template 1k->4k Hz
    tlen = 2 * fs
    t = np.arange(tlen) / fs
    chirp = np.sin(2 * np.pi * (1000 * t + (4000 - 1000) / (2 * 2.0) * t * t))

    true_start = 7 * fs + 1234                              # known insert point
    sig[true_start:true_start + tlen] += chirp

    # clocks: frame -> bootNs (48k => 1/48000 s per frame), boot -> UTC
    boot0 = 5_000_000_000                                   # 5 s boot
    ns_per_frame = 1e9 / fs
    utc0 = parse_utc_seconds("2026-06-10T07:03:05.000Z")

    with tempfile.TemporaryDirectory() as d:
        # WAV
        wp = os.path.join(d, "audio_001.wav")
        with wave.open(wp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(fs)
            w.writeframes(np.clip(sig * 32767, -32768, 32767).astype("<i2").tobytes())
        # chirp template as its own wav (decode path exercises ffmpeg)
        cp = os.path.join(d, "chirp_test.wav")
        with wave.open(cp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(fs)
            w.writeframes(np.clip(chirp * 32767, -32768, 32767).astype("<i2").tobytes())
        # anchors ~5 Hz with small jitter + 1 outlier
        ap = os.path.join(d, "audio_anchor_001.txt")
        with open(ap, "w") as f:
            for fr in range(0, n, fs // 5):
                jit = rng.normal(0, 2000)                   # 2 us boot jitter
                f.write(f"{fr},{int(boot0 + fr * ns_per_frame + jit)}\n")
            f.write(f"{n//2},{int(boot0 + (n//2) * ns_per_frame + 5e8)}\n")  # outlier
        # recording: bootNs -> UTC, ~1 Hz, fmt-2
        rp = os.path.join(d, "recording_001.txt")
        with open(rp, "w") as f:
            for sec in range(dur_s + 2):
                bn = boot0 + int(sec * 1e9)
                u = utc0 + sec
                iso = utc_seconds_to_iso(u)
                f.write(f"{bn},{iso},1500000\n")

        rows = process_session(d, cp)

    assert len(rows) == 1, f"expected 1 pick, got {len(rows)}"
    row = rows[0]
    err = abs(row["start_sample"] - true_start)
    expect_utc = utc0 + true_start / fs
    got_utc = parse_utc_seconds(row["start_utc"])
    utc_err_ms = abs(got_utc - expect_utc) * 1e3
    print(f"\nSELFTEST: sample_err={err} (tol 5)  utc_err={utc_err_ms:.3f}ms (tol 2.0)")
    ok = err <= 5 and utc_err_ms <= 2.0
    print("SELFTEST PASS" if ok else "SELFTEST FAIL")
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", nargs="?", help="app session directory")
    ap.add_argument("--chirp", default=os.path.join(os.path.dirname(__file__), "marker.mp3"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--threshold", type=float, default=0.15)
    ap.add_argument("--min-sep-s", type=float, default=1.0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.session:
        ap.print_help()
        return 1
    process_session(a.session, a.chirp, a.out, a.threshold, a.min_sep_s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
