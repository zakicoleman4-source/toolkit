#!/usr/bin/env python3
"""Parse u-blox .ubx logs (NAV-PVT only) to CSV for ground-truth comparison.

Usage:
    python parse_ref.py FILE.ubx [FILE2.ubx ...]
    python parse_ref.py *.ubx
Each FILE.ubx -> FILE.csv. Prints a one-line summary per file.
"""
import struct
import sys
import glob
import os

SYNC = b"\xb5\x62"
NAV_PVT_CLASS = 0x01
NAV_PVT_ID = 0x07
NAV_PVT_LEN = 92

FIX_TYPES = {0: "no-fix", 1: "dead-reckoning", 2: "2D", 3: "3D",
             4: "GNSS+DR", 5: "time-only"}

# NAV-PVT payload layout (92 bytes), struct format little-endian
_FMT = "<IHBBBBBBIiBBBBiiiiIIiiiiiIIHHi" "i" "hH"
# Field names in order matching _FMT
_FIELDS = [
    "iTOW", "year", "month", "day", "hour", "min", "sec", "valid",
    "tAcc", "nano", "fixType", "flags", "flags2", "numSV",
    "lon", "lat", "height", "hMSL", "hAcc", "vAcc",
    "velN", "velE", "velD", "gSpeed", "headMot", "sAcc", "headAcc",
    "pDOP", "flags3", "reserved1",
    "headVeh", "magDec", "magAcc",
]


def _checksum(payload_with_header):
    ck_a = ck_b = 0
    for b in payload_with_header:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a, ck_b


def parse(path):
    data = open(path, "rb").read()
    rows = []
    i = 0
    n = len(data)
    bad_ck = 0
    while i < n - 8:
        if data[i:i + 2] != SYNC:
            i += 1
            continue
        cls = data[i + 2]
        mid = data[i + 3]
        length = struct.unpack_from("<H", data, i + 4)[0]
        end = i + 6 + length + 2
        if end > n:
            break
        body = data[i + 2:i + 6 + length]          # class..payload
        ck_a, ck_b = data[i + 6 + length], data[i + 7 + length]
        if (ck_a, ck_b) != _checksum(body):
            bad_ck += 1
            i += 1
            continue
        if cls == NAV_PVT_CLASS and mid == NAV_PVT_ID and length == NAV_PVT_LEN:
            vals = struct.unpack_from(_FMT, data, i + 6)
            rows.append(dict(zip(_FIELDS, vals)))
        i = end
    return rows, bad_ck


def to_csv(rows, out):
    cols = ["utc", "iTOW", "fixType", "numSV",
            "lat_deg", "lon_deg", "hMSL_m", "hAcc_m", "vAcc_m",
            "gSpeed_mps", "headMot_deg", "pDOP", "valid"]
    with open(out, "w", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            utc = "%04d-%02d-%02dT%02d:%02d:%02d" % (
                r["year"], r["month"], r["day"], r["hour"], r["min"], r["sec"])
            f.write(",".join(str(x) for x in [
                utc, r["iTOW"], FIX_TYPES.get(r["fixType"], r["fixType"]),
                r["numSV"],
                "%.7f" % (r["lat"] * 1e-7), "%.7f" % (r["lon"] * 1e-7),
                "%.3f" % (r["hMSL"] / 1000.0),
                "%.3f" % (r["hAcc"] / 1000.0), "%.3f" % (r["vAcc"] / 1000.0),
                "%.3f" % (r["gSpeed"] / 1000.0),
                "%.5f" % (r["headMot"] * 1e-5),
                "%.2f" % (r["pDOP"] * 0.01), r["valid"],
            ]) + "\n")


def main(argv):
    args = []
    for a in argv:
        args += glob.glob(a) or [a]
    if not args:
        print(__doc__)
        return 1
    for path in args:
        rows, bad = parse(path)
        out = os.path.splitext(path)[0] + ".csv"
        to_csv(rows, out)
        if rows:
            f = rows[0]
            l = rows[-1]
            fixes = sum(1 for r in rows if r["fixType"] >= 2)
            sv = sum(r["numSV"] for r in rows) / len(rows)
            print("%-28s %4d fixes  %s..%s  %d/%d with-fix  avgSV=%.1f  badCk=%d -> %s"
                  % (os.path.basename(path), len(rows),
                     "%02d:%02d:%02d" % (f["hour"], f["min"], f["sec"]),
                     "%02d:%02d:%02d" % (l["hour"], l["min"], l["sec"]),
                     fixes, len(rows), sv, bad, os.path.basename(out)))
        else:
            print("%-28s no NAV-PVT records (badCk=%d)" % (os.path.basename(path), bad))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
