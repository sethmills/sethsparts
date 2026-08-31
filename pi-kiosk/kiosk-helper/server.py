#!/usr/bin/env python3
"""Local helper for the Pi kiosk -- small OS-level actions the page's own
touch-only buttons can't do from inside the browser sandbox.

Runs as a systemd --user unit (the keyboard toggle needs the graphical
session's DBus bus), listening on 127.0.0.1 only -- the page calls it
directly since it and the kiosk browser share the same machine.

Routes:
  GET  /health         -- 200 if this service is reachable. The page's own JS
                          uses this at load time to detect "am I actually
                          running on the Pi kiosk" (this service only ever
                          runs there) and reveal Pi-only buttons accordingly
                          -- independent of screen size/touch capability, so
                          it keeps working correctly across display swaps and
                          never shows those buttons on someone's phone.
  POST /toggle          -- show/hide squeekboard (already running on this Pi,
                          normally toggled from the taskbar, which kiosk mode
                          hides) via its sm.puri.OSK0.SetVisible DBus method.
  POST /exit-browser   -- kill kiosk Chromium, revealing the desktop
                          underneath (pcmanfm-pi/wf-panel-pi keep running
                          regardless -- only the kiosk browser is fullscreen
                          over them). A desktop shortcut relaunches it
                          (see ../sethsparts-kiosk.desktop).
"""
import subprocess
import threading
import time
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


def _kill_chromium_soon():
    # Small delay so the HTTP response below actually reaches the browser
    # before the process serving the page disappears.
    time.sleep(0.3)
    subprocess.run(["pkill", "-f", "chromium"], capture_output=True)


class Handler(BaseHTTPRequestHandler):
    def _respond(self, status, body=b""):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        # The page (https://sethsparts.com) fetches this cross-origin to detect
        # "am I on the Pi" -- needs to actually read the response, not just
        # trigger the request, so a plain no-cors fetch won't do.
        self.send_header("Access-Control-Allow-Origin", "https://sethsparts.com")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, b"ok")
            return
        self._respond(404)

    def do_POST(self):
        if self.path == "/toggle":
            try:
                new_state = not _get_visible()
                _set_visible(new_state)
                self._respond(200, str(new_state).lower().encode())
            except (subprocess.SubprocessError, OSError):
                self._respond(502)
            return

        if self.path == "/exit-browser":
            self._respond(200)
            threading.Thread(target=_kill_chromium_soon, daemon=True).start()
            return

        self._respond(404)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    print(f"Kiosk helper listening on 127.0.0.1:{LISTEN_PORT}", flush=True)
    server.serve_forever()
