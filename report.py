"""Self-contained HTML + CSV accuracy report. Neutral terminology only."""
import csv
import os

import viz

SUMMARY_COLS = ["name", "verdict", "n", "bias_ms", "one_sigma_ms", "two_sigma_ms",
                "rms_ms", "std_ms", "p95_abs_ms", "worst_ms", "drift_ms_per_min",
                "drift_ppm", "shapiro_p", "bound95_ms"]


def _summary_rows(sr):
    rows = []
    for t in sr["tested"]:
        m = t["compare"]["metrics"]; v = t["compare"]["verdict"]
        rows.append({
            "name": t["name"], "verdict": "PASS" if v["pass"] else "FAIL", "n": m["n"],
            "bias_ms": f"{m['bias']:.2f}", "one_sigma_ms": f"{m['one_sigma']:.2f}",
            "two_sigma_ms": f"{m['two_sigma']:.2f}", "rms_ms": f"{m['rms']:.2f}",
            "std_ms": f"{m['std']:.2f}", "p95_abs_ms": f"{m['p95_abs']:.2f}",
            "worst_ms": f"{m['max_abs']:.2f}", "drift_ms_per_min": f"{m['drift_slope_ms_per_min']:.2f}",
            "drift_ppm": f"{m['drift_slope_ppm']:.1f}", "shapiro_p": f"{m['shapiro_p']:.3g}",
            "bound95_ms": f"{v['bound95']:.2f}",
        })
    return rows


def _metric_table_html(m, v, target_ms):
    def r(k, val): return f"<tr><td>{k}</td><td>{val}</td></tr>"
    return ("<table class=m>"
            + r("verdict", ("PASS" if v["pass"] else "FAIL") + f" @ {target_ms:g} ms target")
            + r("offset (bias)", f"{m['bias']:+.2f} ms ({v['direction']})")
            + r("1σ", f"± {m['one_sigma']:.2f} ms")
            + r("2σ", f"± {m['two_sigma']:.2f} ms")
            + r("~95% bound", f"{v['bound95']:.2f} ms")
            + r("std (classical)", f"{m['std']:.2f} ms")
            + r("RMS", f"{m['rms']:.2f} ms")
            + r("P95 |offset|", f"{m['p95_abs']:.2f} ms")
            + r("worst", f"{m['max_abs']:.2f} ms")
            + r("drift", f"{m['drift_slope_ms_per_min']:+.2f} ms/min ({m['drift_slope_ppm']:+.1f} ppm), R²={m['drift_r2']:.3f}")
            + r("normality (Shapiro p)", f"{m['shapiro_p']:.3g}, skew {m['skew']:+.2f}, kurt {m['kurtosis']:+.2f}")
            + r("N lines", m["n"])
            + "</table>")


def build_html(sr, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    target = sr["target_ms"]
    parts = ["<html><head><meta charset='utf-8'><title>test report</title>",
             "<style>body{font-family:sans-serif;margin:24px}"
             "table.m{border-collapse:collapse}table.m td{border:1px solid #ccc;padding:3px 8px}"
             ".pass{color:#2a8a2a;font-weight:bold}.fail{color:#c0392b;font-weight:bold}"
             "svg{max-width:100%;height:auto}</style></head><body>",
             "<h1>test report</h1>",
             f"<p>Accuracy target: {target:g} ms. Resolution floor: tested 20.83 µs, "
             "Reference 62.50 µs. Bands shown as 1σ and 2σ.</p>"]
    for t in sr["tested"]:
        c = t["compare"]; m = c["metrics"]; v = c["verdict"]
        cls = "pass" if v["pass"] else "fail"
        parts.append(f"<h2>{t['name']} — <span class={cls}>{'PASS' if v['pass'] else 'FAIL'}</span></h2>")
        parts.append(_metric_table_html(m, v, target))
        svg1, _ = viz.error_timeline_mpl(c["pairs"], m, target)
        svg2, _ = viz.hist_gauss_qq_mpl(c["dt_ms"], m)
        svg3, _ = viz.ncc_quality_mpl(t["rows"], 0.15)
        parts += [svg1, svg2, svg3]
    if len(sr["tested"]) > 1:
        parts.append("<h2>All tested — overlay</h2>")
        svgo, _ = viz.multi_overlay_mpl([{"name": t["name"], "pairs": t["compare"]["pairs"]}
                                         for t in sr["tested"]])
        parts.append(svgo)
    parts.append("</body></html>")
    html_path = os.path.join(out_dir, "test_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    csv_path = os.path.join(out_dir, "summary.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_COLS)
        w.writeheader()
        for row in _summary_rows(sr):
            w.writerow(row)
    return {"html_path": html_path, "csv_path": csv_path}
