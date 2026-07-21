"""Solar position engine — zero dependencies (stdlib only).

Implements the NOAA Solar Position Algorithm to compute the sun's
apparent elevation and azimuth for any latitude/longitude and any instant
in time. Accurate to well within 0.1 degrees for dates near the present,
which is far more than we need to decide when the first beam of light
reaches a window.

Everything here is pure math on Python floats, so it runs anywhere Python
runs (including a Raspberry Pi sitting next to the shutter motor) with no
pip install and no network access.

References:
    - NOAA Solar Calculator spreadsheet
      https://gml.noaa.gov/grad/solcalc/calcdetails.html
    - Jean Meeus, "Astronomical Algorithms" (2nd ed.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone


# --- Julian date helpers ----------------------------------------------------

def _to_utc(dt: datetime) -> datetime:
    """Return dt as a timezone-aware UTC datetime.

    A naive datetime is assumed to already be UTC (callers that care about a
    local wall clock should attach a tzinfo before calling in).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def julian_day(dt: datetime) -> float:
    """Julian Day number (including fractional day) for a UTC datetime."""
    dt = _to_utc(dt)
    year = dt.year
    month = dt.month
    day = (
        dt.day
        + (dt.hour + (dt.minute + (dt.second + dt.microsecond / 1e6) / 60.0) / 60.0)
        / 24.0
    )

    if month <= 2:
        year -= 1
        month += 12

    a = year // 100
    b = 2 - a + a // 4  # Gregorian calendar correction
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day
        + b
        - 1524.5
    )


# --- Core solar position ----------------------------------------------------

@dataclass(frozen=True)
class SunPosition:
    """Where the sun is in the sky, as seen from a point on the ground.

    Attributes:
        elevation: Apparent elevation above the horizon, in degrees.
            Negative means the sun is below the horizon. "Apparent" means
            atmospheric refraction has been applied, so this matches what an
            observer actually sees (the sun looks slightly higher than it
            geometrically is, especially near the horizon).
        azimuth: Compass bearing of the sun, in degrees clockwise from true
            north (0 = N, 90 = E, 180 = S, 270 = W).
        declination: Solar declination in degrees (for diagnostics).
    """

    elevation: float
    azimuth: float
    declination: float


def _refraction_correction(elev_deg: float) -> float:
    """Atmospheric refraction correction (degrees) for a true elevation.

    Uses the NOAA piecewise approximation. Refraction is largest at the
    horizon (~0.57 deg) and negligible high in the sky. Added to the true
    geometric elevation to get the apparent elevation.
    """
    if elev_deg > 85.0:
        return 0.0

    te = math.tan(math.radians(elev_deg))
    if elev_deg > 5.0:
        corr = (
            58.1 / te
            - 0.07 / te**3
            + 0.000086 / te**5
        )
    elif elev_deg > -0.575:
        corr = (
            1735.0
            + elev_deg * (-518.2 + elev_deg * (103.4 + elev_deg * (-12.79 + elev_deg * 0.711)))
        )
    else:
        corr = -20.772 / te

    return corr / 3600.0  # arcseconds -> degrees


def sun_position(latitude: float, longitude: float, dt: datetime) -> SunPosition:
    """Compute the sun's apparent position for a location and time.

    Args:
        latitude: Degrees north of the equator (Netanya ~= 32.32).
        longitude: Degrees east of the prime meridian (Netanya ~= 34.85).
            West longitudes are negative.
        dt: The instant to evaluate. Timezone-aware datetimes are converted
            to UTC; naive datetimes are treated as UTC.

    Returns:
        A SunPosition with apparent elevation and azimuth.
    """
    dt = _to_utc(dt)
    jd = julian_day(dt)
    t = (jd - 2451545.0) / 36525.0  # Julian centuries since J2000.0

    # Geometric mean longitude of the sun (deg), normalised to [0, 360).
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0

    # Geometric mean anomaly of the sun (deg).
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    m_rad = math.radians(m)

    # Eccentricity of Earth's orbit.
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)

    # Sun's equation of the centre.
    c = (
        math.sin(m_rad) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * m_rad) * (0.019993 - 0.000101 * t)
        + math.sin(3 * m_rad) * 0.000289
    )

    true_long = l0 + c  # sun's true longitude (deg)

    # Apparent longitude (correct for nutation and aberration).
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    # Obliquity of the ecliptic (deg), corrected.
    mean_obliq = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    obliq_corr = mean_obliq + 0.00256 * math.cos(math.radians(omega))

    # Solar declination (deg).
    decl = math.degrees(
        math.asin(math.sin(math.radians(obliq_corr)) * math.sin(math.radians(app_long)))
    )

    # Equation of time (minutes).
    y = math.tan(math.radians(obliq_corr / 2.0)) ** 2
    l0_rad = math.radians(l0)
    eq_time = 4.0 * math.degrees(
        y * math.sin(2 * l0_rad)
        - 2 * e * math.sin(m_rad)
        + 4 * e * y * math.sin(m_rad) * math.cos(2 * l0_rad)
        - 0.5 * y * y * math.sin(4 * l0_rad)
        - 1.25 * e * e * math.sin(2 * m_rad)
    )

    # Minutes past UTC midnight.
    minutes_utc = (
        dt.hour * 60.0
        + dt.minute
        + (dt.second + dt.microsecond / 1e6) / 60.0
    )

    # True solar time (minutes), working in UTC (timezone offset = 0).
    true_solar_time = (minutes_utc + eq_time + 4.0 * longitude) % 1440.0

    # Hour angle (deg): 0 at solar noon, negative in the morning.
    hour_angle = true_solar_time / 4.0 - 180.0

    lat_rad = math.radians(latitude)
    decl_rad = math.radians(decl)
    ha_rad = math.radians(hour_angle)

    # Solar zenith angle.
    cos_zenith = (
        math.sin(lat_rad) * math.sin(decl_rad)
        + math.cos(lat_rad) * math.cos(decl_rad) * math.cos(ha_rad)
    )
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.degrees(math.acos(cos_zenith))
    true_elev = 90.0 - zenith

    # Azimuth (deg clockwise from true north).
    denom = math.cos(lat_rad) * math.sin(math.radians(zenith))
    if abs(denom) < 1e-9:
        # Sun directly overhead or at the pole; azimuth is undefined.
        azimuth = 180.0 if latitude > decl else 0.0
    else:
        cos_az = (math.sin(lat_rad) * math.cos(math.radians(zenith)) - math.sin(decl_rad)) / denom
        cos_az = max(-1.0, min(1.0, cos_az))
        az_acos = math.degrees(math.acos(cos_az))
        if hour_angle > 0:
            azimuth = (az_acos + 180.0) % 360.0
        else:
            azimuth = (540.0 - az_acos) % 360.0

    apparent_elev = true_elev + _refraction_correction(true_elev)

    return SunPosition(elevation=apparent_elev, azimuth=azimuth, declination=decl)
