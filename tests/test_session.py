# tests/test_session.py
import os
import pytest
import session

EXP3 = r"C:\Aj\gabai_worker\experiment_3"
GT_DIR = os.path.join(EXP3, "ublox_audio")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIRP = os.path.join(HERE, "marker.mp3")

pytestmark = pytest.mark.skipif(not os.path.isdir(GT_DIR), reason="experiment_3 data absent")


def test_detect_format():
    assert session.detect_tested_format(os.path.join(EXP3, "s20_ultra")) == "new"
    assert session.detect_tested_format(GT_DIR) == "unknown"


def test_run_reference_finds_lines():
    ref = session.run_reference(GT_DIR, CHIRP)
    assert len(ref["rows"]) >= 40
    assert ref["fs"] == 16000
    assert len(ref["bin_paths"]) == 6
    assert ref["t0_iso"].startswith("2026-06-22")
    assert len(ref["bin_t0s"]) == len(ref["bin_paths"])


def test_run_tested_and_compare_is_about_one_ms():
    ref = session.run_reference(GT_DIR, CHIRP)
    t = session.run_tested(os.path.join(EXP3, "s20_ultra"), CHIRP)
    assert t["fmt"] == "new"
    assert len(t["rows"]) >= 40
    c = session.compare_tested(t["rows"], ref["rows"], target_ms=10.0)
    assert len(c["pairs"]) >= 40
    assert abs(c["metrics"]["bias"]) < 6.0       # known ~1.2 ms
    assert c["verdict"]["pass"] is True
    assert len(c["dt_ms"]) == len(c["times_s"])
    assert "t_min" in c["pairs"][0]


def test_trust_gate_flags_poor_fit():
    import os
    t_good = session.run_tested(os.path.join(EXP3, "s20_ultra"), CHIRP)
    t_bad = session.run_tested(os.path.join(EXP3, "s21_5g"), CHIRP)
    assert t_good["low_confidence"] is False
    assert t_bad["fit_rmse_ms"] > 5.0
    assert t_bad["low_confidence"] is True
