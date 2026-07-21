"""Runnable demo: build an obstruction horizon from a couple of buildings.

    python examples/gis_horizon_example.py

Shows how neighbouring buildings raise the horizon in their direction, which
is what delays "first light" for a real flat. Replace the hand-written
buildings with polygons clipped from the Netanya GIS layer.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sunshutter.gis import build_horizon_profile  # noqa: E402

# The window we care about (living room, 7th floor ~ 21 m up).
OBSERVER = (32.3215, 34.8532)
OBSERVER_HEIGHT_M = 21.0


def _offset(lat, lon, east_m, north_m):
    """Return (lat, lon) shifted by a local east/north offset in metres."""
    dlat = north_m / 111_320.0
    dlon = east_m / (111_320.0 * math.cos(math.radians(lat)))
    return (lat + dlat, lon + dlon)


def _box(center_lat, center_lon, half_m, height_m):
    corners = [
        _offset(center_lat, center_lon, -half_m, -half_m),
        _offset(center_lat, center_lon, half_m, -half_m),
        _offset(center_lat, center_lon, half_m, half_m),
        _offset(center_lat, center_lon, -half_m, half_m),
    ]
    return {"height_m": height_m, "footprint": corners}


# A tall tower 30 m to the east, and a low block 40 m to the west.
east_tower_center = _offset(*OBSERVER, 30, 0)
west_block_center = _offset(*OBSERVER, -40, 0)
buildings = [
    _box(*east_tower_center, half_m=10, height_m=55),   # blocks the morning sun
    _box(*west_block_center, half_m=12, height_m=18),   # low, barely blocks
]

horizon = build_horizon_profile(OBSERVER, OBSERVER_HEIGHT_M, buildings)

print("Obstruction horizon (elevation the sun must clear), by compass bearing:")
for az in range(0, 360, 15):
    elev = horizon.obstruction_elevation(az)
    bar = "#" * int(elev)
    print(f"  {az:3d} deg : {elev:5.1f} deg  {bar}")

print(
    "\nEast (~90 deg) is blocked by the tower; west (~270 deg) is nearly clear.\n"
    "Paste horizon.samples into config.json under window.horizon.samples."
)
