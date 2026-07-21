"""Tests for window geometry, GIS horizon, events and the scheduler."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sunshutter.config import AppConfig
from sunshutter.events import compute_day_events
from sunshutter.gis import build_horizon_profile
from sunshutter.scheduler import desired_state_at, events_for, run_scheduler
from sunshutter.shutter import MockShutterController
from sunshutter.window import HorizonProfile, Window, angular_distance

TZ = ZoneInfo("Asia/Jerusalem")
LAT, LON = 32.3215, 34.8532


# --- window geometry --------------------------------------------------------

def test_angular_distance_wraps():
    assert angular_distance(350, 10) == 20
    assert angular_distance(10, 350) == 20
    assert angular_distance(0, 180) == 180


def test_faces_sun():
    w = Window(facing_azimuth=270, view_half_angle=90)
    assert w.faces_sun(270)
    assert w.faces_sun(200)
    assert w.faces_sun(359)  # within 90 of 270
    assert not w.faces_sun(90)  # due east, behind a west wall


def test_is_lit_requires_front_and_height():
    w = Window(facing_azimuth=270, view_half_angle=90, min_sun_elevation=5)
    assert w.is_lit(sun_elevation=30, sun_azimuth=260)
    assert not w.is_lit(sun_elevation=3, sun_azimuth=260)   # too low
    assert not w.is_lit(sun_elevation=30, sun_azimuth=90)   # behind wall


def test_horizon_profile_interpolates():
    hp = HorizonProfile(samples={0.0: 10.0, 90.0: 20.0})
    assert hp.obstruction_elevation(0) == 10.0
    assert hp.obstruction_elevation(90) == 20.0
    assert abs(hp.obstruction_elevation(45) - 15.0) < 1e-6


# --- GIS horizon ------------------------------------------------------------

def test_gis_building_blocks_east():
    # A tall building ~20 m due east of the observer should raise the horizon
    # in the eastern direction (azimuth ~90) and leave the west clear.
    observer = (LAT, LON)
    # ~20 m east: shift longitude by 20 / (111320 * cos(lat)).
    import math
    dlon = 20.0 / (111320.0 * math.cos(math.radians(LAT)))
    east_center_lon = LON + dlon
    d = 2.0 / 111320.0  # ~2 m half-size footprint in degrees lat
    building = {
        "height_m": 40.0,
        "footprint": [
            (LAT - d, east_center_lon - dlon * 0.1),
            (LAT + d, east_center_lon - dlon * 0.1),
            (LAT + d, east_center_lon + dlon * 0.1),
            (LAT - d, east_center_lon + dlon * 0.1),
        ],
    }
    hp = build_horizon_profile(observer, observer_height_m=0.0, buildings=[building])
    east = hp.obstruction_elevation(90)
    west = hp.obstruction_elevation(270)
    assert east > 30.0  # 40 m tall at ~20 m -> steep angle
    assert west < 1.0


def test_gis_building_below_floor_does_not_block():
    observer = (LAT, LON)
    d = 2.0 / 111320.0
    building = {
        "height_m": 10.0,  # below a 12 m-high window
        "footprint": [
            (LAT - d, LON + d),
            (LAT + d, LON + d),
            (LAT + d, LON + 3 * d),
            (LAT - d, LON + 3 * d),
        ],
    }
    hp = build_horizon_profile(observer, observer_height_m=12.0, buildings=[building])
    assert max(hp.samples.values()) == 0.0


# --- events -----------------------------------------------------------------

def test_events_ordering_clean_horizon():
    # West-facing window, clean horizon. Expect: sunrise < first_light on a
    # west window (sun reaches a west wall after it crosses into the west) and
    # first_light < darkness.
    w = Window(facing_azimuth=270, view_half_angle=90)
    ev = compute_day_events(LAT, LON, w, date(2024, 6, 21), TZ)
    assert ev.sunrise is not None
    assert ev.sunset is not None
    assert ev.first_light is not None
    assert ev.darkness is not None
    # On a clean horizon the west window is lit until the sun sets.
    assert ev.first_light < ev.darkness
    assert ev.last_light <= ev.darkness + timedelta(minutes=1)


def test_south_window_lit_midday():
    w = Window(facing_azimuth=180, view_half_angle=90)
    ev = compute_day_events(LAT, LON, w, date(2024, 12, 21), TZ)
    # A south window in winter is lit around the middle of the day.
    assert ev.first_light is not None and ev.last_light is not None
    noon = datetime(2024, 12, 21, 11, 39, tzinfo=TZ)
    assert ev.first_light <= noon <= ev.last_light


# --- scheduler --------------------------------------------------------------

def _cfg(window: Window) -> AppConfig:
    return AppConfig(
        latitude=LAT,
        longitude=LON,
        timezone=TZ,
        timezone_name="Asia/Jerusalem",
        window=window,
        darkness_depth=0.0,
        shutter={"type": "mock"},
        open_on="first_light",
        close_on="darkness",
    )


def test_desired_state_transitions():
    cfg = _cfg(Window(facing_azimuth=270))
    ev = events_for(cfg, date(2024, 6, 21))
    before_open = ev.first_light - timedelta(minutes=5)
    after_open = ev.first_light + timedelta(minutes=5)
    after_close = ev.darkness + timedelta(minutes=5)
    assert desired_state_at(cfg, ev, before_open) == "closed"
    assert desired_state_at(cfg, ev, after_open) == "open"
    assert desired_state_at(cfg, ev, after_close) == "closed"


def test_scheduler_drives_full_day():
    cfg = _cfg(Window(facing_azimuth=270))
    controller = MockShutterController()

    # Simulate a clock that jumps straight to each scheduled wake time.
    clock = {"now": datetime(2024, 6, 21, 0, 0, tzinfo=TZ)}

    def now_fn():
        return clock["now"]

    def sleep_fn(seconds):
        clock["now"] = clock["now"] + timedelta(seconds=seconds)

    # Run until we've seen the open and the close actions.
    run_scheduler(cfg, controller, now_fn=now_fn, sleep_fn=sleep_fn, max_iterations=3)

    actions = [a for _, a in controller.history]
    # Start-of-day reconcile closes, then opens at first light, then closes at dark.
    assert "open" in actions
    assert actions[-1] == "close"
