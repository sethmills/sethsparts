# LED "find the part" controller

Source for the two pieces that live outside this Django app but make the
drawer-detail "Locate" button work (see `docs/HANDOFF.md` item 3 for full
context). Kept here for version control/backup — **not** auto-deployed by
`git pull` like the main app; copy changes to the Pi manually (scp). Firmware
changes go to the board with `pi/flash-scorpio.py` (see "Flashing the board").

- `pi/server.py` — small stdlib-only HTTP service that runs on the Raspberry
  Pi as the `led-controller` systemd service (`pi/led-controller.service`),
  listening on `127.0.0.1:9000` behind its own Cloudflare Tunnel
  (`led.sethsparts.com`). Receives `POST /locate` from the Django app and
  relays it to the Scorpio over USB serial. `SCORPIO_SERIAL_PORT` in
  `/etc/led-controller/env` should point at the board's **data** channel —
  the `-if02` path under `/dev/serial/by-id/`, not a bare `/dev/ttyACM0`:
  the board exposes two serial channels and only one of them answers commands.
- `pi/flash-scorpio.py` — interactive, guided firmware installer for the board.
  Run it on the Pi; both it and the app's setup wizard explain it.
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

## Flashing the board

`pi/flash-scorpio.py` does this, and it is the script the app's setup wizard tells you to
run (**Settings → Flash the LED controller**). Copy it to the Pi and run it *there*,
because that is where the board's USB is:

    scp pi/flash-scorpio.py pi:~/led-controller/pi/
    ssh pi python3 ~/led-controller/pi/flash-scorpio.py

It is interactive on purpose — the parts it cannot do for you are physical (holding a
button, watching whether strips light up), and those are the parts people get wrong from
written instructions alone. It covers both situations:

- **A board that has never had CircuitPython on it.** Hold the **BOOTSEL** button, plug
  the USB cable into the Pi, then let go: the board appears as a USB drive called
  `RPI-RP2`. The script then installs CircuitPython itself (it needs the Feather RP2040
  **Scorpio** image from
  <https://circuitpython.org/board/adafruit_feather_rp2040_scorpio/> — pass it with
  `--uf2`, or drop it in `scorpio-firmware/`), then the libraries the firmware imports
  (`adafruit_neopxl8` and its dependencies, via the official `circup` or the Adafruit
  bundle zip), then `boot.py` and `code.py`.
- **A board already running CircuitPython** — it shows up as `CIRCUITPY` instead. No
  BOOTSEL, no UF2, no libraries: just the two firmware files. This is the ordinary case
  when updating.

`python3 pi/flash-scorpio.py --check` verifies the current state without changing
anything, which is also what the app's "Check the board" button does from the other side.

**Two traps, both of which cost an evening here:**

1. `boot.py` calls `usb_cdc.enable()` to expose the second (data) serial channel, and that
   only takes effect after a **true hardware reset** — the board's reset button, or
   `microcontroller.reset()` from its REPL. A soft reset (Ctrl-D) re-runs the code but does
   not re-enumerate USB, so the channel silently stays missing and every command times out.
2. Because that gives the board two serial channels, a bare `/dev/ttyACM0` is ambiguous.
   `SCORPIO_SERIAL_PORT` in `/etc/led-controller/env` must point at the **`-if02`** path
   under `/dev/serial/by-id/`. `-if00` is CircuitPython's console/REPL and will not answer
   commands. Then `sudo systemctl restart led-controller`.

The script checks both, and says which one is wrong rather than just failing.
