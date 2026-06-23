import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as _ss

GT_GREEN = "#39ff14"
TESTED_CYAN = "#00d0ff"


def _fig_to_svg_png(fig):
    s = io.StringIO()
    fig.savefig(s, format="svg", bbox_inches="tight")
    p = io.BytesIO()
    fig.savefig(p, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return s.getvalue(), p.getvalue()


def error_timeline_mpl(pairs, metrics, target_ms):
    x = [p["t_min"] for p in pairs] if pairs and "t_min" in pairs[0] else [p["phone_pick"] for p in pairs]
    xlabel = "time (min)" if pairs and "t_min" in pairs[0] else "line index"
    dt = np.array([p["dt_ms"] for p in pairs], dtype=float)
    bias = metrics["bias"]; s1 = metrics["one_sigma"]; s2 = metrics["two_sigma"]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.axhspan(-target_ms, target_ms, color="#2ca02c", alpha=0.07, label=f"±{target_ms:g} ms target")
    ax.axhspan(bias - s2, bias + s2, color="#e45756", alpha=0.10, label="±2σ")
    ax.axhspan(bias - s1, bias + s1, color="#e45756", alpha=0.20, label="±1σ")
    ax.axhline(bias, color="k", ls="--", lw=1, label=f"bias {bias:+.2f} ms")
    out = np.abs(dt - bias) > 3 * metrics["mad"] if metrics["mad"] > 0 else np.zeros(dt.shape, bool)
    ax.plot(x, dt, "o-", ms=4, lw=0.8, color=TESTED_CYAN, label="offset")
    if out.any():
        ax.plot(np.array(x)[out], dt[out], "x", ms=9, color="red", label="outlier")
    # drift line
    if len(x) > 1:
        z = np.polyfit(x, dt, 1)
        ax.plot(x, np.polyval(z, x), color="orange", lw=1.2,
                label=f"drift {metrics['drift_slope_ms_per_min']:+.2f} ms/min")
    ax.set_xlabel(xlabel); ax.set_ylabel("offset (ms)  +=late")
    ax.set_title(f"Per-line offset — bias {bias:+.2f} ± {s1:.2f} ms (1σ); ± {s2:.2f} ms (2σ)")
    ax.legend(fontsize=7, ncol=3, loc="upper left")
    return _fig_to_svg_png(fig)


def hist_gauss_qq_mpl(dt_ms, metrics):
    x = np.asarray(dt_ms, dtype=float)
    mu = metrics["mean"]; sig = metrics["std"] if metrics["std"] > 0 else 1e-9
    fig, (ax, axq) = plt.subplots(1, 2, figsize=(12, 4.5))
    nb = max(5, min(40, int(np.sqrt(x.size)) + 1))
    counts, edges, _ = ax.hist(x, bins=nb, color="#4c78a8", alpha=0.85)
    binw = edges[1] - edges[0]
    xs = np.linspace(x.min() - 3 * sig, x.max() + 3 * sig, 300)
    ax.plot(xs, x.size * binw / (sig * np.sqrt(2 * np.pi)) * np.exp(-0.5 * ((xs - mu) / sig) ** 2),
            color="#e45756", lw=2, label=f"Gaussian μ={mu:.2f} σ={sig:.2f}")
    try:
        kde = _ss.gaussian_kde(x)
        ax.plot(xs, kde(xs) * x.size * binw, color="purple", lw=1.5, ls="--", label="KDE")
    except Exception:
        pass
    b = metrics["bias"]; s1 = metrics["one_sigma"]; s2 = metrics["two_sigma"]
    ax.axvspan(b - s2, b + s2, color="#e45756", alpha=0.08)
    ax.axvspan(b - s1, b + s1, color="#e45756", alpha=0.15)
    ax.axvline(b, color="k", ls="--")
    ax.set_xlabel("offset (ms)"); ax.set_ylabel("count")
    ax.set_title(f"Distribution — N={x.size}, Shapiro p={metrics['shapiro_p']:.3g}")
    ax.legend(fontsize=7)
    _ss.probplot(x, dist="norm", plot=axq)
    axq.set_title("Q–Q (normality)")
    return _fig_to_svg_png(fig)


def ncc_quality_mpl(rows, threshold):
    idx = [int(r["pick_index"]) for r in rows]
    ncc = np.array([float(r["ncc"]) for r in rows], dtype=float)
    weak = ncc < (threshold + 0.05)
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.bar(idx, ncc, color=np.where(weak, "#e45756", "#72b7b2"))
    ax.axhline(threshold, color="orange", ls="--", label=f"threshold {threshold:g}")
    ax.set_xlabel("line index"); ax.set_ylabel("match quality")
    ax.set_title(f"Match quality per line — min {ncc.min():.3f}, median {np.median(ncc):.3f}, "
                 f"{int(weak.sum())} weak")
    ax.legend(fontsize=7)
    return _fig_to_svg_png(fig)


def multi_overlay_mpl(per_tested):
    fig, ax = plt.subplots(figsize=(11, 4.5))
    use_t_min = any(d["pairs"] and "t_min" in d["pairs"][0] for d in per_tested)
    for d in per_tested:
        x = [p["t_min"] for p in d["pairs"]] if use_t_min and d["pairs"] and "t_min" in d["pairs"][0] \
            else [p["phone_pick"] for p in d["pairs"]]
        dt = [p["dt_ms"] for p in d["pairs"]]
        ax.plot(x, dt, "o-", ms=3, lw=0.7, label=d["name"])
    ax.axhline(0, color="k", lw=0.8)
    xlabel = "time (min)" if use_t_min else "line index"
    ax.set_xlabel(xlabel); ax.set_ylabel("offset (ms)")
    ax.set_title("Offset per line — all tested items")
    ax.legend(fontsize=7, ncol=3)
    return _fig_to_svg_png(fig)


# --- appended to viz.py ---
import datetime as _dt
import wave

import plotly.graph_objects as go
from scipy.signal import spectrogram as _spectrogram

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
_IL = 3 * 3600
FMAX = 5200


def _utc(iso):
    return (_dt.datetime.fromisoformat(iso.replace("Z", "+00:00")) - _EPOCH).total_seconds()


def _read_bin(path):
    return np.fromfile(path, dtype="<i2").astype(np.float32)


def _read_wav(path):
    w = wave.open(path, "rb")
    return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)


def _decode_media(path, fs):
    # mp4/other -> mono samples via the proven decoder
    import tested_engine as ap
    return ap.decode_to_samples(path, fs)


def _spec(x, fs, fmax=FMAX, max_cols=None):
    n = 4096 if fs > 20000 else 2048
    f, t, S = _spectrogram(x, fs=fs, nperseg=n, noverlap=n // 2, scaling="spectrum")
    msk = f <= fmax
    f, S = f[msk], S[msk]
    Sdb = 10 * np.log10(S + 1e-12)
    if max_cols and t.size > max_cols:
        step = int(np.ceil(t.size / max_cols))
        ncols = t.size // step
        if ncols >= 1:
            t = t[:ncols * step:step]
            Sdb = Sdb[:, :ncols * step].reshape(Sdb.shape[0], ncols, step).max(axis=2)
    return f, t, Sdb


def _load_tested_signal(media, fmt, fs):
    if fmt == "new" and media.lower().endswith(".wav"):
        return _read_wav(media)
    return _decode_media(media, fs)


def error_timeline_plotly(pairs, metrics, target_ms):
    x = [p["t_min"] for p in pairs] if pairs and "t_min" in pairs[0] else [p["phone_pick"] for p in pairs]
    xlabel = "time (min)" if pairs and "t_min" in pairs[0] else "line index"
    dt = [p["dt_ms"] for p in pairs]
    b = metrics["bias"]; s1 = metrics["one_sigma"]; s2 = metrics["two_sigma"]
    fig = go.Figure()
    for lo, hi, c, nm in [(-target_ms, target_ms, "rgba(44,160,44,0.08)", f"±{target_ms:g} ms target"),
                          (b - s2, b + s2, "rgba(228,87,86,0.10)", "±2σ"),
                          (b - s1, b + s1, "rgba(228,87,86,0.20)", "±1σ")]:
        fig.add_hrect(y0=lo, y1=hi, fillcolor=c, line_width=0, annotation_text=nm,
                      annotation_position="top left")
    fig.add_scatter(x=x, y=dt, mode="lines+markers", name="offset",
                    line=dict(color=TESTED_CYAN))
    fig.add_hline(y=b, line=dict(color="black", dash="dash"))
    fig.update_layout(height=420, title=f"Per-line offset — bias {b:+.2f} ± {s1:.2f} ms (1σ); "
                      f"± {s2:.2f} ms (2σ)", xaxis_title=xlabel, yaxis_title="offset (ms)")
    return fig


def hist_plotly(dt_ms, metrics):
    x = np.asarray(dt_ms, float)
    mu, sig = metrics["mean"], (metrics["std"] or 1e-9)
    nb = max(5, min(40, int(np.sqrt(x.size)) + 1))
    counts, edges = np.histogram(x, bins=nb)
    centers = 0.5 * (edges[:-1] + edges[1:]); binw = edges[1] - edges[0]
    xs = np.linspace(x.min() - 3 * sig, x.max() + 3 * sig, 300)
    fig = go.Figure()
    fig.add_bar(x=centers, y=counts, width=binw * 0.95, marker_color="#4c78a8", name="count")
    fig.add_scatter(x=xs, y=x.size * binw / (sig * np.sqrt(2 * np.pi)) *
                    np.exp(-0.5 * ((xs - mu) / sig) ** 2),
                    mode="lines", line=dict(color="#e45756", width=2),
                    name=f"Gaussian μ={mu:.2f} σ={sig:.2f}")
    b = metrics["bias"]; s1 = metrics["one_sigma"]; s2 = metrics["two_sigma"]
    fig.add_vrect(x0=b - s2, x1=b + s2, fillcolor="rgba(228,87,86,0.08)", line_width=0)
    fig.add_vrect(x0=b - s1, x1=b + s1, fillcolor="rgba(228,87,86,0.16)", line_width=0)
    fig.add_vline(x=metrics["bias"], line=dict(color="black", dash="dash"))
    fig.update_layout(height=420, title=f"Distribution — N={x.size}",
                      xaxis_title="offset (ms)", yaxis_title="count", bargap=0.02)
    return fig


def _to_dt64(epoch_s):
    return (np.asarray(epoch_s, dtype="float64") * 1000).astype("timedelta64[ms]") + np.datetime64("1970-01-01T00:00:00")


def _butterfly_arrays(ref_bin_paths, ref_t0_iso, ref_fs, tested_media, tested_fmt,
                      tested_fs, tested_t0_iso, window, max_cols, ref_bin_t0s=None):
    ph = _load_tested_signal(tested_media, tested_fmt, tested_fs)
    ph_t0 = _utc(tested_t0_iso)
    # crop tested to window
    ph_off = 0.0
    if window:
        w0p = _utc(window[0]) - ph_t0
        w1p = _utc(window[1]) - ph_t0
        pi0 = max(0, int(w0p * tested_fs)); pi1 = min(ph.size, int(w1p * tested_fs))
        if pi1 > pi0:
            ph = ph[pi0:pi1]; ph_off = pi0 / tested_fs
    pf, ptt, pS = _spec(ph, tested_fs, max_cols=max_cols)
    px = ph_t0 + ph_off + ptt

    # GT half: per-bin placement if ref_bin_t0s provided and matches bin count
    if ref_bin_t0s is not None and len(ref_bin_t0s) == len(ref_bin_paths):
        segments = []  # list of (first_x, gx_array, gf, gS)
        for bp, t0_iso in zip(ref_bin_paths, ref_bin_t0s):
            gt_bin = _read_bin(bp)
            bin_t0 = _utc(t0_iso)
            bin_off = 0.0
            if window:
                w0 = _utc(window[0]) - bin_t0
                w1 = _utc(window[1]) - bin_t0
                gi0 = max(0, int(w0 * ref_fs)); gi1 = min(gt_bin.size, int(w1 * ref_fs))
                if gi1 <= gi0:
                    continue  # this bin falls outside the window
                gt_bin = gt_bin[gi0:gi1]; bin_off = gi0 / ref_fs
            gf_bin, gtt_bin, gS_bin = _spec(gt_bin, ref_fs, max_cols=max_cols)
            gx_bin = bin_t0 + bin_off + gtt_bin
            segments.append((gx_bin[0] if gx_bin.size > 0 else float("inf"), gx_bin, gf_bin, gS_bin))
        if not segments:
            # all bins outside window — return tiny valid arrays
            gx = np.array([_utc(ref_t0_iso)])
            gf = np.array([0.0])
            gS = np.zeros((1, 1))
        else:
            segments.sort(key=lambda s: s[0])
            gx = np.concatenate([s[1] for s in segments])
            gf = segments[0][2]  # frequency axis is the same for all bins (same fs)
            gS = np.hstack([s[3] for s in segments])
    else:
        # single-t0 fallback (original behaviour)
        gt = np.concatenate([_read_bin(b) for b in ref_bin_paths])
        gt_t0 = _utc(ref_t0_iso)
        gt_off = 0.0
        if window:
            w0 = _utc(window[0]) - gt_t0
            w1 = _utc(window[1]) - gt_t0
            gi0 = max(0, int(w0 * ref_fs)); gi1 = min(gt.size, int(w1 * ref_fs))
            if gi1 > gi0:
                gt = gt[gi0:gi1]; gt_off = gi0 / ref_fs
        gf, gtt, gS = _spec(gt, ref_fs, max_cols=max_cols)
        gx = gt_t0 + gt_off + gtt

    return gf, gx, gS, pf, px, pS


def butterfly_plotly(ref_bin_paths, ref_t0_iso, ref_fs, tested_media, tested_fmt, tested_fs,
                     tested_t0_iso, ref_picks_iso, tested_picks_iso, window=None, max_cols=3500,
                     ref_bin_t0s=None):
    gf, gx, gS, pf, px, pS = _butterfly_arrays(ref_bin_paths, ref_t0_iso, ref_fs,
                                               tested_media, tested_fmt, tested_fs,
                                               tested_t0_iso, window, max_cols,
                                               ref_bin_t0s=ref_bin_t0s)
    gx_dt = _to_dt64(gx)
    px_dt = _to_dt64(px)
    fig = go.Figure()
    fig.add_heatmap(x=gx_dt, y=gf, z=gS, colorscale="Magma", showscale=False)
    fig.add_heatmap(x=px_dt, y=-pf, z=pS, colorscale="Viridis", colorbar=dict(title="dB"))
    for u in ref_picks_iso:
        fig.add_vline(x=str(_to_dt64(_utc(u))), line=dict(color=GT_GREEN, width=0.8))
    for u in tested_picks_iso:
        fig.add_vline(x=str(_to_dt64(_utc(u))), line=dict(color=TESTED_CYAN, width=0.8))
    fig.update_layout(height=620, title="Strength overlay — Reference (up) vs tested (down)",
                      xaxis_title="time (UTC)", yaxis_title="Reference ↑   |   tested ↓")
    return fig


def butterfly_image(ref_bin_paths, ref_t0_iso, ref_fs, tested_media, tested_fmt, tested_fs,
                    tested_t0_iso, ref_picks_iso, tested_picks_iso, window, dpi=150,
                    ref_bin_t0s=None):
    gf, gx, gS, pf, px, pS = _butterfly_arrays(ref_bin_paths, ref_t0_iso, ref_fs,
                                               tested_media, tested_fmt, tested_fs,
                                               tested_t0_iso, window, None,
                                               ref_bin_t0s=ref_bin_t0s)
    gx_dt = _to_dt64(gx)
    px_dt = _to_dt64(px)
    fig, ax = plt.subplots(figsize=(13, 7))
    ax.pcolormesh(gx_dt, gf, gS, shading="auto", cmap="magma")
    ax.pcolormesh(px_dt, -pf, pS, shading="auto", cmap="viridis")
    ax.axhline(0, color="w", lw=1)
    for u in ref_picks_iso:
        ax.axvline(_to_dt64(_utc(u)), color=GT_GREEN, lw=0.7)
    for u in tested_picks_iso:
        ax.axvline(_to_dt64(_utc(u)), color=TESTED_CYAN, lw=0.7)
    if window:
        ax.set_xlim(_to_dt64(_utc(window[0])), _to_dt64(_utc(window[1])))
    ax.set_ylim(-FMAX, FMAX)
    ax.set_yticks([-4000, -2000, 0, 2000, 4000]); ax.set_yticklabels(["4k", "2k", "0", "2k", "4k"])
    ax.set_xlabel("time (UTC)"); ax.set_ylabel("tested ↓   Hz   ↑ Reference")
    ax.set_title("Strength overlay — sharp window render")
    return _fig_to_svg_png(fig)
