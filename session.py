# session.py
"""Pure batch orchestration over the proven backend libs. No Streamlit."""
import csv
import glob
import os

import ref_engine as ub
import tested_engine as ap
import compare as cp
import stats as st_

FIT_RMSE_LIMIT_MS = 5.0   # above this -> low confidence


def detect_tested_format(folder):
    if glob.glob(os.path.join(folder, "audio_*.wav")) and \
       glob.glob(os.path.join(folder, "audio_anchor_*.txt")):
        return "new"
    if glob.glob(os.path.join(folder, "recording_*.mp4")):
        return "old"
    return "unknown"


def run_reference(folder, chirp_path, fs=16000, threshold=0.15, min_sep_s=1.0):
    bins = sorted(glob.glob(os.path.join(folder, "*.bin")))
    if not bins:
        raise ValueError("no Reference data files in folder")
    template = ub.decode_to_samples(chirp_path, int(fs))
    combined, files, used_bins, bin_t0s = [], [], [], []
    for bp in bins:
        up = os.path.splitext(bp)[0] + ".ubx"
        if not os.path.exists(up):
            continue
        samples = ub.read_bin_mono(bp)
        ubx = ub.read_ubx_utc_seconds(up)
        pps = ub.detect_pps(samples, int(fs))
        fit, t0, span = ub.fit_sample_to_utc(pps, ubx, 0)
        clean = ub.suppress_pps(samples, pps)
        picks, _ = ub.find_chirps_multi(clean, template, threshold, int(min_sep_s * fs))
        name = os.path.basename(bp)
        for s, v in picks:
            combined.append({
                "start_sample": int(s), "start_offset_s": round(s / fs, 4),
                "start_utc": ub.utc_seconds_to_iso(float(fit(s))), "ncc": round(v, 3),
                "source": name,
            })
        files.append({"name": name, "n_picks": len(picks),
                      "pps_rmse_ms": fit.rmse * 1e3, "span_s": float(span), "n_ubx": len(ubx)})
        used_bins.append(bp)
        bin_t0s.append(ub.utc_seconds_to_iso(t0))
    combined.sort(key=lambda r: r["start_utc"])
    for j, r in enumerate(combined):
        r["pick_index"] = j
    return {"rows": combined, "files": files, "bin_paths": used_bins,
            "bin_t0s": bin_t0s,
            "t0_iso": min(bin_t0s) if bin_t0s else "", "fs": int(fs)}


def _rows_from_pick_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def run_tested(folder, chirp_path, threshold=0.15, min_sep_s=1.0):
    fmt = detect_tested_format(folder)
    name = os.path.basename(os.path.normpath(folder))
    out_csv = os.path.join(folder, "_tested_picks.csv")
    if fmt == "new":
        res = ap.process_session(folder, chirp_path, out_path=out_csv,
                                 threshold=threshold, min_sep_s=min_sep_s)
        media = (glob.glob(os.path.join(folder, "audio_*.wav")) or [None])[0]
        fs = 48000
    elif fmt == "old":
        media = glob.glob(os.path.join(folder, "recording_*.mp4"))[0]
        rec = (glob.glob(os.path.join(folder, "recording_*.txt")) or [None])[0]
        res = ap.process_old_format(media, rec, chirp_path, out_path=out_csv,
                                    threshold=threshold, min_sep_s=min_sep_s)
        fs = 16000
    else:
        raise ValueError("unrecognised tested folder (missing data files)")
    rows = _rows_from_pick_csv(out_csv)
    fit_rmse_ms = 0.0
    try:
        if fmt == "new":
            anchor = glob.glob(os.path.join(folder, "audio_anchor_*.txt"))[0]
            rec = (glob.glob(os.path.join(folder, "recording_*.txt")) or [None])[0]
            meas = (glob.glob(os.path.join(folder, "measurements_*.txt")) or [None])[0]
            rboots, rutcs, runc = ap.read_recording_pairs(rec) if rec else ([], [], None)
            if len(rboots) < 2 and meas:
                rboots, rutcs = ap.read_measurements_pairs(meas)
                runc = None
            rec_fit = ap.robust_fit(rboots, rutcs, weights=ap.weights_from_unc(runc)) if len(rboots) >= 2 else None
            fit_rmse_ms = rec_fit.rmse * 1e3 if rec_fit is not None else 0.0
        elif fmt == "old":
            rec = (glob.glob(os.path.join(folder, "recording_*.txt")) or [None])[0]
            vboots, vutcs, _ = ap.read_recording_pairs(rec) if rec else ([], [], None)
            rec_fit = ap.robust_fit(vboots, vutcs) if len(vboots) >= 2 else None
            fit_rmse_ms = rec_fit.rmse * 1e3 if rec_fit is not None else 0.0
    except Exception:
        fit_rmse_ms = 0.0
    # tested sample-0 UTC = first pick UTC minus that pick's offset into the recording
    # (NOT the first pick's UTC — that is ~10 s in and would shift the strength overlay)
    if rows:
        t0_s = cp.parse_utc(rows[0]["start_utc"]) - float(rows[0]["start_offset_s"])
        t0_iso = ap.utc_seconds_to_iso(t0_s)
    else:
        t0_iso = ""
    return {"name": name, "fmt": fmt, "rows": rows, "media_path": media, "fs": fs,
            "fit_rmse_ms": fit_rmse_ms, "t0_iso": t0_iso,
            "low_confidence": fit_rmse_ms > FIT_RMSE_LIMIT_MS}


def _to_pick_objs(rows):
    out = []
    for r in rows:
        out.append({"pick_index": int(r["pick_index"]),
                    "start_utc": cp.parse_utc(r["start_utc"]), "iso": r["start_utc"]})
    out.sort(key=lambda r: r["start_utc"])
    return out


def compare_tested(tested_rows, gt_rows, target_ms=10.0, max_dt=2.0):
    phone = _to_pick_objs(tested_rows)
    gt = _to_pick_objs(gt_rows)
    loop = cp.estimate_loop_s(gt)
    pairs_raw = cp.match(phone, gt, max_dt)
    pairs, dt_ms = [], []
    gt0 = min(g["start_utc"] for g in gt) if gt else None
    for p, g in pairs_raw:
        d = (p["start_utc"] - g["start_utc"]) * 1e3
        t_min = (g["start_utc"] - gt0) / 60.0 if gt0 is not None else 0.0
        pairs.append({"phone_pick": p["pick_index"], "gt_pick": g["pick_index"],
                      "phone_utc": p["iso"], "gt_utc": g["iso"], "dt_ms": d,
                      "t_min": t_min})
        dt_ms.append(d)
    if not dt_ms:
        return {"pairs": [], "dt_ms": [], "times_s": [], "metrics": None,
                "verdict": None, "loop_s": loop, "n_unmatched": len(phone) - len(pairs)}
    t0 = min(p["start_utc"] for p, _ in pairs_raw)
    times_s = [p["start_utc"] - t0 for p, _ in pairs_raw]
    metrics = st_.accuracy_metrics(dt_ms, times_s)
    return {"pairs": pairs, "dt_ms": dt_ms, "times_s": times_s, "metrics": metrics,
            "verdict": st_.verdict(metrics, target_ms), "loop_s": loop,
            "n_unmatched": len(phone) - len(pairs)}
