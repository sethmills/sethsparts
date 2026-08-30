"""Seth's Parts LED "find the part" firmware for the Feather RP2040 Scorpio.

Listens on the USB "data" serial channel (see boot.py) for newline-delimited JSON
commands from the Pi's led-controller service and drives the matching NeoPXL8
channel/index range. Auto-clears a locate after its duration expires so nothing
is ever left lit forever.

STRAND_LENGTH is a placeholder max-pixels-per-channel -- raise or lower it once
the real per-cabinet strip lengths are known (it just needs to be >= the longest
strip actually wired to any one channel).
"""
import json
import time

import board
import usb_cdc
from adafruit_neopxl8 import NeoPxl8

NUM_STRANDS = 8
STRAND_LENGTH = 100

pixels = NeoPxl8(
    board.NEOPIXEL0, NUM_STRANDS * STRAND_LENGTH, num_strands=NUM_STRANDS, auto_write=False
)
pixels.fill(0)
pixels.show()

serial = usb_cdc.data

active_until = {}  # channel -> time.monotonic() deadline
buf = b""


def clear_channel(channel):
    base = channel * STRAND_LENGTH
    for i in range(STRAND_LENGTH):
        pixels[base + i] = 0
    pixels.show()


def handle(msg):
    cmd = msg.get("cmd")

    if cmd == "ping":
        return {"ok": True, "pong": True}

    if cmd == "clear":
        channel = msg.get("channel")
        if not isinstance(channel, int) or not (0 <= channel < NUM_STRANDS):
            return {"ok": False, "error": "bad channel"}
        clear_channel(channel)
        active_until.pop(channel, None)
        return {"ok": True}

    if cmd == "locate":
        channel = msg.get("channel")
        start = msg.get("start", 0)
        count = msg.get("count", 1)
        color = msg.get("color", [255, 255, 255])
        duration_ms = msg.get("duration_ms", 12000)

        if not isinstance(channel, int) or not (0 <= channel < NUM_STRANDS):
            return {"ok": False, "error": "bad channel"}
        if not isinstance(start, int) or not isinstance(count, int) or start < 0 or count < 1:
            return {"ok": False, "error": "bad start/count"}
        if start + count > STRAND_LENGTH:
            return {"ok": False, "error": "start/count exceeds STRAND_LENGTH -- raise it in code.py"}

        base = channel * STRAND_LENGTH
        rgb = (color[0] << 16) | (color[1] << 8) | color[2]
        for i in range(count):
            pixels[base + start + i] = rgb
        pixels.show()
        active_until[channel] = time.monotonic() + duration_ms / 1000
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
    expired = [ch for ch, deadline in active_until.items() if now >= deadline]
    for ch in expired:
        clear_channel(ch)
        del active_until[ch]

    time.sleep(0.02)
