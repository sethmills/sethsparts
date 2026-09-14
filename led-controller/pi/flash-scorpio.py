#!/usr/bin/env python3
"""Put the LED controller's firmware onto a Feather RP2040 Scorpio, guided.

Run this **on the Raspberry Pi the board is plugged into**, over SSH:

    python3 ~/led-controller/pi/flash-scorpio.py

It is the script the app's setup wizard tells you to run (`Settings -> Flash the LED
controller`), and it is interactive on purpose: the parts it cannot do for you are physical
(holding a button, watching whether strips light up), and the parts it can do are the ones
people get wrong from written instructions alone.

**Two routes, because there are two situations.**

* *A board that has never had CircuitPython on it* — it has to be put into its bootloader
  first (hold BOOTSEL, plug in USB), which mounts it as `RPI-RP2`. Then a CircuitPython
  `.uf2` goes onto it, the board reboots as `CIRCUITPY`, the libraries go into `lib/`, and
  finally `boot.py` + `code.py`.
* *A board already running CircuitPython* — only `boot.py` / `code.py` change. No BOOTSEL,
  no UF2, no libraries. This is the common case when iterating on the firmware.

**The trap that costs an evening**, recorded here because it cost one: `boot.py` calls
`usb_cdc.enable()` to expose a second serial channel for the protocol. That only takes
effect after a **true hardware reset** — press the board's reset button, or `microcontroller
.reset()` from the REPL. A soft reset (Ctrl-D) re-runs `boot.py` and `code.py` but does *not*
re-enumerate USB, so the data channel silently stays missing and every command times out.
The script checks for the channel and says so if it is absent.

Exit codes: 0 done, 1 something needs attention (the summary says what).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BOOTLOADER_LABELS = ("RPI-RP2", "RP2350")   # RP2040 boards mount as RPI-RP2; RP2350 boards differ
FIRMWARE_LABEL = "CIRCUITPY"

# Where a desktop Linux mounts removable volumes, in the order worth looking.
MOUNT_ROOTS = (
    "/media/{user}", "/run/media/{user}", "/media", "/run/media", "/mnt",
)

BOARD_PAGE = "https://circuitpython.org/board/adafruit_feather_rp2040_scorpio/"
BUNDLE_PAGE = "https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases/latest"

# What the firmware imports, so a fresh board can be told what it is missing. circup
# resolves these itself if it is installed; otherwise they come from the bundle zip.
REQUIRED_LIBRARIES = ("adafruit_neopxl8", "adafruit_pioasm", "adafruit_pixelbuf")

BRIDGE_URL = "http://127.0.0.1:9000"
ENV_FILE = Path("/etc/led-controller/env")
SERIAL_BY_ID = Path("/dev/serial/by-id")


# ---------------------------------------------------------------------------
# The parts worth testing: no hardware, no prompts, no side effects
# ---------------------------------------------------------------------------


def mount_roots(user: str | None = None) -> list[Path]:
    user = user or os.environ.get("USER") or os.environ.get("LOGNAME") or "pi"
    return [Path(root.format(user=user)) for root in MOUNT_ROOTS]


def find_mount(label: str, roots=None) -> Path | None:
    """The first mounted volume with this label, or None.

    `roots` is injectable so the search can be tested against a temporary directory tree
    rather than the machine's real /media.
    """
    for root in roots if roots is not None else mount_roots():
        candidate = Path(root) / label
        if candidate.is_dir():
            return candidate
    return None


def find_board_mount(kind: str) -> Path | None:
    """`kind` is "bootloader" (RPI-RP2 / RP2350) or "firmware" (CIRCUITPY)."""
    labels = BOOTLOADER_LABELS if kind == "bootloader" else (FIRMWARE_LABEL,)
    for label in labels:
        found = find_mount(label)
        if found:
            return found
    return None


def firmware_dir() -> Path:
    """`scorpio-firmware/`, next to this script's parent — wherever it was copied to."""
    return Path(__file__).resolve().parent.parent / "scorpio-firmware"


def firmware_files(directory: Path) -> dict[str, Path]:
    """The files that go on the board, and where they live off it."""
    return {
        name: directory / name
        for name in ("boot.py", "code.py")
    }


def missing_firmware(directory: Path) -> list[str]:
    return [name for name, path in firmware_files(directory).items() if not path.is_file()]


def serial_ports(dev_root: Path | None = None) -> dict[str, Path]:
    """The board's serial devices, by role.

    The board exposes **two** channels once `boot.py` has run on a real reset: `-if00` is
    CircuitPython's console/REPL, `-if02` is the JSON protocol the Pi's service talks to.
    Only a board with the firmware running has the second one, which makes it the honest
    "is it running?" signal — and why `SCORPIO_SERIAL_PORT` should point at it (a bare
    `/dev/ttyACM0` is ambiguous when both channels enumerable as ttyACM devices).
    """
    dev_root = dev_root or Path("/dev")
    by_id = dev_root / "serial" / "by-id"
    ports = {"console": None, "data": None, "ttyacm": []}
    if by_id.is_dir():
        for entry in sorted(by_id.iterdir()):
            text = str(entry)
            if "Scorpio" not in text and "scorpio" not in text:
                continue
            if entry.name.endswith("-if02"):
                ports["data"] = entry
            elif entry.name.endswith("-if00"):
                ports["console"] = entry
    tty_dir = dev_root
    if tty_dir.is_dir():
        ports["ttyacm"] = sorted(p for p in tty_dir.glob("ttyACM*"))
    return ports


def missing_libraries(mount: Path, needed=REQUIRED_LIBRARIES) -> list[str]:
    """Libraries the board's `lib/` does not have yet.

    Checks for the `.mpy` or the plain `.py` form — a hand-copied source library works too,
    and reporting it as missing when it is present would send someone down a false trail.
    """
    lib = mount / "lib"
    missing = []
    for name in needed:
        candidates = [lib / f"{name}.mpy", lib / f"{name}.py", lib / name]
        if not any(c.exists() for c in candidates):
            missing.append(name)
    return missing


def decide_route(bootloader: Path | None, firmware: Path | None, force: str | None = None) -> str:
    """Which of the two jobs this run is: "circuitpython", "firmware", or "nothing"."""
    if force in ("circuitpython", "firmware"):
        return force
    if bootloader:
        return "circuitpython"
    if firmware:
        return "firmware"
    return "nothing"


def says_how_to_get_a_uf2(uf2: Path | None) -> str:
    if uf2:
        return f"using the CircuitPython image at {uf2}"
    return (
        "no .uf2 found — download the board's image from\n"
        f"    {BOARD_PAGE}\n"
        "  and pass it in as --uf2 /path/to/adafruit-circuitpython-...-scorpio-....uf2\n"
        "  (or drop it in scorpio-firmware/ and re-run)"
    )


def find_uf2(explicit: str | None, directory: Path) -> Path | None:
    """An explicitly given image, or any .uf2 sitting in scorpio-firmware/."""
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    found = sorted(directory.glob("*.uf2")) if directory.is_dir() else []
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Talking to the world: prompts, copying, and the local service
# ---------------------------------------------------------------------------


def say(text: str = "") -> None:
    print(text, flush=True)


def heading(step: int, total: int, text: str) -> None:
    say()
    say(f"── {step}/{total} {text} " + "─" * max(0, 60 - len(text)))


def ask(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        say(f"{prompt} [assumed yes]")
        return True
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def press_enter(prompt: str, assume_yes: bool) -> None:
    if assume_yes:
        say(f"{prompt} [continuing]")
        return
    try:
        input(f"{prompt} — press Enter when done ")
    except EOFError:
        pass


def copy_onto_board(paths: dict[str, Path], target: Path) -> list[str]:
    """Copy files onto a mounted board. Returns any failures, as printable lines."""
    failures = []
    for name, source in paths.items():
        try:
            shutil.copy(source, target / name)
            say(f"   copied {name}")
        except OSError as exc:
            failures.append(f"couldn't copy {name}: {exc}")
    try:
        os.sync()
    except OSError:
        pass
    return failures


def wait_for_mount(kind: str, seconds: int, assume_yes: bool, label: str) -> Path | None:
    """Poll for a mount, telling the user what to do while we wait."""
    deadline = time.time() + seconds
    reported = False
    while time.time() < deadline:
        found = find_board_mount(kind)
        if found:
            return found
        if not reported:
            say(f"   waiting for {label} to appear …")
            if not assume_yes:
                say("   (nothing will happen until it does — Ctrl-C to stop)")
            reported = True
        time.sleep(1)
    return None


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """`/etc/led-controller/env`, as a dict. Empty when unreadable.

    Unreadable is normal rather than exceptional: the file holds the service's API key and
    is often root-only. The caller says what it could not do rather than failing the run.
    """
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return {}
    return values


def http(url: str, data: bytes | None = None, headers=None, timeout: int = 10):
    """One small HTTP call. Returns (status, body_text) or (None, error_message)."""
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # connection refused, DNS, timeout, TLS — all "couldn't ask"
        return None, str(exc)


# ---------------------------------------------------------------------------
# The guided run
# ---------------------------------------------------------------------------

TOTAL_STEPS = 5


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Flash/update the Feather RP2040 Scorpio that drives the LED strips.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Run with no arguments for the guided version. The board must be plugged into\n"
            "this Pi over USB; the script cannot reach it any other way.\n"
        ),
    )
    parser.add_argument("--route", choices=["circuitpython", "firmware"], default=None,
                        help="force a job instead of working it out from what's mounted")
    parser.add_argument("--uf2", default=None, help="CircuitPython .uf2 for this board")
    parser.add_argument("--libs-from", default=None,
                        help="directory holding the extracted Adafruit bundle's lib/ (fresh boards)")
    parser.add_argument("--yes", action="store_true", help="don't ask; assume the physical steps are done")
    parser.add_argument("--check", action="store_true", help="only verify the current state, change nothing")
    parser.add_argument("--timeout", type=int, default=60, help="seconds to wait for a mount (default 60)")
    args = parser.parse_args(argv)

    firmware = firmware_dir()
    say("LED controller — Scorpio firmware")
    say("=" * 34)
    if not firmware.is_dir():
        say(f"Can't find the firmware to install: {firmware}")
        say("Run this from the led-controller checkout (see led-controller/README.md).")
        return 1
    missing = missing_firmware(firmware)
    if missing:
        say(f"Firmware incomplete — missing {', '.join(missing)} in {firmware}")
        return 1
    say(f"Firmware to install: {', '.join(sorted(firmware_files(firmware)))} from {firmware}")

    bootloader = find_board_mount("bootloader")
    circuitpy = find_board_mount("firmware")
    route = decide_route(bootloader, circuitpy, args.route)

    if args.check:
        return verify(args)

    # --- 1: work out which job this is ------------------------------------
    heading(1, TOTAL_STEPS, "What kind of job this is")
    if route == "nothing":
        say("I can't see the board.")
        say()
        say("Plug it into *this Pi* with a USB data cable (a charge-only cable will power it")
        say("and never show up), then either:")
        say()
        say("  • the board has never run CircuitPython → put it in flashing mode:")
        say("      hold the BOOTSEL button, plug the USB cable in, let go.")
        say("      It should appear as a USB drive called RPI-RP2.")
        say("  • the board already runs CircuitPython → you should see a drive called CIRCUITPY.")
        say()
        press_enter("Do that", args.yes)
        bootloader = wait_for_mount("bootloader", args.timeout, args.yes, "RPI-RP2") if not circuitpy else None
        circuitpy = find_board_mount("firmware")
        route = decide_route(bootloader, circuitpy, args.route)
        if route == "nothing":
            say()
            say("Still nothing. Check `lsusb` and `dmesg | tail` — a board in flashing mode")
            say("shows up as a storage device, and a board running CircuitPython as both a")
            say("storage device and two serial devices.")
            return 1

    if route == "firmware":
        if circuitpy is None:
            # Happens when the route was forced (--route firmware) without a board mounted.
            # Better to wait and say so than to fall over on a None a few steps later.
            circuitpy = wait_for_mount("firmware", args.timeout, args.yes, "CIRCUITPY")
            if circuitpy is None:
                say("Asked for a firmware-only update, but no CIRCUITPY drive is mounted.")
                say("Plug the board in (it needs to already be running CircuitPython) and re-run.")
                return 1
        say("Found a board already running CircuitPython (CIRCUITPY).")
        say("This run updates the firmware files only — no BOOTSEL, no UF2, no libraries.")
    else:
        assert bootloader is not None
        say(f"Found a board in its bootloader, mounted at {bootloader}.")
        say("This run installs CircuitPython itself, then the libraries, then the firmware.")

    # --- 2: CircuitPython itself (fresh boards only) -----------------------
    boot_mount = bootloader
    if route == "circuitpython":
        heading(2, TOTAL_STEPS, "Installing CircuitPython")
        uf2 = find_uf2(args.uf2, firmware)
        if not uf2:
            say(says_how_to_get_a_uf2(None))
            return 1
        say(f"Copying {uf2.name} onto {bootloader} …")
        try:
            shutil.copy(uf2, bootloader / uf2.name)
            os.sync()
        except OSError as exc:
            say(f"Couldn't copy the image: {exc}")
            return 1
        say("Copied. The board is rebooting and installing it.")
        circuitpy = wait_for_mount("firmware", args.timeout, args.yes, "CIRCUITPY")
        if not circuitpy:
            say()
            say("CIRCUITPY never appeared. Most often that means the .uf2 was not the right")
            say("one for this board (it must be the Feather RP2040 **Scorpio** image), or the")
            say("board needs unplugging and replugging once.")
            return 1
        say(f"CircuitPython is running — the board is mounted at {circuitpy}.")
    else:
        heading(2, TOTAL_STEPS, "Installing CircuitPython")
        say("Skipped — this board already has it.")

    # --- 3: libraries ------------------------------------------------------
    heading(3, TOTAL_STEPS, "Libraries the firmware imports")
    assert circuitpy is not None
    missing_libs = missing_libraries(circuitpy)
    if not missing_libs:
        say(f"All present ({', '.join(REQUIRED_LIBRARIES)}).")
    elif args.libs_from:
        source_lib = Path(args.libs_from).expanduser()
        target_lib = circuitpy / "lib"
        target_lib.mkdir(exist_ok=True)
        copies = {name: source_lib / name for name in missing_libs if (source_lib / name).exists()}
        failures = copy_onto_board(copies, target_lib)
        for line in failures:
            say(f"   {line}")
        still = missing_libraries(circuitpy)
        if still:
            say(f"Still missing: {', '.join(still)} — is --libs-from pointing at the bundle's lib/ directory?")
            return 1
    else:
        say(f"Missing: {', '.join(missing_libs)}")
        say()
        say("Two ways to get them, both official:")
        say("  • circup (handles dependencies for you):")
        say("      pip install circup && circup install " + " ".join(missing_libs))
        say("  • or download the bundle zip, unzip it, and re-run with:")
        say(f"      {BUNDLE_PAGE}")
        say("      --libs-from /path/to/adafruit-circuitpython-bundle-*/lib")
        say()
        say("Then run this script again — it skips what is already there.")
        return 1

    # --- 4: the firmware files --------------------------------------------
    heading(4, TOTAL_STEPS, "The firmware files")
    assert circuitpy is not None
    failures = copy_onto_board(firmware_files(firmware), circuitpy)
    for line in failures:
        say(f"   {line}")
    if failures:
        return 1
    say("CircuitPython re-runs code.py on save, so this takes effect now.")

    # --- 5: does it actually work? ----------------------------------------
    heading(5, TOTAL_STEPS, "Checking it works")
    return verify(args, just_copied=True)


def verify(args, just_copied: bool = False) -> int:
    """Report honestly: board present, data channel there, service talking to it."""
    problems = []

    circuitpy = find_board_mount("firmware")
    ports = serial_ports()
    say()
    say(f"board mounted as CIRCUITPY: {'yes' if circuitpy else 'no'}")
    say(f"serial console channel:     {ports['console'] or 'not found'}")
    say(f"serial data channel:        {ports['data'] or 'not found'}")

    if not ports["data"]:
        problems.append(
            "the second serial channel (the '-if02' one the service talks to) is missing.\n"
            "     If you just flashed, that is expected until a **true hardware reset**:\n"
            "     press the board's reset button (or run microcontroller.reset() in its\n"
            "     REPL). Ctrl-D is not enough — it does not re-enumerate USB."
        )

    env = read_env_file()
    if env:
        configured = env.get("SCORPIO_SERIAL_PORT", "")
        say(f"service is configured to use: {configured or 'nothing (SCORPIO_SERIAL_PORT unset)'}")
        if configured and not Path(configured).exists():
            problems.append(
                f"SCORPIO_SERIAL_PORT in {ENV_FILE} points at {configured}, which does not exist.\n"
                "     Point it at the '-if02' path above, then: sudo systemctl restart led-controller"
            )
        elif configured and ports["data"] and Path(configured).name.endswith("-if00"):
            problems.append(
                f"SCORPIO_SERIAL_PORT is set to the *console* channel ({configured}).\n"
                "     The service needs the data channel ('-if02'), or commands go to the REPL."
            )
    else:
        say(f"couldn't read {ENV_FILE} (root-only? not set up yet?) — skipping the config check")

    status, body = http(f"{BRIDGE_URL}/health")
    if status is None:
        problems.append(f"the LED service on this Pi didn't answer at {BRIDGE_URL} ({body}).\n"
                        "     Is it running? sudo systemctl status led-controller")
    else:
        say(f"service /health: HTTP {status} {body.strip()[:120]}")
        if status != 200:
            problems.append("the LED service answered but not with 200 — see its logs")

    key = env.get("LED_CONTROLLER_KEY", "")
    if status == 200 and key:
        say("asking the service to run the demo (the strips should light up and stay on) …")
        status, body = http(
            f"{BRIDGE_URL}/demo",
            data=b'{"on": true}',
            headers={"Content-Type": "application/json", "X-Api-Key": key},
        )
        if status == 200:
            say(f"board answered: {body.strip()[:160]}")
            say()
            say("   >>> Look at the strips. A rainbow chase means the firmware is running")
            say("   >>> and driving them. Turn it off again from Settings -> Lights.")
        elif status == 502:
            problems.append("the service could not reach the board: " + body.strip()[:200] +
                            "\n     Board not flashed, not plugged in, or the serial path is wrong.")
        else:
            problems.append(f"the demo request came back HTTP {status}: {body.strip()[:160]}")
    elif status == 200:
        say("(no API key readable, so no light test — use Settings -> Lights in the app for that)")

    say()
    if problems:
        say("NOT FINISHED — things to sort out:")
        for problem in problems:
            say(f"  • {problem}")
        return 1
    say("ALL GOOD: the board is talking to the Pi's LED service.")
    if just_copied:
        say("Then in the app: Settings -> Flash the LED controller, and press Check.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say("Stopped. Nothing is half-written: files are copied whole, and the board is a USB drive.")
        sys.exit(130)
