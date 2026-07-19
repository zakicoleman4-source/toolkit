"""Turn GIS building data into an obstruction horizon for one window.

This is the bridge between the open Netanya building data and the sun maths.
Given the observer's position and eye height (their floor), and the footprints
and heights of nearby buildings, we compute — for each compass direction — how
high the sun must climb before it clears the rooftops and reaches the window.
That per-azimuth profile is exactly what Window/HorizonProfile consumes.

The geometry here is a local flat-earth approximation: over the few hundred
metres that matter for shadowing, converting latitude/longitude to metres with
a fixed scale is accurate to well under a degree of elevation, which is plenty.

Input format is deliberately simple and matches what you get after clipping a
GeoJSON export to the neighbourhood:

    buildings = [
        {
            "height_m": 24.0,             # roof height above ground
            "footprint": [(lat, lon), (lat, lon), ...],  # polygon vertices
        },
        ...
    ]

If the GIS layer gives floor counts instead of metres, multiply by a floor
height (typically ~3 m) before calling in.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple

from .window import HorizonProfile

LatLon = Tuple[float, float]

# Mean Earth radius (m) for the local equirectangular projection.
_EARTH_R = 6_371_000.0


def _local_xy(origin: LatLon, point: LatLon) -> Tuple[float, float]:
    """Project (lat, lon) to local east/north metres relative to origin."""
    olat, olon = origin
    plat, plon = point
    mean_lat = math.radians((olat + plat) / 2.0)
    east = math.radians(plon - olon) * math.cos(mean_lat) * _EARTH_R
    north = math.radians(plat - olat) * _EARTH_R
    return east, north


def _azimuth_and_distance(east: float, north: float) -> Tuple[float, float]:
    """Compass azimuth (deg from north) and horizontal distance (m)."""
    azimuth = math.degrees(math.atan2(east, north)) % 360.0
    distance = math.hypot(east, north)
    return azimuth, distance


def build_horizon_profile(
    observer: LatLon,
    observer_height_m: float,
    buildings: Iterable[dict],
    azimuth_step: float = 5.0,
    samples_per_edge: int = 8,
) -> HorizonProfile:
    """Compute an obstruction horizon from nearby buildings.

    Args:
        observer: (latitude, longitude) of the window.
        observer_height_m: Height of the window above ground level, i.e. the
            friend's floor. Floor number x storey height is a fine estimate.
        buildings: Iterable of {"height_m": float, "footprint": [(lat, lon)..]}.
        azimuth_step: Resolution of the output horizon, in degrees.
        samples_per_edge: How many points to sample along each footprint edge.
            More samples trace the true skyline of long walls more closely.

    Returns:
        A HorizonProfile mapping azimuth bins to the elevation (deg) the sun
        must exceed to clear the tallest obstruction in that direction.
    """
    n_bins = int(round(360.0 / azimuth_step))
    horizon: Dict[int, float] = {i: 0.0 for i in range(n_bins)}

    for b in buildings:
        height = float(b["height_m"]) - observer_height_m
        footprint: Sequence[LatLon] = b["footprint"]
        if height <= 0 or len(footprint) < 2:
            # Roof at or below the window never blocks the sun.
            continue

        for i in range(len(footprint)):
            p1 = footprint[i]
            p2 = footprint[(i + 1) % len(footprint)]
            for s in range(samples_per_edge + 1):
                frac = s / samples_per_edge
                lat = p1[0] + (p2[0] - p1[0]) * frac
                lon = p1[1] + (p2[1] - p1[1]) * frac
                east, north = _local_xy(observer, (lat, lon))
                azimuth, dist = _azimuth_and_distance(east, north)
                if dist < 0.5:
                    continue  # essentially at the observer; skip
                elev = math.degrees(math.atan2(height, dist))
                bin_idx = int(round(azimuth / azimuth_step)) % n_bins
                if elev > horizon[bin_idx]:
                    horizon[bin_idx] = elev

    samples = {float(idx * azimuth_step): val for idx, val in horizon.items()}
    return HorizonProfile(samples=samples)
