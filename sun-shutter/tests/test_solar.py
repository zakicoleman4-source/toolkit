"""Accuracy checks for the solar engine against independently known values.

The reference numbers come from the NOAA Solar Calculator for Netanya. We
allow a small tolerance because NOAA rounds to the minute and we apply
refraction.
"""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from sunshutter.solar import sun_position

NETANYA_LAT = 32.3215
NETANYA_LON = 34.8532
TZ = ZoneInfo("Asia/Jerusalem")


def test_solar_noon_elevation_summer():
    # Around the summer solstice the noon sun over Netanya is very high
    # (~81 deg). Solar noon is close to 12:39 local in late June.
    dt = datetime(2024, 6, 21, 12, 39, tzinfo=TZ)
    pos = sun_position(NETANYA_LAT, NETANYA_LON, dt)
    assert 80.0 < pos.elevation < 82.0
    # Sun is roughly due south near local noon. At ~81 deg elevation the sun
    # is almost overhead, so azimuth swings quickly with time; allow a wider
    # band than the low-winter-sun case.
    assert abs(pos.azimuth - 180.0) < 10.0


def test_solar_noon_elevation_winter():
    # Near the winter solstice the noon sun is low (~34 deg).
    dt = datetime(2024, 12, 21, 11, 39, tzinfo=TZ)
    pos = sun_position(NETANYA_LAT, NETANYA_LON, dt)
    assert 33.0 < pos.elevation < 36.0
    assert abs(pos.azimuth - 180.0) < 3.0


def test_sun_is_east_in_the_morning():
    dt = datetime(2024, 3, 20, 7, 30, tzinfo=TZ)
    pos = sun_position(NETANYA_LAT, NETANYA_LON, dt)
    assert pos.elevation > 0
    # Morning sun sits in the eastern half of the sky.
    assert 60.0 < pos.azimuth < 120.0


def test_sun_is_west_in_the_afternoon():
    dt = datetime(2024, 3, 20, 16, 30, tzinfo=TZ)
    pos = sun_position(NETANYA_LAT, NETANYA_LON, dt)
    assert pos.elevation > 0
    assert 240.0 < pos.azimuth < 300.0


def test_night_is_below_horizon():
    dt = datetime(2024, 3, 20, 1, 0, tzinfo=TZ)
    pos = sun_position(NETANYA_LAT, NETANYA_LON, dt)
    assert pos.elevation < 0


def test_azimuth_in_range():
    for hour in range(0, 24):
        dt = datetime(2024, 8, 1, hour, tzinfo=TZ)
        pos = sun_position(NETANYA_LAT, NETANYA_LON, dt)
        assert 0.0 <= pos.azimuth < 360.0
        assert -90.0 <= pos.elevation <= 90.0
