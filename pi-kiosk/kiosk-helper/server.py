#!/usr/bin/env python3
"""Local helper for the Pi kiosk -- small OS-level actions the page's own
touch-only buttons can't do from inside the browser sandbox.

Runs as a systemd --user unit, listening on 127.0.0.1 only -- the page
calls it directly since it and the kiosk browser share the same machine.

Routes:
  GET  /health         -- 200 if this service is reachable. The page's own JS
                          uses this at load time to detect "am I actually
                          running on the Pi kiosk" (this service only ever
                          runs there) and reveal Pi-only buttons accordingly
                          -- independent of screen size/touch capability, so
                          it keeps working correctly across display swaps and
                          never shows those buttons on someone's phone.
  POST /toggle-keyboard -- toggle the on-screen keyboard (squeekboard) on/off.
                          Opt-in from the app's Settings; the page only shows the
                          button when the owner has turned it on. Caveat: on some
                          Pi compositors squeekboard's overlay will not render above
                          a fullscreen Chromium surface -- if the button appears to
                          do nothing, that z-ordering quirk (not this service) is why.
"""
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT = 9091


def _kill_chromium_soon():
    # Small delay so the HTTP response below actually reaches the browser
    # before the process serving the page disappears.
    time.sleep(0.3)
    subprocess.run(["pkill", "-f", "chromium"], capture_output=True)


def _toggle_keyboard():
    # squeekboard is the on-screen keyboard on Raspberry Pi OS (Wayland). Toggle it:
    # start it if it isn't running, stop it if it is.
    running = subprocess.run(["pgrep", "-f", "squeekboard"], capture_output=True).returncode == 0
    if running:
        subprocess.run(["pkill", "-f", "squeekboard"], capture_output=True)
    else:
        subprocess.Popen(["squeekboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
        if self.path == "/exit-browser":
            self._respond(200)
            threading.Thread(target=_kill_chromium_soon, daemon=True).start()
            return

        if self.path == "/toggle-keyboard":
            self._respond(200)
            threading.Thread(target=_toggle_keyboard, daemon=True).start()
            return

        self._respond(404)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    print(f"Kiosk helper listening on 127.0.0.1:{LISTEN_PORT}", flush=True)
    server.serve_forever()
