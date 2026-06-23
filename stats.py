"""Engineering-grade accuracy metrics for offset (dt) series. Pure: numpy + scipy only."""
import numpy as np
from scipy import stats as _ss


def _robust_sigma(x):
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    return 1.4826 * mad, mad


def accuracy_metrics(dt_ms, times_s):
    x = np.asarray(dt_ms, dtype=float)
    t = np.asarray(times_s, dtype=float)
    n = x.size
    if n == 0:
        raise ValueError("empty dt series")
    mean = float(x.mean())
    median = float(np.median(x))
    rms = float(np.sqrt(np.mean(x * x)))
    std = float(x.std(ddof=1)) if n > 1 else 0.0
    sigma_robust, mad = _robust_sigma(x)
    sigma_robust = float(sigma_robust); mad = float(mad)
    q1, q3 = np.percentile(x, [25, 75])
    iqr = float(q3 - q1)
    absx = np.abs(x)
    p50, p95, p99 = (float(v) for v in np.percentile(absx, [50, 95, 99]))

    # 95% CI on the mean (Student-t)
    if n > 1:
        se = std / np.sqrt(n)
        tcrit = float(_ss.t.ppf(0.975, df=n - 1))
        ci_lo, ci_hi = mean - tcrit * se, mean + tcrit * se
    else:
        ci_lo = ci_hi = mean

    # drift: OLS dt(ms) vs elapsed time(s)
    slope_ms_per_s = 0.0; r2 = 0.0; s_ci_lo = 0.0; s_ci_hi = 0.0
    if n > 1 and np.ptp(t) > 0:
        lr = _ss.linregress(t, x)
        slope_ms_per_s = float(lr.slope)
        r2 = float(lr.rvalue ** 2)
        if n > 2:
            tcrit2 = float(_ss.t.ppf(0.975, df=n - 2))
            s_ci_lo = slope_ms_per_s - tcrit2 * float(lr.stderr)
            s_ci_hi = slope_ms_per_s + tcrit2 * float(lr.stderr)
        else:
            s_ci_lo = s_ci_hi = slope_ms_per_s

    # normality
    if n >= 3 and std > 0:
        shapiro_p = float(_ss.shapiro(x).pvalue)
    else:
        shapiro_p = 1.0
    skew = float(_ss.skew(x)) if n > 2 and std > 0 else 0.0
    kurt = float(_ss.kurtosis(x, fisher=True)) if n > 3 and std > 0 else 0.0

    return {
        "n": int(n), "mean": mean, "median": median, "rms": rms, "std": std,
        "mad": mad, "sigma_robust": sigma_robust, "iqr": iqr,
        "min": float(x.min()), "max": float(x.max()), "max_abs": float(absx.max()),
        "bias": median, "p50_abs": p50, "p95_abs": p95, "p99_abs": p99,
        "ci95_mean_lo": float(ci_lo), "ci95_mean_hi": float(ci_hi),
        "one_sigma": sigma_robust, "two_sigma": 2.0 * sigma_robust,
        "drift_slope_ms_per_min": slope_ms_per_s * 60.0,
        "drift_slope_ppm": slope_ms_per_s * 1e3,   # ms/s -> (s/s)*1e6
        "drift_r2": r2,
        "drift_slope_ci95_lo": s_ci_lo * 60.0, "drift_slope_ci95_hi": s_ci_hi * 60.0,
        "shapiro_p": shapiro_p, "skew": skew, "kurtosis": kurt,
    }


def verdict(metrics, target_ms=10.0):
    bias = metrics["bias"]
    bound95 = abs(bias) + metrics["two_sigma"]
    return {
        "pass": bool(bound95 <= target_ms),
        "bound95": float(bound95),
        "direction": "late" if bias >= 0 else "early",
    }
