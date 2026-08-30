#!/usr/bin/env python3
"""Toggles squeekboard (the on-screen keyboard) via its DBus interface.

Squeekboard already runs on this Pi (started by its own XDG autostart entry) and
exposes sm.puri.OSK0.SetVisible/.Visible on the session bus -- normally toggled from
a taskbar button, which kiosk Chromium hides. This just gives Seth's Parts' own
"Keyboard" button (visible only on touch devices) something local to call instead.

Runs as a systemd --user unit (needs the graphical session's DBus bus), listening
on 127.0.0.1 only -- the page calls it directly since it and the kiosk browser
share the same machine.
"""
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT = 9091
BUS_ARGS = ["busctl", "--user"]
DEST, PATH, IFACE = "sm.puri.OSK0", "/sm/puri/OSK0", "sm.puri.OSK0"


def _get_visible():
    out = subprocess.run(
        [*BUS_ARGS, "get-property", DEST, PATH, IFACE, "Visible"],
        capture_output=True, text=True, timeout=3, check=True,
    )
    return "true" in out.stdout


def _set_visible(value):
    subprocess.run(
        [*BUS_ARGS, "call", DEST, PATH, IFACE, "SetVisible", "b", "true" if value else "false"],
        capture_output=True, text=True, timeout=3, check=True,
    )


class Handler(BaseHTTPRequestHandler):
    def _respond(self, status, body=b""):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        if self.path != "/toggle":
            self._respond(404)
            return
        try:
            new_state = not _get_visible()
            _set_visible(new_state)
            self._respond(200, str(new_state).lower().encode())
        except (subprocess.SubprocessError, OSError):
            self._respond(502)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    print(f"Keyboard toggle listening on 127.0.0.1:{LISTEN_PORT}", flush=True)
    server.serve_forever()
