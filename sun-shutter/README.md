# sunshutter

Open a window shutter the moment sunlight actually reaches the glass, and
close it when it goes dark — automatically, every day, for a specific flat.

This is a small, **dependency-free** Python project (standard library only, so
it runs on anything down to a Raspberry Pi next to the shutter motor). It is
self-contained in this folder and can be lifted straight into its own Git repo.

## The idea

A friend in **Netanya, Israel** has motorised shutters with an API. He wants
them to:

- **open** the instant the first beam of direct sun reaches his window, and
- **close** the instant it gets dark.

"When the sun reaches *his* window" is not the same as "sunrise". A west-facing
flat on the 8th floor sees the sun much later than a rooftop, and neighbouring
buildings block the low sun. So the project has two halves:

1. **Where is the sun?** A solar-position engine computes the sun's elevation
   and azimuth for his exact latitude/longitude at any instant
   (`solar.py`, NOAA algorithm, accurate to a fraction of a degree).
2. **Does that light reach his window?** A window model combines which way the
   glass faces with an *obstruction horizon* — how high the sun must climb to
   clear surrounding buildings — which we build from the open **Netanya GIS
   building data** and his floor height (`window.py`, `gis.py`).

From those, `events.py` finds the exact open/close moments each day and
`scheduler.py` drives the shutter through a pluggable controller
(`shutter.py`).

## Quick start

```bash
cd sun-shutter
cp config.example.json config.json      # edit for the real flat

# Where is the sun right now, and is the window lit?
python -m sunshutter --config config.json now

# Today's open/close trigger times
python -m sunshutter --config config.json today

# The next week of triggers
python -m sunshutter --config config.json forecast --days 7

# Run the always-on control loop (drives the shutter)
python -m sunshutter --config config.json run
```

With the default config (`shutter.type = "mock"`) the loop logs what it *would*
do and touches no hardware — perfect for a dry run before anything is wired up.

## Configuration

Everything lives in one JSON file (`config.example.json` is documented):

- `location` — latitude, longitude, timezone.
- `window.facing_azimuth` — compass bearing the glass faces
  (0 = N, 90 = E, 180 = S, 270 = W).
- `window.view_half_angle` — horizontal field of view (90 = a flat wall).
- `window.horizon.samples` — obstruction elevation per azimuth (from GIS).
- `darkness_depth` — how far the sun drops below the horizon before "dark"
  (`0` = geometric sunset, `-0.833` = standard sunset, `-6` = end of civil
  twilight).
- `open_on` / `close_on` — which computed event fires each action.
- `shutter` — `mock` for dry runs, or `http` with the real hub URLs.

## Wiring up the real shutter

The scheduler only ever calls `open()` / `close()` on a controller, so any hub
is supported by configuration or a tiny subclass. Three backends ship today:
`mock` (dry run), `switcher` (Switcher Runner), and `http` (generic).

### Switcher Runner (the friend's shutter)

Switcher's shutter/blind products are the **Runner** line (Runner, Runner
Mini, Runner S11, Runner S12). They're controlled over the **local network**
(no cloud) via the `aioswitcher` library — the same one Home Assistant uses.
It's an **optional** dependency, so install it only for the real device:

```bash
pip install "sunshutter[switcher]"     # or: pip install aioswitcher
```

Find the Runner on the LAN (run this on a machine on the same subnet):

```bash
python -m sunshutter discover
#   device_type: RUNNER
#   device_id  : abcd12
#   device_key : 18
#   ip_address : 192.168.1.50
```

Then set the `switcher` block in `config.json`:

```json
"shutter": {
  "type": "switcher",
  "switcher": {
    "device_type": "RUNNER",
    "ip_address": "192.168.1.50",
    "device_id": "abcd12",
    "device_key": "18",
    "token": null,
    "index": 0,
    "open_position": 100,
    "close_position": 0
  }
}
```

Notes:
- Give the Runner a **static / DHCP-reserved IP** so it doesn't move.
- `token` is needed **only** for the newer **S11 / S12** (request it from
  Switcher — they email a token tied to your account). Leave it `null` for
  `RUNNER` / `RUNNER_MINI`.
- Position is a percentage: `100` = open, `0` = closed (swap them if a
  particular install is wired the other way).

### Generic HTTP hub

For any other hub with an HTTP API:

```json
"shutter": {
  "type": "http",
  "open":  {"url": "http://hub.local/api/shutter/1/up",   "method": "POST"},
  "close": {"url": "http://hub.local/api/shutter/1/down", "method": "POST"},
  "headers": {"Authorization": "Bearer <token>"},
  "timeout": 10
}
```

If a hub speaks some other protocol entirely, subclass `ShutterController`
(see `switcher.py` for a worked example) and return it from
`build_controller`.

## Using the Netanya GIS building data

The open building layer gives building footprints and heights (or floor
counts). Clip it to the neighbourhood, convert to `(lat, lon)` polygons, and:

```python
from sunshutter.gis import build_horizon_profile

buildings = [
    {"height_m": 24.0, "footprint": [(32.321, 34.853), (32.321, 34.854), ...]},
    # ...neighbouring buildings...
]

horizon = build_horizon_profile(
    observer=(32.3215, 34.8532),   # the window's coordinates
    observer_height_m=21.0,        # his floor height (floor number x ~3 m)
    buildings=buildings,
)
# horizon.samples -> paste into config.json under window.horizon.samples
```

`build_horizon_profile` walks each building outline, works out how high each
rooftop sits above the window as an elevation angle, and keeps the tallest
obstruction per compass direction. See `examples/gis_horizon_example.py` for a
runnable demo. Once the real GIS extract and hub API are in hand, the details
slot into `config.json` with no code changes.

## Project layout

```
sun-shutter/
  sunshutter/
    solar.py       NOAA solar position (elevation + azimuth)
    window.py      window facing + obstruction-horizon model
    gis.py         GIS buildings -> obstruction horizon
    events.py      daily first-light / darkness triggers
    shutter.py     shutter controllers (mock + HTTP template)
    switcher.py    Switcher Runner backend (optional aioswitcher dep)
    scheduler.py   the always-on control loop
    config.py      config loading
    cli.py         command-line interface
  tests/           unit tests (run with: python -m pytest)
  config.example.json
  examples/gis_horizon_example.py
```

## Tests

```bash
python -m pytest tests/ -q
```

## Status / next steps

Working today: solar engine, window+horizon model, GIS→horizon conversion,
daily event computation, scheduler, mock + **Switcher Runner** + HTTP shutter
backends, LAN discovery, CLI, tests.

To finish for the real installation:
1. Get the real Netanya GIS extract for his block and his floor height →
   generate `window.horizon.samples`.
2. Run `python -m sunshutter discover` on his network → fill in the `switcher`
   block (and get a token from Switcher if it's a Runner S11/S12).
3. Deploy the `run` loop on an always-on device (systemd unit / cron `@reboot`).
