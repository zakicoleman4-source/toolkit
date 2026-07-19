"""sunshutter — sun-position-driven window shutter control.

A small, dependency-free toolkit that computes where the sun is in the sky
for a specific window (accounting for surrounding buildings via GIS data) and
drives an automatic shutter so it opens the moment sunlight reaches the glass
and closes when it goes dark.

Public surface:
    sun_position, SunPosition        -- solar geometry (solar.py)
    Window, HorizonProfile           -- window model (window.py)
    compute_day_events, DayEvents    -- daily triggers (events.py)
    build_horizon_profile            -- GIS -> horizon (gis.py)
    ShutterController, ...            -- hardware backends (shutter.py)
    load_config, AppConfig           -- configuration (config.py)
    run_scheduler                    -- the control loop (scheduler.py)
"""

from .config import AppConfig, load_config
from .events import DayEvents, compute_day_events
from .gis import build_horizon_profile
from .scheduler import run_scheduler
from .shutter import (
    HttpShutterController,
    MockShutterController,
    ShutterController,
    build_controller,
)
from .solar import SunPosition, sun_position
from .window import HorizonProfile, Window

__version__ = "0.1.0"

__all__ = [
    "AppConfig",
    "load_config",
    "DayEvents",
    "compute_day_events",
    "build_horizon_profile",
    "run_scheduler",
    "ShutterController",
    "MockShutterController",
    "HttpShutterController",
    "build_controller",
    "SunPosition",
    "sun_position",
    "HorizonProfile",
    "Window",
]
