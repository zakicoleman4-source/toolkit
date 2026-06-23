import numpy as np
import pytest
import stats
import viz


def _pairs(dt):
    return [{"phone_pick": i, "gt_pick": i, "dt_ms": d} for i, d in enumerate(dt)]


def test_error_timeline_returns_svg_and_png():
    dt = (np.random.default_rng(0).normal(1.0, 1.0, 50)).tolist()
    m = stats.accuracy_metrics(dt, list(range(50)))
    svg, png = viz.error_timeline_mpl(_pairs(dt), m, target_ms=10.0)
    assert svg.lstrip().startswith("<?xml") or "<svg" in svg
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_hist_returns_two_outputs():
    dt = (np.random.default_rng(1).normal(0.0, 2.0, 80)).tolist()
    m = stats.accuracy_metrics(dt, list(range(80)))
    svg, png = viz.hist_gauss_qq_mpl(dt, m)
    assert "<svg" in svg and png[:4] == b"\x89PNG"


def test_ncc_quality_runs():
    rows = [{"pick_index": i, "ncc": 0.3 + 0.01 * i} for i in range(20)]
    svg, png = viz.ncc_quality_mpl(rows, threshold=0.15)
    assert "<svg" in svg


def test_multi_overlay_runs():
    a = _pairs((np.random.default_rng(2).normal(1, 1, 30)).tolist())
    b = _pairs((np.random.default_rng(3).normal(-2, 1, 30)).tolist())
    svg, png = viz.multi_overlay_mpl([{"name": "A", "pairs": a}, {"name": "B", "pairs": b}])
    assert "<svg" in svg
