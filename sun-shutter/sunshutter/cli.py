"""Command-line interface.

    python -m sunshutter now      --config config.json
    python -m sunshutter today    --config config.json [--date YYYY-MM-DD]
    python -m sunshutter forecast --config config.json [--days N]
    python -m sunshutter run      --config config.json

`now`/`today`/`forecast` are read-only and safe to run anywhere. `run` starts
the always-on control loop that actually drives the shutter.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta

from .config import load_config
from .events import compute_day_events
from .scheduler import _close_time, _open_time, events_for, run_scheduler
from .shutter import build_controller
from .solar import sun_position


def _fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z") if dt else "does not occur"


def cmd_now(args) -> int:
    cfg = load_config(args.config)
    now = datetime.now(cfg.timezone)
    pos = sun_position(cfg.latitude, cfg.longitude, now)
    lit = cfg.window.is_lit(pos.elevation, pos.azimuth)
    print(f"Location : {cfg.latitude:.5f}, {cfg.longitude:.5f} ({cfg.timezone_name})")
    print(f"Time     : {_fmt(now)}")
    print(f"Sun      : elevation {pos.elevation:6.2f} deg, azimuth {pos.azimuth:6.2f} deg")
    print(f"Window   : faces {cfg.window.facing_azimuth:.0f} deg  ({cfg.window.label})")
    print(f"Sunlight on window: {'YES' if lit else 'no'}")
    return 0


def _print_day(cfg, day: date) -> None:
    ev = events_for(cfg, day)
    print(f"== {day.isoformat()} ==")
    print(f"  sunrise      : {_fmt(ev.sunrise)}")
    print(f"  first light  : {_fmt(ev.first_light)}   <- OPEN trigger" if cfg.open_on == "first_light" else f"  first light  : {_fmt(ev.first_light)}")
    print(f"  last light   : {_fmt(ev.last_light)}")
    print(f"  darkness     : {_fmt(ev.darkness)}   <- CLOSE trigger" if cfg.close_on == "darkness" else f"  darkness     : {_fmt(ev.darkness)}")
    print(f"  sunset       : {_fmt(ev.sunset)}")
    print(f"  -> OPEN  at  : {_fmt(_open_time(cfg, ev))}")
    print(f"  -> CLOSE at  : {_fmt(_close_time(cfg, ev))}")


def cmd_today(args) -> int:
    cfg = load_config(args.config)
    day = date.fromisoformat(args.date) if args.date else datetime.now(cfg.timezone).date()
    _print_day(cfg, day)
    return 0


def cmd_forecast(args) -> int:
    cfg = load_config(args.config)
    start = datetime.now(cfg.timezone).date()
    for i in range(args.days):
        _print_day(cfg, start + timedelta(days=i))
    return 0


def cmd_discover(args) -> int:
    import asyncio

    from .switcher import discover_devices_async

    print(f"Listening for Switcher devices on the LAN for {args.timeout:.0f}s ...")
    try:
        devices = asyncio.run(discover_devices_async(timeout=args.timeout))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    if not devices:
        print("No devices found. Ensure this machine is on the same network/subnet")
        print("as the Runner, and that broadcast traffic is not blocked.")
        return 1
    for d in devices:
        print("-" * 48)
        print(f"  name       : {d.get('name')}")
        print(f"  device_type: {d.get('device_type')}")
        print(f"  device_id  : {d.get('device_id')}")
        print(f"  device_key : {d.get('device_key')}")
        print(f"  ip_address : {d.get('ip_address')}")
    print("-" * 48)
    print("Copy device_type / device_id / device_key / ip_address into the")
    print('shutter block of config.json (type: \"switcher\"). S11/S12 also need a')
    print("token from Switcher.")
    return 0


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    controller = build_controller(cfg.shutter)
    logging.info("Starting shutter control loop (Ctrl-C to stop)")
    try:
        run_scheduler(cfg, controller)
    except KeyboardInterrupt:
        logging.info("Stopped.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sunshutter", description="Sun-driven shutter control.")
    p.add_argument("--config", default="config.json", help="Path to config JSON.")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("now", help="Show the current sun position and window state.").set_defaults(func=cmd_now)

    t = sub.add_parser("today", help="Show today's open/close trigger times.")
    t.add_argument("--date", help="Evaluate a specific day (YYYY-MM-DD).")
    t.set_defaults(func=cmd_today)

    f = sub.add_parser("forecast", help="Show trigger times for the next N days.")
    f.add_argument("--days", type=int, default=7)
    f.set_defaults(func=cmd_forecast)

    d = sub.add_parser("discover", help="Find Switcher devices on the LAN (needs aioswitcher).")
    d.add_argument("--timeout", type=float, default=12.0, help="Seconds to listen.")
    d.set_defaults(func=cmd_discover)

    sub.add_parser("run", help="Run the always-on control loop.").set_defaults(func=cmd_run)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)
