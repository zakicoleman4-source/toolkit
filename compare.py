#!/usr/bin/env python3
"""Phone inaccuracy = phone chirp-pick UTC  -  ublox-GT chirp-pick UTC.

Takes the two chirp_picks CSVs (same schema, produced by tested_engine.py and
ref_engine.py), matches picks by nearest start_utc, and reports the
per-chirp time delta plus summary stats. Positive dt = phone stamps the chirp
LATER than the ground truth.

Both CSVs must come from the SAME experiment (phone + ublox recording the same
looped chirp at the same time), or there is nothing to match.

Usage:
    python compare.py PHONE.csv UBLOX_GT.csv [--max-dt-s 2.0] [--out diff.csv]
    python compare.py --selftest
"""
import argparse
import csv
import datetime as dt
import sys

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


import re as _re
_TZ_TAIL = _re.compile(r"([+-]\d{2}:?\d{2})$")


def parse_utc(iso):
    """ISO-8601 -> POSIX seconds. Handles 'Z', '+HH:MM'/'+HHMM' offsets (Excel /
    pandas rewrite 'Z' as '+00:00'), and up to 9 fractional digits."""
    s = iso.strip()
    tz = ""
    if s.endswith("Z"):
        s = s[:-1]
    else:
        m = _TZ_TAIL.search(s)
        if m:
            tz = m.group(1)
            s = s[: m.start()]
    if "." in s:
        base, frac = s.split(".", 1)
        s = f"{base}.{(frac + '000000')[:6]}"
    d = dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)
    if tz and tz not in ("+0000", "+00:00", "-0000", "-00:00"):
        if ":" not in tz:
            tz = tz[:3] + ":" + tz[3:]
        sign = 1 if tz[0] == "+" else -1
        hh, mm = tz[1:].split(":")
        d = d - dt.timedelta(seconds=sign * (int(hh) * 3600 + int(mm) * 60))
    return (d - _EPOCH).total_seconds()


def load_picks(path):
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append({
                "pick_index": int(row["pick_index"]),
                "start_utc": parse_utc(row["start_utc"]),
                "iso": row["start_utc"],
            })
    out.sort(key=lambda r: r["start_utc"])
    return out


def estimate_loop_s(gt):
    """Median spacing between consecutive GT picks (the chirp loop period).
    Used only to sanity-check max_dt against half the loop."""
    u = sorted(g["start_utc"] for g in gt)
    diffs = [b - a for a, b in zip(u, u[1:]) if b - a > 0]
    if not diffs:
        return float("inf")
    diffs.sort()
    return diffs[len(diffs) // 2]


def match(phone, gt, max_dt):
    """Pair each phone pick to the GT pick NEAREST in absolute UTC, within max_dt,
    each used once (global greedy by smallest |dt|).

    Phone and GT are absolute UTC of the SAME physical chirps, so the true timing
    error is far smaller than the chirp loop spacing -- nearest-in-time is the
    correct match. (A bulk pairwise-offset search is NOT usable: with a periodic
    chirp comb, every whole-loop shift that keeps the phone session inside the GT
    span ties on inlier count, so it can lock onto a ghost offset of k*loop.)
    Keep max_dt < half the loop so a pick can't grab the wrong neighbour."""
    cand = []
    for pi, p in enumerate(phone):
        for gj, g in enumerate(gt):
            d = abs(p["start_utc"] - g["start_utc"])
            if d <= max_dt:
                cand.append((d, pi, gj))
    cand.sort()
    up = [False] * len(phone)
    ug = [False] * len(gt)
    pairs = []
    for d, pi, gj in cand:
        if up[pi] or ug[gj]:
            continue
        up[pi] = ug[gj] = True
        pairs.append((phone[pi], gt[gj]))
    pairs.sort(key=lambda pr: pr[0]["start_utc"])
    return pairs


def stats(vals):
    n = len(vals)
    if n == 0:
        return None
    m = sum(vals) / n
    var = sum((v - m) ** 2 for v in vals) / n
    rms = (sum(v * v for v in vals) / n) ** 0.5
    s = sorted(vals)
    med = s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    return {"n": n, "mean": m, "median": med, "rms": rms,
            "std": var ** 0.5, "min": min(vals), "max": max(vals),
            "max_abs": max(abs(v) for v in vals)}


def compare(phone_csv, gt_csv, max_dt=2.0, out_path=None):
    phone = load_picks(phone_csv)
    gt = load_picks(gt_csv)
    if not phone or not gt:
        print(f"phone picks={len(phone)}  gt picks={len(gt)} - need both non-empty")
        return [], None

    loop = estimate_loop_s(gt)
    if max_dt > 0.5 * loop:
        print(f"NOTE: max_dt {max_dt}s > half the chirp loop ({loop:.1f}s) -- a pick "
              "could match the wrong neighbour. Lower --align-tol-s.")
    pairs = match(phone, gt, max_dt)
    rows = []
    for p, g in pairs:
        rows.append({
            "phone_pick": p["pick_index"],
            "gt_pick": g["pick_index"],
            "phone_utc": p["iso"],
            "gt_utc": g["iso"],
            "dt_ms": (p["start_utc"] - g["start_utc"]) * 1e3,
        })
    # systematic bias = median dt (robust to a missing/extra pick)
    offset = (stats([r["dt_ms"] for r in rows])["median"] / 1e3) if rows else 0.0
    if out_path:
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["phone_pick", "gt_pick",
                                              "phone_utc", "gt_utc", "dt_ms"])
            w.writeheader()
            for r in rows:
                r2 = dict(r); r2["dt_ms"] = round(r["dt_ms"], 3)
                w.writerow(r2)

    print(f"phone picks={len(phone)}  gt picks={len(gt)}  matched={len(pairs)} "
          f"(median bias={offset*1e3:+.1f}ms, max_dt={max_dt}s)")
    if len(pairs) < min(len(phone), len(gt)):
        print(f"  WARNING: {min(len(phone),len(gt))-len(pairs)} pick(s) unmatched "
              "(missing chirp on one side, or >align_tol jitter)")
    for r in rows:
        print(f"  phone#{r['phone_pick']} {r['phone_utc']}  vs  "
              f"gt#{r['gt_pick']} {r['gt_utc']}   dt={r['dt_ms']:+.2f} ms")
    st = stats([r["dt_ms"] for r in rows])
    if st:
        # residual = jitter after removing the systematic bulk offset
        res = stats([r["dt_ms"] - offset * 1e3 for r in rows])
        print(f"\nPHONE INACCURACY (dt = phone - GT):")
        print(f"  n={st['n']}  median={st['median']:+.2f}ms  mean={st['mean']:+.2f}ms  "
              f"rms={st['rms']:.2f}ms  max_abs={st['max_abs']:.2f}ms")
        print(f"  systematic bias (bulk) = {offset*1e3:+.2f}ms")
        print(f"  random jitter (residual): rms={res['rms']:.2f}ms "
              f"std={res['std']:.2f}ms max_abs={res['max_abs']:.2f}ms")
    else:
        print("no matches within max_dt - same experiment? if the phone clock is "
              "grossly off, raise --max-dt-s (but keep it < half the chirp loop).")
    if out_path:
        print(f"-> {out_path}")
    return rows, st


def selftest():
    import tempfile, os
    base = dt.datetime(2026, 6, 21, 14, 6, 41, tzinfo=dt.timezone.utc)

    def iso(off):
        d = base + dt.timedelta(seconds=off)
        return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    starts = [13.0, 43.7, 74.4, 105.1]
    jit = [0.0005, -0.0003, 0.0004, -0.0002]

    def write_csvs(d, gt_starts, phone_starts):
        gp, pp = os.path.join(d, "gt.csv"), os.path.join(d, "phone.csv")
        with open(gp, "w") as f:
            f.write("pick_index,start_sample,start_offset_s,start_utc,ncc\n")
            for i, s in enumerate(gt_starts):
                f.write(f"{i},0,{s},{iso(s)},0.25\n")
        with open(pp, "w") as f:
            f.write("pick_index,start_sample,start_offset_s,start_utc,ncc\n")
            for i, s in enumerate(phone_starts):
                f.write(f"{i},0,{s},{iso(s)},1.0\n")
        return pp, gp

    ok = True

    # case 1: small 4 ms bias + jitter -> all 4 matched, median ~4ms
    with tempfile.TemporaryDirectory() as d:
        pp, gp = write_csvs(d, starts, [s + 0.004 + j for s, j in zip(starts, jit)])
        print("--- case 1: 4 ms bias ---")
        rows, st = compare(pp, gp, max_dt=2.0)
    c1 = st and st["n"] == 4 and abs(st["median"] - 4.0) < 1.0
    ok = ok and c1

    # case 2: +6 s offset within max_dt and < half loop -> all 4 matched, ~6000 ms
    with tempfile.TemporaryDirectory() as d:
        pp, gp = write_csvs(d, starts, [s + 6.0 + j for s, j in zip(starts, jit)])
        print("\n--- case 2: +6 s offset (max_dt 10) ---")
        rows, st = compare(pp, gp, max_dt=10.0)
    c2 = st and st["n"] == 4 and abs(st["median"] - 6000.0) < 5.0
    ok = ok and c2

    # case 3: phone missing the 2nd chirp -> 3 matched, no false pair
    with tempfile.TemporaryDirectory() as d:
        ph = [starts[0] + 0.004, starts[2] + 0.004, starts[3] + 0.004]
        pp, gp = write_csvs(d, starts, ph)
        print("\n--- case 3: phone missing 1 chirp ---")
        rows, st = compare(pp, gp, max_dt=2.0)
    c3 = st and st["n"] == 3 and abs(st["median"] - 4.0) < 1.0
    ok = ok and c3

    # case 4: GHOST regression -- phone session in the MIDDLE of a long GT
    # timeline. Nearest-UTC must report ~4 ms, NOT a k*loop ghost.
    with tempfile.TemporaryDirectory() as d:
        loop = 30.7
        gt_long = [i * loop for i in range(250)]
        ph_mid = [(40 + i) * loop + 0.004 for i in range(12)]
        pp, gp = write_csvs(d, gt_long, ph_mid)
        print("\n--- case 4: phone in middle of 250-pick GT (ghost regression) ---")
        rows, st = compare(pp, gp, max_dt=2.0)
    c4 = st and st["n"] == 12 and abs(st["median"] - 4.0) < 1.0
    ok = ok and c4

    print(f"\ncases: c1={bool(c1)} c2={bool(c2)} c3={bool(c3)} c4={bool(c4)}")
    print("SELFTEST PASS" if ok else "SELFTEST FAIL")
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phone_csv", nargs="?")
    ap.add_argument("gt_csv", nargs="?")
    ap.add_argument("--max-dt-s", type=float, default=2.0,
                    help="max |phone-gt| UTC distance to accept a pair "
                         "(keep < half the chirp loop spacing)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.phone_csv and a.gt_csv):
        ap.print_help()
        return 1
    compare(a.phone_csv, a.gt_csv, a.max_dt_s, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
