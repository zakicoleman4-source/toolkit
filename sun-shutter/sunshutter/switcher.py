"""Switcher Runner shutter backend.

Switcher (the Israeli smart-home brand) sells the shutter/blind controllers
under the "Runner" name: Runner, Runner Mini, Runner S11, Runner S12. They are
controlled over the *local* network (no cloud round-trip) using the well-
maintained ``aioswitcher`` library — the same one Home Assistant's Switcher
integration uses.

To keep the rest of sunshutter dependency-free, ``aioswitcher`` is an OPTIONAL
dependency and is imported lazily, only when a Switcher shutter is actually
driven. Install it with::

    pip install "sunshutter[switcher]"      # or: pip install aioswitcher

What you need to configure a Runner (find these with ``sunshutter discover``):

  * device_type  -- RUNNER | RUNNER_MINI | RUNNER_S11 | RUNNER_S12
  * ip_address   -- the Runner's LAN IP (give it a DHCP reservation)
  * device_id    -- the Runner's device id
  * device_key   -- the Runner's device key (a.k.a. login key)
  * token        -- ONLY the newer S11/S12 need this; request it from Switcher
                    (they email a token tied to your account). RUNNER and
                    RUNNER_MINI leave it null.

Position is a percentage: 100 = fully open, 0 = fully closed. Both are
configurable in case a particular install is wired the other way round.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from .shutter import ShutterController

logger = logging.getLogger("sunshutter.switcher")

_SHUTTER_DEVICE_TYPES = {"RUNNER", "RUNNER_MINI", "RUNNER_S11", "RUNNER_S12"}
_TOKEN_REQUIRED = {"RUNNER_S11", "RUNNER_S12"}


class SwitcherShutterController(ShutterController):
    """Drive a Switcher Runner shutter over the local network."""

    def __init__(
        self,
        device_type: str,
        ip_address: str,
        device_id: str,
        device_key: str,
        token: Optional[str] = None,
        index: int = 0,
        open_position: int = 100,
        close_position: int = 0,
    ) -> None:
        dt = device_type.strip().upper()
        if dt not in _SHUTTER_DEVICE_TYPES:
            raise ValueError(
                f"device_type {device_type!r} is not a Switcher shutter; "
                f"expected one of {sorted(_SHUTTER_DEVICE_TYPES)}"
            )
        if dt in _TOKEN_REQUIRED and not token:
            raise ValueError(
                f"{dt} requires a 'token' (request one from Switcher and add it "
                "to the config); RUNNER / RUNNER_MINI do not need a token."
            )
        self.device_type_name = dt
        self.ip_address = ip_address
        self.device_id = device_id
        self.device_key = device_key
        self.token = token
        self.index = index
        self.open_position = open_position
        self.close_position = close_position

    # -- internals -----------------------------------------------------------

    def _resolve_device_type(self):
        """Import aioswitcher lazily and map the config name to its enum."""
        try:
            from aioswitcher.device import DeviceType  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError(
                "The 'aioswitcher' package is required to control a Switcher "
                "Runner. Install it with:  pip install \"sunshutter[switcher]\""
            ) from exc
        try:
            return DeviceType[self.device_type_name]
        except KeyError as exc:
            raise RuntimeError(
                f"aioswitcher has no DeviceType named {self.device_type_name!r}; "
                "your aioswitcher version may be too old — upgrade it."
            ) from exc

    async def _set_position_async(self, position: int) -> None:
        from aioswitcher.api import SwitcherApi  # type: ignore

        device_type = self._resolve_device_type()
        async with SwitcherApi(
            device_type,
            self.ip_address,
            self.device_id,
            self.device_key,
            self.token,
        ) as api:
            response = await api.set_position(position, self.index)
            logger.info(
                "[switcher] %s -> position %d%% (index %d): %s",
                self.device_type_name,
                position,
                self.index,
                "ok" if getattr(response, "successful", True) else "FAILED",
            )
            if not getattr(response, "successful", True):
                raise RuntimeError(
                    f"Switcher rejected set_position({position}); response={response!r}"
                )

    def _run(self, position: int) -> None:
        # The scheduler is synchronous and fires at most a couple of commands a
        # day, so spinning up a fresh event loop per command is perfectly fine.
        asyncio.run(self._set_position_async(position))

    # -- ShutterController ---------------------------------------------------

    def open(self) -> None:  # noqa: A003
        self._run(self.open_position)

    def close(self) -> None:
        self._run(self.close_position)


def build_switcher_controller(config: Dict[str, Any]) -> SwitcherShutterController:
    """Construct a SwitcherShutterController from a config dict."""
    return SwitcherShutterController(
        device_type=config["device_type"],
        ip_address=config["ip_address"],
        device_id=config["device_id"],
        device_key=config["device_key"],
        token=config.get("token"),
        index=int(config.get("index", 0)),
        open_position=int(config.get("open_position", 100)),
        close_position=int(config.get("close_position", 0)),
    )


async def discover_devices_async(timeout: float = 12.0) -> list:
    """Listen for Switcher devices broadcasting on the LAN.

    Returns a list of plain dicts describing each device seen within `timeout`
    seconds (Switcher devices broadcast their state roughly every 4 seconds).
    Requires the optional ``aioswitcher`` dependency.
    """
    try:
        from aioswitcher.bridge import SwitcherBridge  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on install
        raise RuntimeError(
            "The 'aioswitcher' package is required for discovery. Install it "
            'with:  pip install "sunshutter[switcher]"'
        ) from exc

    seen: Dict[str, dict] = {}

    def on_device_found(device) -> None:
        info = {
            "name": getattr(device, "name", None),
            "device_id": getattr(device, "device_id", None),
            "device_key": getattr(device, "device_key", None),
            "ip_address": getattr(device, "ip_address", None),
            "device_type": getattr(getattr(device, "device_type", None), "name", None),
        }
        if info["device_id"]:
            seen[info["device_id"]] = info

    async with SwitcherBridge(on_device_found):
        await asyncio.sleep(timeout)

    return list(seen.values())
