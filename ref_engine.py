#!/usr/bin/env python3
"""u-blox-audio .bin -> chirp starts in global UTC (cheaper ground truth).

Ground-truth twin of tested_engine.py. Where the phone app derives per-sample
UTC from BOOTTIME anchors, this hardware stamps a 1 Hz GPS PPS impulse directly
INTO the recorded audio, and logs absolute UTC in a paired u-blox .ubx (NAV-PVT).

Per-sample UTC (single robust affine fit, drift-absorbing):
    PPS impulses  -> sample index of each GPS-second edge   (in the .bin audio)
    .ubx NAV-PVT  -> absolute UTC of those seconds
    fit: sample -> UTC over all ~300 PPS edges

Then the chirp template (looped in the recording) is found by normalized
cross-correlation -> MULTIPLE chirp starts -> each mapped to global UTC.

CSV schema matches tested_engine.py so app picks and GT picks diff directly.

.bin facts (measured): headerless int16 LE mono, nominal 16000 Hz, 300 s.
PPS = sharp NEGATIVE impulse (~-15k, 1-2 samples), exactly 1/sec, 300/file,
detected as the per-second-window |max| (audio std ~1167, PPS >5000 = clean).
PPS is kept in the output time base; an internal PPS-suppressed copy is used
for correlation only so the impulses cannot spawn spurious chirp peaks.

Inputs (auto-paired by name in a dir, or given explicitly):
    <name>.bin   raw int16 mono audio with PPS
    <name>.ubx   u-blox NAV-PVT (absolute UTC)
    marker.mp3    reference chirp (any rate; resampled to fs)

Output: <name>.chirp_picks_utc.csv : pick_index,start_sample,start_offset_s,start_utc

Usage:
    python ref_engine.py BIN_OR_DIR [--ubx f.ubx] [--chirp marker.mp3]
        [--fs 16000] [--threshold 0.15] [--min-sep-s 1.0] [--t0-offset 0]
    python ref_engine.py --selftest
"""
import argparse
import datetime as dt
import glob
import os
import struct
import subprocess
import sys

import numpy as np

NOMINAL_FS = 16000
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)

# --------------------------------------------------------------------------
# Robust affine fit  y = ymean + slope*(x - xmean)  (OLS about means + MAD)
# --------------------------------------------------------------------------


class AffineFit:
    __slots__ = ("slope", "xmean", "ymean", "n", "n_rejected", "rmse")

    def __init__(self, slope, xmean, ymean, n, n_rejected, rmse):
        self.slope, self.xmean, self.ymean = slope, xmean, ymean
        self.n, self.n_rejected, self.rmse = n, n_rejected, rmse

    def __call__(self, x):
        return self.ymean + self.slope * (np.asarray(x, dtype=np.float64) - self.xmean)


def _ols(x, y):
    xm, ym = x.mean(), y.mean()
    xc = x - xm
    sxx = float(np.sum(xc * xc))
    if sxx <= 0.0:
        raise ValueError("all x identical; cannot fit")
    slope = float(np.sum(xc * (y - ym)) / sxx)
    return slope, xm, ym, y - (ym + slope * xc)


def robust_fit(xs, ys, mad_threshold=5.0, max_iter=3):
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    g = np.isfinite(x) & np.isfinite(y)
    x, y = x[g], y[g]
    n0 = x.size
    if n0 < 2:
        raise ValueError(f"need >=2 points, got {n0}")
    slope, xm, ym, resid = _ols(x, y)
    kx, ky = x, y
    for _ in range(max_iter):
        mad = float(np.median(np.abs(resid)))
        if mad <= 0.0:
            break
        mask = np.abs(resid) <= mad_threshold * mad
        if mask.sum() < 2 or mask.all():
            break
        kx, ky = kx[mask], ky[mask]
        slope, xm, ym, resid = _ols(kx, ky)
    rmse = float(np.sqrt(np.mean(resid * resid))) if resid.size else 0.0
    return AffineFit(slope, xm, ym, kx.size, n0 - kx.size, rmse)


def utc_seconds_to_iso(utc_s):
    d = _EPOCH + dt.timedelta(seconds=float(utc_s))
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------


def read_bin_mono(path):
    return np.fromfile(path, dtype="<i2").astype(np.float64)


def _ubx_cksum_ok(data, i, length):
    """8-bit Fletcher checksum over class..payload, vs the 2 trailing bytes."""
    ck_a = ck_b = 0
    for b in data[i + 2:i + 6 + length]:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a == data[i + 6 + length] and ck_b == data[i + 7 + length]


def read_ubx_utc_seconds(path):
    """Return sorted POSIX-seconds of checksum-valid NAV-PVT fixes.

    Verifies the UBX checksum, then keeps fixes by time-validity TIER, preferring
    the strictest that still yields >=2 fixes so a logger that never sets a given
    flag can't leave us with nothing:
      NAV-PVT `valid`: bit0 validDate, bit1 validTime, bit2 fullyResolved.
      tier 1: all three (0x07)   tier 2: date+time (0x03)   tier 3: sane year only.
    """
    data = open(path, "rb").read()
    n = len(data)
    cand = []   # (utc_s, valid_flags)
    i = 0
    while i < n - 8:
        if data[i] != 0xB5 or data[i + 1] != 0x62:
            i += 1
            continue
        length = struct.unpack_from("<H", data, i + 4)[0]
        end = i + 6 + length + 2
        if end > n:
            break
        if data[i + 2] == 0x01 and data[i + 3] == 0x07 and length == 92:
            if not _ubx_cksum_ok(data, i, length):
                i += 1
                continue
            p = i + 6
            year, month, day, hour, minute, sec = struct.unpack_from("<HBBBBB", data, p + 4)
            valid = data[p + 11]
            nano = struct.unpack_from("<i", data, p + 16)[0]
            if 2000 < year < 2100:
                try:
                    base = dt.datetime(year, month, day, hour, minute, sec,
                                       tzinfo=dt.timezone.utc)
                    cand.append(((base - _EPOCH).total_seconds() + nano * 1e-9, valid))
                except ValueError:
                    pass
        i = end
    for mask in (0x07, 0x03, 0x00):
        kept = [u for u, v in cand if (v & mask) == mask]
        if len(kept) >= 2:
            return sorted(kept)
    return sorted(u for u, _ in cand)


def decode_to_samples(path, target_fs):
    """Decode any audio via ffmpeg -> mono float64 at target_fs."""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ac", "1",
           "-ar", str(target_fs), "-f", "f32le", "-"]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return np.frombuffer(out.stdout, dtype="<f4").astype(np.float64)


# --------------------------------------------------------------------------
# PPS: detect 1 Hz impulses, fit sample -> UTC
# --------------------------------------------------------------------------


def detect_pps(samples, fs):
    """Per-second-window |max| = PPS candidate sample. Returns ascending sample[].

    ~one candidate per whole second. When the true rate differs from fs the pulse
    drifts across window edges, so a window can hold two pulses (one missed) or
    none (argmax = audio). Ordinal k is recovered from spacing in fit_sample_to_utc,
    and such misfires are dropped there as fit outliers (MAD)."""
    a = np.abs(samples)
    nsec = samples.size // fs
    return np.array([s * fs + int(np.argmax(a[s * fs:(s + 1) * fs])) for s in range(nsec)])


def _align_residual_ms(fit, pps, ubx_arr):
    pu = fit(pps)
    nearest = ubx_arr[np.abs(ubx_arr[None, :] - pu[:, None]).argmin(axis=1)]
    return float(np.median(np.abs(pu - nearest))) * 1e3


def fit_sample_to_utc(pps_samples, ubx_utcs, t0_offset=0):
    """Affine sample->UTC, rate-agnostic. Returns (fit, T0, span_mismatch_s).

    k (the GPS-second ordinal of each PPS pulse) comes from the median pulse
    spacing (NOT fs, which may differ from the true clock). Absolute UTC = T0 + k,
    T0 = integer second of the first .ubx fix: the .bin and .ubx are triggered
    together, so PPS pulse 0 == the first GPS second == ubx_utcs[0].

    NOTE: auto-searching the offset is NOT viable -- NAV-PVT runs ~1 Hz so almost
    ANY integer-second shift lines the PPS comb up with SOME fix (the match is
    periodic-ambiguous). We therefore anchor first-PPS to first-fix and instead
    sanity-check the SPAN: the PPS comb and the ubx fixes must cover the same
    wall-clock window. `span_mismatch_s` = |pps_span - ubx_span|; a large value
    means dropped end fixes or a mis-paired .bin/.ubx, and is surfaced as a flag.
    Use `t0_offset` to nudge T0 by whole seconds if a session ever needs it."""
    if not ubx_utcs:
        raise ValueError("no NAV-PVT fixes in .ubx")
    pps = np.sort(np.asarray(pps_samples, dtype=np.float64))
    if pps.size < 2:
        raise ValueError(f"need >=2 PPS pulses, got {pps.size} "
                         "(bin shorter than ~2 s, or wrong --fs)")
    spacing = float(np.median(np.diff(pps)))
    if spacing <= 0:
        raise ValueError("degenerate PPS spacing (duplicate PPS samples)")
    k = np.round((pps - pps[0]) / spacing)
    t0 = round(ubx_utcs[0]) + t0_offset
    fit = robust_fit(pps, t0 + k)
    pps_span = float(fit(pps[-1]) - fit(pps[0]))
    ubx_span = float(ubx_utcs[-1] - ubx_utcs[0])
    return fit, t0, abs(pps_span - ubx_span)


def suppress_pps(samples, pps_samples, half=2):
    """Internal copy with each PPS impulse linearly interpolated over (+-half),
    so the impulses do not create spurious cross-correlation peaks."""
    s = samples.copy()
    n = s.size
    for p in pps_samples:
        lo, hi = max(0, p - half), min(n - 1, p + half)
        if hi - lo >= 2:
            s[lo:hi + 1] = np.linspace(s[lo], s[hi], hi - lo + 1)
    return s


# --------------------------------------------------------------------------
# Multi-pick normalized cross-correlation
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
    Uses scipy.find_peaks (O(n); the old greedy was O(cand*min_sep))."""
    from scipy.signal import find_peaks
    ncc = normalized_xcorr(signal, template)
    peaks, _ = find_peaks(ncc, height=threshold, distance=max(1, int(min_sep)))
    return [(int(p), float(ncc[p])) for p in peaks], ncc


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def process(bin_path, ubx_path, chirp_path, fs=NOMINAL_FS, threshold=0.15,
            min_sep_s=1.0, t0_offset=0, out_path=None):
    samples = read_bin_mono(bin_path)
    ubx_utcs = read_ubx_utc_seconds(ubx_path)

    pps = detect_pps(samples, fs)
    fit, t0, span_mismatch = fit_sample_to_utc(pps, ubx_utcs, t0_offset)

    clean = suppress_pps(samples, pps)
    template = decode_to_samples(chirp_path, fs)
    min_sep = int(min_sep_s * fs)
    picks, ncc = find_chirps_multi(clean, template, threshold, min_sep)

    rows = []
    for i, (start, peak) in enumerate(picks):
        rows.append({
            "pick_index": i,
            "start_sample": start,
            "start_offset_s": start / fs,
            "start_utc": utc_seconds_to_iso(float(fit(start))),
            "ncc": round(peak, 3),
        })

    if out_path is None:
        out_path = os.path.splitext(bin_path)[0] + ".chirp_picks_utc.csv"
    cols = ["pick_index", "start_sample", "start_offset_s", "start_utc", "ncc"]
    with open(out_path, "w", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(r[c]) for c in cols) + "\n")

    print(f"bin={os.path.basename(bin_path)} samples={samples.size} ({samples.size/fs:.1f}s)")
    print(f"PPS: {pps.size} edges  fit rej={fit.n_rejected} rmse={fit.rmse*1e3:.2f}ms "
          f"slope={fit.slope*fs:.4f}s/s  T0={utc_seconds_to_iso(t0)}")
    print(f"ubx fixes={len(ubx_utcs)}  span_mismatch={span_mismatch:.2f}s"
          + ("  WARN: bin/ubx spans differ -> dropped end fixes or mis-paired files"
             if span_mismatch > 2 else "  OK"))
    print(f"chirps found: {len(picks)} (thr={threshold} min_sep={min_sep_s}s)")
    for r in rows[:8]:
        print(f"  #{r['pick_index']} sample={r['start_sample']} "
              f"+{r['start_offset_s']:.3f}s ncc={r['ncc']} -> {r['start_utc']}")
    if len(rows) > 8:
        print(f"  ... ({len(rows)-8} more)")
    print(f"-> {out_path}")
    return rows


def _pair(bin_or_dir, ubx_arg):
    if os.path.isdir(bin_or_dir):
        bins = sorted(glob.glob(os.path.join(bin_or_dir, "*.bin")))
        if not bins:
            raise FileNotFoundError(f"no .bin in {bin_or_dir}")
        bin_path = bins[0]
    else:
        bin_path = bin_or_dir
    ubx_path = ubx_arg or (os.path.splitext(bin_path)[0] + ".ubx")
    if not os.path.exists(ubx_path):
        raise FileNotFoundError(f"no .ubx for {bin_path} (looked at {ubx_path})")
    return bin_path, ubx_path


# --------------------------------------------------------------------------
# Self-test: synthetic .bin (PPS train + looped chirps at known samples) + UTC
# list; assert recovered chirp UTCs.
# --------------------------------------------------------------------------


def selftest():
    fs = NOMINAL_FS
    dur = 60
    n = fs * dur
    rng = np.random.default_rng(1)
    sig = 0.005 * rng.standard_normal(n)

    # PPS: sharp negative impulse every second (slightly sub-nominal: 15999/s
    # to mimic the real clock) so the fit must absorb the rate.
    eff = 15999
    pps_true = (np.arange(dur) * eff + 37).astype(int)      # phase 37
    pps_true = pps_true[pps_true < n]
    sig[pps_true] = -1.0                                     # impulse dominates

    # chirp template (1 s, 800->3000 Hz), looped into the signal at known starts
    tlen = fs
    tt = np.arange(tlen) / fs
    chirp = 0.3 * np.sin(2 * np.pi * (800 * tt + (3000 - 800) / (2 * 1.0) * tt * tt))
    true_starts = [5 * fs + 100, 17 * fs + 250, 31 * fs + 900, 46 * fs + 33]
    for s in true_starts:
        sig[s:s + tlen] += chirp

    # absolute UTC list (the .ubx stand-in) with gaps, like real data
    t0 = (dt.datetime(2026, 6, 10, 7, 3, 5, tzinfo=dt.timezone.utc) - _EPOCH).total_seconds()
    ubx = [t0 + s for s in range(dur) if s % 7 != 3]         # drop some seconds

    # run inner pipeline directly (no file I/O for audio/ubx)
    pps = detect_pps(sig, fs)
    fit, T0, _ = fit_sample_to_utc(pps, ubx, 0)
    clean = suppress_pps(sig, pps)
    picks, _ = find_chirps_multi(clean, chirp, threshold=0.15, min_sep=int(0.8 * fs))

    found = sorted(s for s, _ in picks)
    print(f"PPS detected={pps.size} fit rej={fit.n_rejected} rmse={fit.rmse*1e3:.3f}ms "
          f"slope*fs={fit.slope*fs:.5f} (true {fs/eff:.5f})")
    print(f"chirps: true={len(true_starts)} found={len(found)}")

    ok = True
    if len(found) != len(true_starts):
        ok = False
    sample_errs, utc_errs = [], []
    for ts in true_starts:
        nf = min(found, key=lambda x: abs(x - ts)) if found else -1
        se = abs(nf - ts)
        sample_errs.append(se)
        exp_utc = t0 + ts / eff          # ground-truth absolute UTC of that sample
        got_utc = float(fit(nf))
        utc_errs.append(abs(got_utc - exp_utc) * 1e3)
    print(f"sample_err max={max(sample_errs)} (tol 5)")
    print(f"utc_err max={max(utc_errs):.3f}ms (tol 3.0)")
    ok = ok and max(sample_errs) <= 5 and max(utc_errs) <= 3.0
    print("SELFTEST PASS" if ok else "SELFTEST FAIL")
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bin", nargs="?", help=".bin file or a directory of them")
    ap.add_argument("--ubx", default=None)
    ap.add_argument("--chirp", default=os.path.join(os.path.dirname(__file__), "marker.mp3"))
    ap.add_argument("--fs", type=int, default=NOMINAL_FS)
    ap.add_argument("--threshold", type=float, default=0.15)
    ap.add_argument("--min-sep-s", type=float, default=1.0)
    ap.add_argument("--t0-offset", type=int, default=0, help="integer-second nudge if off-by-1")
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.bin:
        ap.print_help()
        return 1
    bin_path, ubx_path = _pair(a.bin, a.ubx)
    process(bin_path, ubx_path, a.chirp, a.fs, a.threshold, a.min_sep_s, a.t0_offset, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
