#!/usr/bin/env python3
"""LED "find the part" controller for Seth's Parts.

Receives POST /locate from the Django app (via the led.sethsparts.com Cloudflare
Tunnel) and relays it to the Feather RP2040 Scorpio over USB serial, which drives
the actual WS2812B strip.

strip_map.json maps logical strip names (matching Drawer.led_strip in Seth's Parts)
to physical Scorpio channel numbers (0-7). It starts empty on purpose -- fill it in
once the cabinet-to-strip wiring is actually decided; until an entry exists for a
given strip name, /locate just returns a clear "not mapped yet" error instead of
guessing.
"""
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STRIP_MAP_PATH = os.path.join(BASE_DIR, "strip_map.json")

SERIAL_PORT = os.environ.get("SCORPIO_SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = int(os.environ.get("SCORPIO_SERIAL_BAUD", "115200"))
API_KEY = os.environ.get("LED_CONTROLLER_KEY", "")
LISTEN_PORT = int(os.environ.get("LED_CONTROLLER_PORT", "9000"))
DEFAULT_COLOR = [255, 255, 255]
DEFAULT_DURATION_MS = 12000

_serial_lock = threading.Lock()
_serial_conn = None


def _load_strip_map():
    try:
        with open(STRIP_MAP_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _get_serial():
    global _serial_conn
    if _serial_conn is None or not _serial_conn.is_open:
        _serial_conn = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
    return _serial_conn


def _send_command(payload):
    """Send one JSON line to the Scorpio and read back its single-line reply."""
    global _serial_conn
    line = (json.dumps(payload) + "\n").encode("utf-8")
    with _serial_lock:
        try:
            conn = _get_serial()
            conn.reset_input_buffer()
            conn.write(line)
            conn.flush()
            response = conn.readline().decode("utf-8", errors="replace").strip()
        except Exception:
            # Discard a possibly-stale connection (e.g. the Scorpio was unplugged
            # mid-session -- termios raises its own error type here, not always a
            # serial.SerialException/OSError) so the next request reopens fresh
            # instead of repeatedly hitting the same broken file descriptor.
            _serial_conn = None
            raise
    return response


class Handler(BaseHTTPRequestHandler):
    def _json_response(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            strip_map = _load_strip_map()
            self._json_response(200, {"ok": True, "strips_configured": sorted(strip_map)})
            return
        self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/locate":
            self._json_response(404, {"error": "not found"})
            return

        if not API_KEY or self.headers.get("X-Api-Key") != API_KEY:
            self._json_response(403, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid json"})
            return

        strip_name = payload.get("strip")
        start_index = payload.get("start_index")
        count = payload.get("count", 1)

        if not strip_name or start_index is None:
            self._json_response(400, {"error": "strip and start_index are required"})
            return

        strip_map = _load_strip_map()
        if strip_name not in strip_map:
            self._json_response(
                409,
                {"error": f"'{strip_name}' isn't in strip_map.json yet -- add it once the wiring is known"},
            )
            return

        command = {
            "cmd": "locate",
            "channel": strip_map[strip_name],
            "start": start_index,
            "count": count,
            "color": DEFAULT_COLOR,
            "duration_ms": DEFAULT_DURATION_MS,
        }
        try:
            reply = _send_command(command)
        except Exception as exc:
            # Broad on purpose: this is a narrow hardware I/O boundary (USB serial
            # to the Scorpio) where the failure mode should always just be "couldn't
            # reach it" regardless of the exact underlying exception type -- e.g.
            # termios.error (device unplugged mid-session) isn't reliably a
            # serial.SerialException/OSError subclass across platforms.
            self._json_response(502, {"error": f"couldn't reach the Scorpio: {exc}"})
            return

        self._json_response(200, {"ok": True, "scorpio_reply": reply})

    def log_message(self, format, *args):
        pass  # journald captures the startup print(); per-request logging would just be noise


class ThreadingHTTPServerV6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


if __name__ == "__main__":
    # Bind both loopback families -- cloudflared's ingress target is the hostname
    # "localhost", which it can resolve to ::1 (IPv6) rather than 127.0.0.1, and an
    # IPv4-only bind then looks like "connection refused" to it even though the
    # service is actually up (confirmed: this exact symptom broke the tunnel).
    v4 = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    v6 = ThreadingHTTPServerV6(("::1", LISTEN_PORT), Handler)
    threading.Thread(target=v6.serve_forever, daemon=True).start()
    print(f"LED controller listening on 127.0.0.1:{LISTEN_PORT} and [::1]:{LISTEN_PORT}, serial={SERIAL_PORT}", flush=True)
    v4.serve_forever()
