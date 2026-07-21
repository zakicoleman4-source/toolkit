"""Turn sun geometry into the two moments we care about each day.

For a given day, location and window we want:

  * first_light  -- the instant direct sun first reaches the window
                    (the "open the shutter" trigger), and
  * last_light   -- the instant direct sun last leaves the window, and
  * darkness     -- the instant the sky goes dark (the "close the shutter"
                    trigger), defined by a configurable sun-below-horizon
                    depth (0 = geometric sunset, -6 = end of civil twilight).

We find these by scanning the day at a coarse step to locate each
transition, then binary-searching the transition to the second. That keeps
the code dependency-free and robust to any horizon profile, however lumpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Callable, List, Optional

from .solar import sun_position
from .window import Window


@dataclass
class DayEvents:
    """The trigger moments for one calendar day (all timezone-aware)."""

    day: date
    first_light: Optional[datetime]  # sun first reaches the window -> OPEN
    last_light: Optional[datetime]   # sun last leaves the window
    darkness: Optional[datetime]     # sky goes dark -> CLOSE
    sunrise: Optional[datetime]
    sunset: Optional[datetime]


def _refine(
    predicate: Callable[[datetime], bool],
    before: datetime,
    after: datetime,
    resolution: timedelta = timedelta(seconds=15),
) -> datetime:
    """Binary-search the boundary where `predicate` flips between two times.

    `predicate(before)` and `predicate(after)` are assumed to differ. Returns
    the earliest time (to within `resolution`) at which `predicate` holds the
    same value as it does at `after`.
    """
    target = predicate(after)
    lo, hi = before, after
    while hi - lo > resolution:
        mid = lo + (hi - lo) / 2
        if predicate(mid) == target:
            hi = mid
        else:
            lo = mid
    return hi


def _scan_transitions(
    predicate: Callable[[datetime], bool],
    start: datetime,
    end: datetime,
    step: timedelta,
) -> List[tuple]:
    """Return (was, now, t_prev, t_now) tuples where `predicate` changes."""
    transitions = []
    t_prev = start
    prev = predicate(t_prev)
    t = start + step
    while t <= end:
        cur = predicate(t)
        if cur != prev:
            transitions.append((prev, cur, t_prev, t))
        prev = cur
        t_prev = t
        t += step
    return transitions


def compute_day_events(
    latitude: float,
    longitude: float,
    window: Window,
    day: date,
    tz: tzinfo,
    darkness_depth: float = 0.0,
    scan_step: timedelta = timedelta(minutes=2),
) -> DayEvents:
    """Compute the open/close trigger moments for one local day.

    Args:
        latitude, longitude: Observer location in degrees.
        window: The window whose light we track.
        day: The local calendar day to evaluate.
        tz: Local timezone (e.g. ZoneInfo("Asia/Jerusalem")). All returned
            datetimes are in this timezone.
        darkness_depth: How far the sun must sink below the horizon before we
            call it "dark". 0 = geometric sunset, -6 = end of civil twilight,
            -0.833 = the standard sunrise/sunset definition including the
            solar disc radius and refraction.
        scan_step: Coarse scan granularity for locating transitions.

    Returns:
        A DayEvents. Any field is None if that transition does not occur on
        the day (e.g. polar day/night, or a window the sun never reaches).
    """
    start = datetime.combine(day, time(0, 0), tzinfo=tz)
    end = start + timedelta(days=1)

    def lit(t: datetime) -> bool:
        pos = sun_position(latitude, longitude, t)
        return window.is_lit(pos.elevation, pos.azimuth)

    def bright(t: datetime) -> bool:
        # "Not dark" — sun above the darkness threshold, ignoring the window.
        pos = sun_position(latitude, longitude, t)
        return pos.elevation >= darkness_depth

    def above_horizon(t: datetime) -> bool:
        pos = sun_position(latitude, longitude, t)
        return pos.elevation >= -0.833  # standard sunrise/sunset altitude

    lit_transitions = _scan_transitions(lit, start, end, scan_step)
    first_light = None
    last_light = None
    for was, now, tp, tn in lit_transitions:
        boundary = _refine(lit, tp, tn)
        if now and first_light is None:  # became lit
            first_light = boundary
        if not now:  # became unlit
            last_light = boundary

    # Darkness: the evening transition from bright -> dark.
    darkness = None
    for was, now, tp, tn in _scan_transitions(bright, start, end, scan_step):
        if was and not now:  # bright -> dark
            darkness = _refine(bright, tp, tn)

    sunrise = None
    sunset = None
    for was, now, tp, tn in _scan_transitions(above_horizon, start, end, scan_step):
        boundary = _refine(above_horizon, tp, tn)
        if now:
            sunrise = boundary
        else:
            sunset = boundary

    return DayEvents(
        day=day,
        first_light=first_light,
        last_light=last_light,
        darkness=darkness,
        sunrise=sunrise,
        sunset=sunset,
    )
