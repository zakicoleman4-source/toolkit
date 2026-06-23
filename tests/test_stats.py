import numpy as np
import pytest
import stats


def test_constant_offset_has_zero_spread_and_drift():
    dt = [5.0] * 20
    t = list(range(20))
    m = stats.accuracy_metrics(dt, t)
    assert m["n"] == 20
    assert m["bias"] == pytest.approx(5.0)
    assert m["sigma_robust"] == pytest.approx(0.0, abs=1e-9)
    assert m["std"] == pytest.approx(0.0, abs=1e-9)
    assert m["drift_slope_ms_per_min"] == pytest.approx(0.0, abs=1e-9)


def test_linear_ramp_recovers_exact_slope():
    # dt = 2 ms per second of elapsed time
    t = list(range(0, 60))
    dt = [2.0 * x for x in t]
    m = stats.accuracy_metrics(dt, t)
    assert m["drift_slope_ms_per_min"] == pytest.approx(120.0, rel=1e-6)   # 2 ms/s * 60
    assert m["drift_slope_ppm"] == pytest.approx(2000.0, rel=1e-6)         # 2 ms/s = 2000 ppm
    assert m["drift_r2"] == pytest.approx(1.0, rel=1e-9)


def test_robust_sigma_uses_mad():
    dt = [0.0, 0.0, 0.0, 0.0, 100.0]   # one outlier
    t = list(range(5))
    m = stats.accuracy_metrics(dt, t)
    # MAD of mostly-zeros is 0 -> robust sigma 0, unlike classical std
    assert m["sigma_robust"] == pytest.approx(0.0, abs=1e-9)
    assert m["std"] > 10.0
    assert m["one_sigma"] == m["sigma_robust"]
    assert m["two_sigma"] == pytest.approx(2 * m["sigma_robust"])


def test_gaussian_sample_is_normal():
    rng = np.random.default_rng(0)
    dt = (rng.normal(1.0, 1.5, 500)).tolist()
    t = list(range(500))
    m = stats.accuracy_metrics(dt, t)
    assert m["shapiro_p"] > 0.01            # not rejected as normal
    assert abs(m["skew"]) < 0.4
    assert m["sigma_robust"] == pytest.approx(1.5, rel=0.2)


def test_verdict_pass_and_fail():
    rng = np.random.default_rng(1)
    good = stats.accuracy_metrics((rng.normal(1.0, 1.0, 200)).tolist(), list(range(200)))
    v = stats.verdict(good, target_ms=10.0)
    assert v["pass"] is True
    assert v["direction"] == "late"
    bad = stats.accuracy_metrics((rng.normal(8.0, 4.0, 200)).tolist(), list(range(200)))
    assert stats.verdict(bad, target_ms=10.0)["pass"] is False


def test_percentiles_of_abs_error():
    dt = list(range(-10, 11))   # -10..10
    m = stats.accuracy_metrics(dt, list(range(len(dt))))
    assert m["p50_abs"] == pytest.approx(5.0, abs=1.0)
    assert m["p99_abs"] == pytest.approx(10.0, abs=1.0)
