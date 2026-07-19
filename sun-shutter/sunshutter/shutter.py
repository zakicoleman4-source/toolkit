"""Shutter controllers — the thing that actually moves the blinds.

The scheduler only ever calls `open()` and `close()` on a controller, so any
brand of automation hub can be supported by writing one small subclass. Two
are provided:

  * MockShutterController  -- logs actions and remembers state; use it to dry-
    run the whole system with no hardware.
  * HttpShutterController   -- a fill-in-the-blanks template that fires an HTTP
    request per action, using only urllib (no dependencies). Once your friend
    shares the real hub API, set the URL/method/headers/body in config and it
    works.

Keeping this behind an interface means the sun maths and the scheduling never
need to know which hub is on the other end.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger("sunshutter.shutter")


class ShutterController:
    """Abstract shutter. Subclass and implement open()/close()."""

    def open(self) -> None:  # noqa: A003 - deliberately named like the action
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class MockShutterController(ShutterController):
    """A controller that moves nothing but records what it was asked to do.

    Handy for testing the schedule end-to-end and for a first dry run against
    real sun times before any hardware is wired up.
    """

    def __init__(self) -> None:
        self.state: Optional[str] = None
        self.history: list[tuple[str, str]] = []  # (iso_time_or_'', action)

    def open(self) -> None:  # noqa: A003
        self.state = "open"
        self.history.append(("", "open"))
        logger.info("[mock] shutter OPEN")

    def close(self) -> None:
        self.state = "closed"
        self.history.append(("", "close"))
        logger.info("[mock] shutter CLOSE")


class HttpShutterController(ShutterController):
    """Generic HTTP controller — one request to open, one to close.

    Configure with whatever the real hub expects. Everything is optional
    beyond the URLs. Body may contain no placeholders; it is sent verbatim.

    Example config (JSON):
        {
          "open":  {"url": "http://hub.local/api/shutter/1/up",
                    "method": "POST"},
          "close": {"url": "http://hub.local/api/shutter/1/down",
                    "method": "POST"},
          "headers": {"Authorization": "Bearer <token>"},
          "timeout": 10
        }
    """

    def __init__(
        self,
        open_request: Dict[str, Any],
        close_request: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 10.0,
    ) -> None:
        self._open = open_request
        self._close = close_request
        self._headers = headers or {}
        self._timeout = timeout

    def _fire(self, spec: Dict[str, Any], action: str) -> None:
        url = spec["url"]
        method = spec.get("method", "POST").upper()
        headers = {**self._headers, **spec.get("headers", {})}

        data: Optional[bytes] = None
        body = spec.get("body")
        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            else:
                data = str(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                logger.info("[http] shutter %s -> %s %s", action, resp.status, url)
        except urllib.error.URLError as exc:  # network/HTTP failure
            logger.error("[http] shutter %s FAILED (%s): %s", action, url, exc)
            raise

    def open(self) -> None:  # noqa: A003
        self._fire(self._open, "OPEN")

    def close(self) -> None:
        self._fire(self._close, "CLOSE")


def build_controller(config: Dict[str, Any]) -> ShutterController:
    """Construct a controller from a config dict.

    config["type"] selects the backend: "mock" (default) or "http".
    """
    kind = (config or {}).get("type", "mock").lower()
    if kind == "mock":
        return MockShutterController()
    if kind == "http":
        return HttpShutterController(
            open_request=config["open"],
            close_request=config["close"],
            headers=config.get("headers"),
            timeout=config.get("timeout", 10.0),
        )
    raise ValueError(f"Unknown shutter controller type: {kind!r}")
