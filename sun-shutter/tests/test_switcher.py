"""Tests for the Switcher Runner backend.

These do not require the optional `aioswitcher` package: construction and
config parsing are dependency-free, and the actual device call is monkey-
patched so open()/close() can be exercised without hardware or the library.
"""

import pytest

from sunshutter.shutter import build_controller
from sunshutter.switcher import SwitcherShutterController


def test_build_controller_selects_switcher_from_nested_block():
    cfg = {
        "type": "switcher",
        "switcher": {
            "device_type": "RUNNER",
            "ip_address": "192.168.1.50",
            "device_id": "abc123",
            "device_key": "18",
        },
    }
    controller = build_controller(cfg)
    assert isinstance(controller, SwitcherShutterController)
    assert controller.ip_address == "192.168.1.50"
    assert controller.open_position == 100
    assert controller.close_position == 0


def test_runner_does_not_require_token():
    c = SwitcherShutterController(
        device_type="runner",  # case-insensitive
        ip_address="10.0.0.5",
        device_id="id",
        device_key="key",
    )
    assert c.device_type_name == "RUNNER"
    assert c.token is None


def test_s11_requires_token():
    with pytest.raises(ValueError, match="requires a 'token'"):
        SwitcherShutterController(
            device_type="RUNNER_S11",
            ip_address="10.0.0.5",
            device_id="id",
            device_key="key",
        )


def test_unknown_device_type_rejected():
    with pytest.raises(ValueError, match="not a Switcher shutter"):
        SwitcherShutterController(
            device_type="WATER_HEATER",
            ip_address="10.0.0.5",
            device_id="id",
            device_key="key",
        )


def test_open_and_close_call_set_position(monkeypatch):
    c = SwitcherShutterController(
        device_type="RUNNER",
        ip_address="10.0.0.5",
        device_id="id",
        device_key="key",
        open_position=100,
        close_position=0,
        index=0,
    )

    calls = []

    def fake_run(position):
        calls.append(position)

    monkeypatch.setattr(c, "_run", fake_run)
    c.open()
    c.close()
    assert calls == [100, 0]


def test_custom_positions_and_index():
    c = SwitcherShutterController(
        device_type="RUNNER_MINI",
        ip_address="10.0.0.9",
        device_id="id",
        device_key="key",
        index=1,
        open_position=80,
        close_position=10,
    )
    assert c.index == 1
    assert c.open_position == 80
    assert c.close_position == 10
