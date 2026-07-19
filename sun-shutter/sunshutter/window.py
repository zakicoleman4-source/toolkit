"""Window geometry and the "does sunlight reach this window?" test.

A window only receives direct sun when two things are true at once:

  1. The sun is on the correct side of the wall — its compass azimuth is
     within the window's horizontal field of view around the way the glass
     faces. A south-facing window never sees the sun coming from due north.

  2. The sun is high enough to clear whatever is in the way — the natural
     horizon plus any obstruction (neighbouring buildings, a parapet, a
     hill). This "obstruction horizon" is exactly what the Netanya GIS
     building data lets us compute for a specific flat on a specific floor
     (see gis.py).

This module keeps those two ideas in one small, testable place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


def angular_distance(a: float, b: float) -> float:
    """Smallest absolute angle between two compass bearings, in degrees.

    Handles the 0/360 wrap-around, e.g. 350 and 10 are 20 apart, not 340.
    """
    diff = (a - b) % 360.0
    return min(diff, 360.0 - diff)


@dataclass
class HorizonProfile:
    """Minimum sun elevation needed to clear obstructions, per azimuth.

    Stored as a sparse map of azimuth-bin -> obstruction elevation (deg).
    Between sampled azimuths we interpolate. An empty profile means a clean,
    flat horizon everywhere (obstruction elevation 0). Populate it from GIS
    building data via gis.build_horizon_profile().
    """

    # azimuth (deg, clockwise from north) -> obstruction elevation (deg)
    samples: Dict[float, float] = field(default_factory=dict)
    # Elevation used when there are no samples at all.
    default_elevation: float = 0.0

    def obstruction_elevation(self, azimuth: float) -> float:
        """Obstruction elevation (deg) blocking the sun at a given azimuth."""
        if not self.samples:
            return self.default_elevation

        az = azimuth % 360.0
        keys = sorted(self.samples)

        # Exact hit.
        if az in self.samples:
            return self.samples[az]

        # Find the neighbouring samples on either side (with wrap-around) and
        # linearly interpolate between them.
        lower = None
        upper = None
        for k in keys:
            if k <= az:
                lower = k
        for k in reversed(keys):
            if k >= az:
                upper = k

        if lower is None:
            lower = keys[-1]  # wrap below
        if upper is None:
            upper = keys[0]  # wrap above

        if lower == upper:
            return self.samples[lower]

        # Angular gap from lower up to az and from az up to upper (mod 360).
        span = (upper - lower) % 360.0
        if span == 0:
            return self.samples[lower]
        frac = ((az - lower) % 360.0) / span
        lo_v = self.samples[lower]
        hi_v = self.samples[upper]
        return lo_v + (hi_v - lo_v) * frac


@dataclass
class Window:
    """A single window (or a group that behaves identically).

    Attributes:
        facing_azimuth: Compass bearing the glass faces, degrees clockwise
            from true north (0 = N, 90 = E, 180 = S, 270 = W). For Netanya,
            a window looking at the Mediterranean faces roughly west (~270).
        view_half_angle: Half of the horizontal field of view, in degrees.
            The sun counts as "in front of" the window when its azimuth is
            within this many degrees of facing_azimuth. 90 means the full
            180-degree span a flat wall can see; use less to model a deep
            reveal or side wall that shades grazing angles.
        min_sun_elevation: A floor on the sun's elevation, independent of the
            obstruction horizon. Useful to ignore the faint, near-horizon sun
            (e.g. require the sun to be at least a couple of degrees up before
            calling it "light on the window"). 0 by default.
        horizon: Obstruction horizon profile (buildings etc.). Defaults to a
            clean flat horizon.
        label: Human-friendly name for logs.
    """

    facing_azimuth: float
    view_half_angle: float = 90.0
    min_sun_elevation: float = 0.0
    horizon: HorizonProfile = field(default_factory=HorizonProfile)
    label: str = "window"

    def faces_sun(self, sun_azimuth: float) -> bool:
        """Is the sun horizontally in front of the glass?"""
        return angular_distance(sun_azimuth, self.facing_azimuth) <= self.view_half_angle

    def required_elevation(self, sun_azimuth: float) -> float:
        """Elevation the sun must exceed at this azimuth to light the window."""
        return max(self.min_sun_elevation, self.horizon.obstruction_elevation(sun_azimuth))

    def is_lit(self, sun_elevation: float, sun_azimuth: float) -> bool:
        """True when direct sun currently reaches the window."""
        if not self.faces_sun(sun_azimuth):
            return False
        return sun_elevation >= self.required_elevation(sun_azimuth)
