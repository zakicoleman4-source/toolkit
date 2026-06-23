import os
import numpy as np
import pytest
import stats, session as _unused, report


def _make_tested(name, mu, sigma, n=40):
    rng = np.random.default_rng(abs(hash(name)) % 1000)
    dt = (rng.normal(mu, sigma, n)).tolist()
    pairs = [{"phone_pick": i, "gt_pick": i, "phone_utc": "", "gt_utc": "", "dt_ms": d}
             for i, d in enumerate(dt)]
    m = stats.accuracy_metrics(dt, list(range(n)))
    compare = {"pairs": pairs, "dt_ms": dt, "times_s": list(range(n)),
               "metrics": m, "verdict": stats.verdict(m, 10.0), "loop_s": 30, "n_unmatched": 0}
    rows = [{"pick_index": i, "ncc": 0.4} for i in range(n)]
    return {"name": name, "compare": compare, "rows": rows}


def test_build_html_and_csv(tmp_path):
    sr = {"target_ms": 10.0,
          "tested": [_make_tested("A", 1.0, 1.0), _make_tested("B", 9.0, 5.0)]}
    out = report.build_html(sr, str(tmp_path))
    assert os.path.exists(out["html_path"]) and os.path.exists(out["csv_path"])
    html = open(out["html_path"], encoding="utf-8").read()
    assert "PASS" in html and "FAIL" in html
    assert "<svg" in html                      # graphs embedded
    assert "1σ" in html and "2σ" in html
    for banned in ["phone", "u-blox", "chirp", "gps", "acoustic", "audio", "device", "signal", "spectrogram", "event"]:
        assert banned.lower() not in html.lower()
    rows = open(out["csv_path"], encoding="utf-8").read().splitlines()
    assert rows[0].startswith("name,")
    assert len(rows) == 3                       # header + 2 tested
