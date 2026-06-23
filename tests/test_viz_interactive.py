# tests/test_viz_interactive.py
import os
import numpy as np
import pytest
import viz

EXP3 = r"C:\Aj\gabai_worker\experiment_3"


def _pairs(dt):
    return [{"phone_pick": i, "gt_pick": i, "dt_ms": d} for i, d in enumerate(dt)]


def test_error_timeline_plotly_has_traces():
    import stats
    dt = (np.random.default_rng(0).normal(1, 1, 40)).tolist()
    m = stats.accuracy_metrics(dt, list(range(40)))
    fig = viz.error_timeline_plotly(_pairs(dt), m, 10.0)
    assert len(fig.data) >= 1
    assert len(fig.layout.shapes) >= 3


def test_hist_plotly_has_sigma_bands():
    import stats
    dt = (np.random.default_rng(5).normal(0, 2, 60)).tolist()
    m = stats.accuracy_metrics(dt, list(range(60)))
    fig = viz.hist_plotly(dt, m)
    assert len(fig.layout.shapes) >= 2   # 1s + 2s vrects


@pytest.mark.skipif(not os.path.isdir(EXP3), reason="experiment_3 absent")
def test_butterfly_plotly_builds():
    import glob
    bins = sorted(glob.glob(os.path.join(EXP3, "ublox_audio", "*.bin")))
    wav = glob.glob(os.path.join(EXP3, "s20_ultra", "audio_*.wav"))[0]
    fig = viz.butterfly_plotly(bins, "2026-06-22T19:31:53.657Z", 16000, wav, "new", 48000,
                               "2026-06-22T19:31:58.288Z", [], [], window=None, max_cols=1500)
    assert len(fig.data) >= 2   # GT heatmap + tested heatmap


@pytest.mark.skipif(not os.path.isdir(EXP3), reason="experiment_3 absent")
def test_butterfly_image_sharp_window():
    import glob
    bins = sorted(glob.glob(os.path.join(EXP3, "ublox_audio", "*.bin")))
    wav = glob.glob(os.path.join(EXP3, "s20_ultra", "audio_*.wav"))[0]
    svg, png = viz.butterfly_image(bins, "2026-06-22T19:31:53.657Z", 16000, wav, "new", 48000,
                                   "2026-06-22T19:31:58.288Z",
                                   [], [], window=("2026-06-22T19:32:00Z", "2026-06-22T19:37:00Z"))
    assert "<svg" in svg and png[:4] == b"\x89PNG"
