# tests/test_integration_exp3.py
import os
import glob
import pytest
import session, report

EXP3 = r"C:\Aj\gabai_worker\experiment_3"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIRP = os.path.join(HERE, "marker.mp3")
pytestmark = pytest.mark.skipif(not os.path.isdir(EXP3), reason="experiment_3 absent")


def test_known_results_and_neutral_report(tmp_path):
    import report
    ref = session.run_reference(os.path.join(EXP3, "ublox_audio"), CHIRP)
    expect = {"s20_ultra": True, "s23_shit": True, "s21_5g": False}  # PASS / FAIL verified vs original diff.csv
    tested = []
    for name, should_pass in expect.items():
        t = session.run_tested(os.path.join(EXP3, name), CHIRP)
        c = session.compare_tested(t["rows"], ref["rows"], target_ms=10.0)
        assert c["verdict"]["pass"] is should_pass, \
            f"{name}: bias={c['metrics']['bias']:.2f} bound95={c['verdict']['bound95']:.2f}"
        if should_pass:
            assert abs(c["metrics"]["bias"]) < 6.0, f"{name} bias {c['metrics']['bias']:.2f}"
        else:
            assert abs(c["metrics"]["bias"]) > 20.0   # s21_5g genuinely far off
        tested.append({"name": name, "compare": c, "rows": t["rows"]})
    out = report.build_html({"target_ms": 10.0, "tested": tested}, str(tmp_path))
    html = open(out["html_path"], encoding="utf-8").read()
    assert "PASS" in html and "FAIL" in html          # tool shows both verdicts
    for banned in ["phone", "u-blox", "chirp", "gps", "acoustic", "audio", "device", "signal", "spectrogram", "event"]:
        assert banned not in html.lower()
