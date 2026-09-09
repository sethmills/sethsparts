"""Seth's Parts LED "find the part" firmware for the Feather RP2040 Scorpio.

Listens on the USB "data" serial channel (see boot.py) for newline-delimited JSON
commands from the Pi's led-controller service and drives the matching NeoPXL8
channel/index range.

Three independent modes, mutually exclusive (starting one cancels the others):
- "locate" animations, one per channel: breathe for a few seconds, then (if a
  bin row 1-4 was given) flash that many times, then repeat, for a total
  duration -- auto-clears when it expires.
- "room_light": fills every channel solid, stays on until explicitly turned off
  (no auto-clear) -- for using the cabinets as ambient room lighting.
- "demo": a rainbow chase across every channel for a given duration, purely for
  fun/show-off value, then auto-clears.

A persistent global brightness (0-1) and default color apply whenever a command
doesn't specify its own color.

STRAND_LENGTH is a placeholder max-pixels-per-channel -- raise or lower it once
the real per-cabinet strip lengths are known (it just needs to be >= the longest
strip actually wired to any one channel).
"""
import json
import math
import time

import board
import usb_cdc
from adafruit_neopxl8 import NeoPxl8

NUM_STRANDS = 8
STRAND_LENGTH = 100

# Locate animation timing (seconds).
BREATHE_DURATION = 3.6  # one breathe pulse
BREATHE_CYCLES = 3  # how many pulses before flashing the bin row
BREATHE_SEGMENT = BREATHE_DURATION * BREATHE_CYCLES
FLASH_ON = 0.18
FLASH_OFF = 0.15
PAUSE = 0.4
DEFAULT_LOCATE_DURATION_MS = 30000

# Demo mode timing.
DEFAULT_DEMO_DURATION_MS = 15000
DEMO_SPEED = 1.4  # chase speed, in "channels per second"

pixels = NeoPxl8(
    board.NEOPIXEL0, NUM_STRANDS * STRAND_LENGTH, num_strands=NUM_STRANDS, auto_write=False
)
pixels.fill(0)
pixels.show()

serial = usb_cdc.data

# Global, persistent settings (survive across commands until changed or reset).
brightness = 1.0
default_color = (255, 255, 255)

# Mode state -- exactly one of these is "active" at a time.
locate_animations = {}  # channel -> dict, see start_locate()
room_light = None  # None, or {"color": (r,g,b)}
demo = None  # None, or {"start": t, "end": t}

buf = b""


def _rgb_int(color, scale=1.0):
    r, g, b = color
    r = max(0, min(255, int(r * scale)))
    g = max(0, min(255, int(g * scale)))
    b = max(0, min(255, int(b * scale)))
    return (r << 16) | (g << 8) | b


def clear_channel(channel):
    base = channel * STRAND_LENGTH
    for i in range(STRAND_LENGTH):
        pixels[base + i] = 0


def clear_all():
    pixels.fill(0)


def stop_all_modes():
    global room_light, demo
    locate_animations.clear()
    room_light = None
    demo = None
    clear_all()
    pixels.show()


def start_locate(channel, start, count, color, row, duration_ms):
    locate_animations[channel] = {
        "base": channel * STRAND_LENGTH,
        "start": start,
        "count": count,
        "color": color,
        "row": row,  # None, or 1-4
        "cycle_start": time.monotonic(),
        "end": time.monotonic() + duration_ms / 1000,
    }


def pattern_length(anim):
    if anim["row"]:
        return BREATHE_SEGMENT + anim["row"] * (FLASH_ON + FLASH_OFF) + PAUSE
    return BREATHE_SEGMENT + PAUSE


def render_locate(anim, now):
    elapsed = (now - anim["cycle_start"]) % pattern_length(anim)
    base, start, count, color = anim["base"], anim["start"], anim["count"], anim["color"]

    if elapsed < BREATHE_SEGMENT:
        # Smooth 0->1->0 breathe, repeated BREATHE_CYCLES times before flashing.
        phase = elapsed % BREATHE_DURATION
        level = (1 - math.cos(2 * math.pi * phase / BREATHE_DURATION)) / 2
        rgb = _rgb_int(color, level * brightness)
        for i in range(count):
            pixels[base + start + i] = rgb
        return

    t = elapsed - BREATHE_SEGMENT
    if anim["row"]:
        flash_cycle = FLASH_ON + FLASH_OFF
        if t < anim["row"] * flash_cycle:
            on = (t % flash_cycle) < FLASH_ON
            rgb = _rgb_int(color, brightness) if on else 0
            for i in range(count):
                pixels[base + start + i] = rgb
            return

    # Pause segment (all off) between cycles.
    for i in range(count):
        pixels[base + start + i] = 0


def render_demo(now):
    t = now - demo["start"]
    for ch in range(NUM_STRANDS):
        base = ch * STRAND_LENGTH
        offset = ch * 0.6
        for i in range(STRAND_LENGTH):
            hue = (t * DEMO_SPEED * 40 + i * 6 + offset * 60) % 360
            rgb = _hsv_to_rgb_int(hue, 1.0, brightness)
            pixels[base + i] = rgb


def _hsv_to_rgb_int(h, s, v):
    h = h / 60.0
    i = int(h) % 6
    f = h - int(h)
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    r, g, b = [
        (v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q),
    ][i]
    return (int(r * 255) << 16) | (int(g * 255) << 8) | int(b * 255)


def handle(msg):
    global room_light, demo, brightness, default_color

    cmd = msg.get("cmd")

    if cmd == "ping":
        return {"ok": True, "pong": True}

    if cmd == "set_defaults":
        if "brightness" in msg:
            b = msg["brightness"]
            if not isinstance(b, (int, float)) or not (0 <= b <= 1):
                return {"ok": False, "error": "brightness must be 0-1"}
            brightness = float(b)
        if "color" in msg:
            c = msg["color"]
            if not (isinstance(c, list) and len(c) == 3):
                return {"ok": False, "error": "color must be [r,g,b]"}
            default_color = tuple(c)
        return {"ok": True, "brightness": brightness, "color": list(default_color)}

    if cmd == "clear":
        channel = msg.get("channel")
        if channel == "all":
            stop_all_modes()
            return {"ok": True}
        if not isinstance(channel, int) or not (0 <= channel < NUM_STRANDS):
            return {"ok": False, "error": "bad channel"}
        clear_channel(channel)
        pixels.show()
        locate_animations.pop(channel, None)
        return {"ok": True}

    if cmd == "locate":
        channel = msg.get("channel")
        start = msg.get("start", 0)
        count = msg.get("count", 1)
        color = tuple(msg.get("color", default_color))
        duration_ms = msg.get("duration_ms", DEFAULT_LOCATE_DURATION_MS)
        row = msg.get("row")

        if not isinstance(channel, int) or not (0 <= channel < NUM_STRANDS):
            return {"ok": False, "error": "bad channel"}
        if not isinstance(start, int) or not isinstance(count, int) or start < 0 or count < 1:
            return {"ok": False, "error": "bad start/count"}
        if start + count > STRAND_LENGTH:
            return {"ok": False, "error": "start/count exceeds STRAND_LENGTH -- raise it in code.py"}
        if row is not None and (not isinstance(row, int) or not (1 <= row <= 4)):
            return {"ok": False, "error": "row must be 1-4"}

        # Locate is exclusive with room_light/demo, but multiple channels can
        # locate at once (e.g. a drawer's left+right segments).
        room_light = None
        demo = None
        start_locate(channel, start, count, color, row, duration_ms)
        return {"ok": True}

    if cmd == "room_light":
        on = msg.get("on", True)
        locate_animations.clear()
        demo = None
        if on:
            color = tuple(msg.get("color", default_color))
            room_light = {"color": color}
            for ch in range(NUM_STRANDS):
                base = ch * STRAND_LENGTH
                rgb = _rgb_int(color, brightness)
                for i in range(STRAND_LENGTH):
                    pixels[base + i] = rgb
            pixels.show()
        else:
            room_light = None
            clear_all()
            pixels.show()
        return {"ok": True}

    if cmd == "demo":
        duration_ms = msg.get("duration_ms", DEFAULT_DEMO_DURATION_MS)
        locate_animations.clear()
        room_light = None
        demo = {"start": time.monotonic(), "end": time.monotonic() + duration_ms / 1000}
        return {"ok": True}

    return {"ok": False, "error": "unknown cmd"}


while True:
    n = serial.in_waiting
    if n:
        buf += serial.read(n)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                reply = handle(msg)
            except ValueError:
                reply = {"ok": False, "error": "bad json"}
            serial.write((json.dumps(reply) + "\n").encode("utf-8"))

    now = time.monotonic()
    dirty = False

    if demo is not None:
        if now >= demo["end"]:
            clear_all()
            demo = None
        else:
            render_demo(now)
        dirty = True

    expired = [ch for ch, anim in locate_animations.items() if now >= anim["end"]]
    for ch in expired:
        clear_channel(ch)
        del locate_animations[ch]
        dirty = True
    for anim in locate_animations.values():
        render_locate(anim, now)
        dirty = True

    if dirty:
        pixels.show()

    time.sleep(0.02)
