#!/usr/bin/env python3
"""LED "find the part" controller for Seth's Parts.

Receives POST /locate from the Django app (via the led.sethsparts.com Cloudflare
Tunnel) and relays it to the Feather RP2040 Scorpio over USB serial, which drives
the actual WS2812B strip.

strip_map.json maps logical strip names (matching Drawer.led_strip in Seth's Parts)
to physical Scorpio channel numbers (0-7). Until an entry exists for a given strip
name, /locate returns a clear "not mapped yet" error instead of guessing.

That mapping can be written two ways: by editing strip_map.json by hand, or by
POSTing to /strips, which is what the app's setup wizard does. Only you can see
which strip is wired to which channel, so the app asks and then pushes the answer
here rather than trying to work it out.
"""
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import serial
except ImportError:  # pragma: no cover - pyserial is only needed to actually drive LEDs
    # Imported lazily so the strip-map logic can be read, tested and corrected on a
    # machine with no serial port and no pyserial — which is every machine except
    # the Pi, and the place where the logic is most likely to be worked on.
    serial = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STRIP_MAP_PATH = os.path.join(BASE_DIR, "strip_map.json")

SERIAL_PORT = os.environ.get("SCORPIO_SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = int(os.environ.get("SCORPIO_SERIAL_BAUD", "115200"))
API_KEY = os.environ.get("LED_CONTROLLER_KEY", "")
LISTEN_PORT = int(os.environ.get("LED_CONTROLLER_PORT", "9000"))
DEFAULT_COLOR = [255, 255, 255]
DEFAULT_LOCATE_DURATION_MS = 30000

_serial_lock = threading.Lock()
_serial_conn = None


def _load_strip_map():
    try:
        with open(STRIP_MAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


MAX_CHANNEL = 7


def _write_strip_map(mapping):
    """Replace strip_map.json atomically.

    Written to a temporary file and moved into place, because the alternative is a
    window where the file is half-written and /locate reads garbage. Small window,
    but the failure it causes — a drawer lighting up wrongly, or an error that makes
    no sense a week later — is not worth the few lines saved.
    """
    tmp = STRIP_MAP_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, STRIP_MAP_PATH)


def validate_strip_map(mapping):
    """Check a proposed mapping. Returns (cleaned, error).

    Validated here rather than trusting the caller, because a channel number outside
    the Scorpio's range would either be ignored silently or light up something
    unintended, and neither shows up until somebody presses the button.
    """
    if not isinstance(mapping, dict):
        return None, "strips must be an object of name -> channel"
    cleaned = {}
    for name, channel in mapping.items():
        name = str(name).strip()
        if not name:
            return None, "a strip name cannot be empty"
        if isinstance(channel, bool) or not isinstance(channel, int):
            return None, f"channel for '{name}' must be a whole number"
        if not (0 <= channel <= MAX_CHANNEL):
            return None, f"channel for '{name}' must be 0-{MAX_CHANNEL}"
        cleaned[name] = channel
    return cleaned, ""


def _get_serial():
    global _serial_conn
    if serial is None:
        raise RuntimeError("pyserial isn't installed, so the Scorpio can't be reached")
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
        if self.path == "/strips":
            self._json_response(200, {"ok": True, "strips": _load_strip_map()})
            return
        if self.path == "/health":
            strip_map = _load_strip_map()
            self._json_response(200, {"ok": True, "strips_configured": sorted(strip_map)})
            return
        self._json_response(404, {"error": "not found"})

    def _relay(self, command):
        """POST a command to the Scorpio and write the HTTP response. Shared by every
        POST route below."""
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

    def do_POST(self):
        if not API_KEY or self.headers.get("X-Api-Key") != API_KEY:
            self._json_response(403, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid json"})
            return

        if self.path == "/locate":
            self._handle_locate(payload)
        elif self.path == "/room_light":
            self._handle_room_light(payload)
        elif self.path == "/demo":
            self._handle_demo(payload)
        elif self.path == "/set_defaults":
            self._handle_set_defaults(payload)
        elif self.path == "/strips":
            self._handle_strips(payload)
        else:
            self._json_response(404, {"error": "not found"})

    def _handle_locate(self, payload):
        strip_name = payload.get("strip")
        start_index = payload.get("start_index")
        count = payload.get("count", 1)
        row = payload.get("row")  # optional, 1-4 -- which bin-row within the drawer
        col = payload.get("col")  # optional, 1-4 -- which bin-column within the drawer

        if not strip_name or start_index is None:
            self._json_response(400, {"error": "strip and start_index are required"})
            return
        if row is not None and (not isinstance(row, int) or not (1 <= row <= 4)):
            self._json_response(400, {"error": "row must be 1-4"})
            return
        if col is not None and (not isinstance(col, int) or not (1 <= col <= 4)):
            self._json_response(400, {"error": "col must be 1-4"})
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
            "duration_ms": payload.get("duration_ms", DEFAULT_LOCATE_DURATION_MS),
        }
        if "color" in payload:
            command["color"] = payload["color"]
        if row is not None:
            command["row"] = row
        if col is not None:
            command["col"] = col
        self._relay(command)

    def _handle_strips(self, payload):
        """Replace the strip map. Called by the app's setup wizard."""
        cleaned, error = validate_strip_map(payload.get("strips", {}))
        if error:
            self._json_response(400, {"error": error})
            return
        try:
            _write_strip_map(cleaned)
        except OSError as exc:
            self._json_response(500, {"error": f"couldn't save strip_map.json: {exc}"})
            return
        self._json_response(200, {"ok": True, "strips": cleaned})

    def _handle_room_light(self, payload):
        command = {"cmd": "room_light", "on": payload.get("on", True)}
        if "color" in payload:
            command["color"] = payload["color"]
        self._relay(command)

    def _handle_demo(self, payload):
        command = {"cmd": "demo", "on": payload.get("on", True)}
        self._relay(command)

    def _handle_set_defaults(self, payload):
        command = {"cmd": "set_defaults"}
        if "brightness" in payload:
            command["brightness"] = payload["brightness"]
        if "color" in payload:
            command["color"] = payload["color"]
        self._relay(command)

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
