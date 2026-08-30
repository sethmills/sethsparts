# LED "find the part" controller

Source for the two pieces that live outside this Django app but make the
drawer-detail "Locate" button work (see `docs/HANDOFF.md` item 3 for full
context). Kept here for version control/backup — **not** auto-deployed by
`git pull` like the main app; copy changes to the Pi manually (scp) and to
the Scorpio's `CIRCUITPY` drive manually (or over SSH once it's mounted).

- `pi/server.py` — small stdlib-only HTTP service that runs on the Raspberry
  Pi as the `led-controller` systemd service (`pi/led-controller.service`),
  listening on `127.0.0.1:9000` behind its own Cloudflare Tunnel
  (`led.sethsparts.com`). Receives `POST /locate` from the Django app and
  relays it to the Scorpio over USB serial (`/dev/ttyACM0` by default).
- `pi/strip_map.json.example` — the **real** file lives at
  `/home/seth/led-controller/strip_map.json` on the Pi and is deliberately
  not synced from git (a `git pull`-driven overwrite would clobber Seth's
  real mapping). Maps logical strip names (matching `Drawer.led_strip` in
  Seth's Parts admin) to the Scorpio's physical channel number (0-7) — fill
  it in once the cabinet wiring is decided.
- `scorpio-firmware/boot.py` / `code.py` — CircuitPython firmware for the
  Feather RP2040 Scorpio (Adafruit #5650), using the `adafruit_neopxl8`
  library. Parses `{"cmd": "locate"/"clear"/"ping", ...}` JSON lines from a
  dedicated USB "data" serial channel and drives the matching NeoPXL8
  channel/pixel range, auto-clearing after `duration_ms`.

Both env secrets (`LED_CONTROLLER_KEY` on the Pi's
`/etc/led-controller/env`, and the matching value in Hetzner's
`/opt/sethsparts/.env`) must stay in sync — neither is committed here.
