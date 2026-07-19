"""The always-on loop: compute today's triggers and act on them on time.

Design goals:
  * Never miss a trigger even if the process starts mid-day or the machine
    was asleep — on startup we set the shutter to the state it *should*
    currently be in, then wait for the next boundary.
  * Recompute every day (sun times drift ~1-2 minutes/day, plus DST).
  * Be interruptible and testable — the sleeping is injected, so tests can
    drive a whole simulated day in milliseconds.

This is intentionally single-threaded and dependency-free.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from .config import AppConfig
from .events import DayEvents, compute_day_events
from .shutter import ShutterController

logger = logging.getLogger("sunshutter.scheduler")


def _open_time(cfg: AppConfig, ev: DayEvents) -> Optional[datetime]:
    return ev.sunrise if cfg.open_on == "sunrise" else ev.first_light


def _close_time(cfg: AppConfig, ev: DayEvents) -> Optional[datetime]:
    if cfg.close_on == "sunset":
        return ev.sunset
    if cfg.close_on == "last_light":
        return ev.last_light
    return ev.darkness


def desired_state_at(cfg: AppConfig, ev: DayEvents, when: datetime) -> Optional[str]:
    """What state the shutter should be in at `when` given today's events.

    Returns "open", "closed", or None if it cannot be determined (e.g. an
    event is missing). The rule: open between the open trigger and the close
    trigger, closed otherwise.
    """
    ot = _open_time(cfg, ev)
    ct = _close_time(cfg, ev)
    if ot is None or ct is None:
        return None
    if ot <= when < ct:
        return "open"
    return "closed"


def events_for(cfg: AppConfig, day: date) -> DayEvents:
    return compute_day_events(
        latitude=cfg.latitude,
        longitude=cfg.longitude,
        window=cfg.window,
        day=day,
        tz=cfg.timezone,
        darkness_depth=cfg.darkness_depth,
    )


def run_scheduler(
    cfg: AppConfig,
    controller: ShutterController,
    now_fn: Callable[[], datetime] = None,
    sleep_fn: Callable[[float], None] = _time.sleep,
    max_iterations: Optional[int] = None,
) -> None:
    """Run the control loop.

    Args:
        cfg: Loaded application config.
        controller: The shutter to drive.
        now_fn: Returns the current timezone-aware datetime. Defaults to the
            real clock in the configured timezone. Injectable for tests.
        sleep_fn: Sleeps for a number of seconds. Injectable for tests.
        max_iterations: Stop after this many trigger actions (for tests). None
            runs forever.
    """
    if now_fn is None:
        def now_fn() -> datetime:  # real wall clock in local tz
            return datetime.now(cfg.timezone)

    iterations = 0
    current_day: Optional[date] = None
    events: Optional[DayEvents] = None
    last_state: Optional[str] = None

    while True:
        now = now_fn()

        # (Re)compute events at startup and at each day rollover.
        if events is None or now.date() != current_day:
            current_day = now.date()
            events = events_for(cfg, current_day)
            logger.info(
                "Events for %s: first_light=%s darkness=%s (open_on=%s close_on=%s)",
                current_day,
                _fmt(_open_time(cfg, events)),
                _fmt(_close_time(cfg, events)),
                cfg.open_on,
                cfg.close_on,
            )

        # Reconcile: make the shutter match where we should be right now.
        desired = desired_state_at(cfg, events, now)
        if desired is not None and desired != last_state:
            _apply(controller, desired)
            last_state = desired
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return

        # Figure out the next moment something should change.
        wake = _next_boundary(cfg, events, now)
        if wake is None:
            # No more transitions today; wake shortly after midnight to
            # recompute for the new day.
            wake = datetime.combine(
                current_day + timedelta(days=1),
                datetime.min.time(),
                tzinfo=cfg.timezone,
            ) + timedelta(seconds=30)

        delay = (wake - now).total_seconds()
        if delay <= 0:
            delay = 1.0
        logger.debug("Sleeping %.0fs until %s", delay, _fmt(wake))
        sleep_fn(delay)


def _next_boundary(cfg: AppConfig, ev: DayEvents, now: datetime) -> Optional[datetime]:
    candidates = [t for t in (_open_time(cfg, ev), _close_time(cfg, ev)) if t and t > now]
    return min(candidates) if candidates else None


def _apply(controller: ShutterController, state: str) -> None:
    if state == "open":
        controller.open()
    else:
        controller.close()


def _fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%H:%M:%S") if dt else "--"
