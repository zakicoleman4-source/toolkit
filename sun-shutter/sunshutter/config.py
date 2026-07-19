"""Load and validate configuration from a JSON file.

One file describes the whole installation: where the flat is, which way the
window faces, how dark counts as dark, and how to talk to the shutter hub.
Kept deliberately small and explicit so a non-programmer can edit it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Any, Dict
from zoneinfo import ZoneInfo

from .window import HorizonProfile, Window


@dataclass
class AppConfig:
    latitude: float
    longitude: float
    timezone: tzinfo
    timezone_name: str
    window: Window
    darkness_depth: float
    shutter: Dict[str, Any]
    # What to do at each trigger. Defaults match the friend's request:
    # open at first light, close at darkness.
    open_on: str = "first_light"   # first_light | sunrise
    close_on: str = "darkness"     # darkness | last_light | sunset

    raw: Dict[str, Any] = field(default_factory=dict)


def _window_from_config(w: Dict[str, Any]) -> Window:
    horizon = HorizonProfile()
    hz = w.get("horizon")
    if isinstance(hz, dict):
        samples = hz.get("samples") or {}
        horizon = HorizonProfile(
            samples={float(k): float(v) for k, v in samples.items()},
            default_elevation=float(hz.get("default_elevation", 0.0)),
        )
    return Window(
        facing_azimuth=float(w["facing_azimuth"]),
        view_half_angle=float(w.get("view_half_angle", 90.0)),
        min_sun_elevation=float(w.get("min_sun_elevation", 0.0)),
        horizon=horizon,
        label=str(w.get("label", "window")),
    )


def load_config(path: str) -> AppConfig:
    """Read and parse a config JSON file into an AppConfig."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    loc = raw["location"]
    tz_name = loc.get("timezone", "Asia/Jerusalem")

    return AppConfig(
        latitude=float(loc["latitude"]),
        longitude=float(loc["longitude"]),
        timezone=ZoneInfo(tz_name),
        timezone_name=tz_name,
        window=_window_from_config(raw["window"]),
        darkness_depth=float(raw.get("darkness_depth", 0.0)),
        shutter=raw.get("shutter", {"type": "mock"}),
        open_on=raw.get("open_on", "first_light"),
        close_on=raw.get("close_on", "darkness"),
        raw=raw,
    )
