#!/usr/bin/env python3
"""Print-bridge for the Zebra GK420T, connected via USB to this Pi.

Receives POST /print (raw ZPL bytes in the request body) from the Django app (via
a Cloudflare Tunnel) and writes them straight through to the printer's raw USB
device node -- no CUPS, no rasterization here. All label layout/rendering
(fonts, bold/italic, barcodes) happens on the Django side (inventory/label_printing.py)
and arrives here as a complete, ready-to-print ZPL document.

PRINTER_DEVICE starts empty on purpose -- until it's confirmed present, /print
returns a clear "not connected" error instead of guessing a device path that may
not exist (the GK420T's device node is only created while it's actually plugged in
and powered on: /dev/usb/lp0, confirmed via dmesg when connected).
"""
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRINTER_DEVICE = os.environ.get("PRINTER_DEVICE", "/dev/usb/lp0")
API_KEY = os.environ.get("LABEL_PRINTER_KEY", "")
LISTEN_PORT = int(os.environ.get("LABEL_PRINTER_PORT", "9020"))

_device_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _respond(self, status, body=b""):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            connected = os.path.exists(PRINTER_DEVICE)
            self._respond(200 if connected else 503, f'{{"ok": {str(connected).lower()}, "device": "{PRINTER_DEVICE}"}}')
            return
        self._respond(404)

    def do_POST(self):
        if not API_KEY or self.headers.get("X-Api-Key") != API_KEY:
            self._respond(403, "unauthorized")
            return
        if self.path != "/print":
            self._respond(404)
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        zpl_bytes = self.rfile.read(length)

        if not os.path.exists(PRINTER_DEVICE):
            self._respond(503, f"printer not connected (no {PRINTER_DEVICE} -- check the USB cable/power)")
            return

        try:
            with _device_lock:
                with open(PRINTER_DEVICE, "wb") as f:
                    f.write(zpl_bytes)
        except OSError as exc:
            self._respond(502, f"couldn't write to printer: {exc}")
            return

        self._respond(200, '{"ok": true}')

    def log_message(self, format, *args):
        pass


class ThreadingHTTPServerV6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


if __name__ == "__main__":
    v4 = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    v6 = ThreadingHTTPServerV6(("::1", LISTEN_PORT), Handler)
    threading.Thread(target=v6.serve_forever, daemon=True).start()
    print(f"Label printer bridge listening on 127.0.0.1:{LISTEN_PORT} and [::1]:{LISTEN_PORT}, device={PRINTER_DEVICE}", flush=True)
    v4.serve_forever()
