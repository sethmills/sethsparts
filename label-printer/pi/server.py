#!/usr/bin/env python3
"""Print-bridge: takes finished label bytes from the app and gets them to the printer.

Runs on the Raspberry Pi next to the printer, behind its own Cloudflare Tunnel. The
Django app does all the rendering and encoding -- fonts, barcodes, and the printer's
own command language -- so this bridge stays deliberately dumb. It looks at the
content type and takes one of two routes:

* **Raw** (ZPL, Brother QL raster, Dymo raster): the app has already produced the
  printer's own command stream, so anything in between is a chance to corrupt it.
  Straight to the printer's raw USB device node: no CUPS, no rasterization.
* **CUPS** (`image/png`): the app has no encoder for this printer, so the image goes to
  `lp` and whatever driver that queue has installed prints it. This is what makes "any
  printer" honest -- it's the route for the printers nobody has written an encoder for.

Anything else is refused with a 415 rather than guessed at, because sending a JPEG to a
raw device node prints pages of binary noise, and it does it at the printer.

PRINTER_DEVICE starts empty on purpose -- until it's confirmed present, a raw job
returns a clear "not connected" error instead of guessing a device path that may not
exist (a USB printer's node is only created while it's actually plugged in and powered
on: /dev/usb/lp0, confirmed via dmesg when connected).
"""
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRINTER_DEVICE = os.environ.get("PRINTER_DEVICE", "/dev/usb/lp0")
# Blank means "the default queue", which is what a single-printer Pi should use.
CUPS_QUEUE = os.environ.get("PRINTER_CUPS_QUEUE", "")
API_KEY = os.environ.get("LABEL_PRINTER_KEY", "")
LISTEN_PORT = int(os.environ.get("LABEL_PRINTER_PORT", "9020"))

# Content types meaning "the app already produced the printer's own bytes". Keep these
# in step with the content types in inventory/label_drivers.py.
RAW_CONTENT_TYPES = frozenset({
    "application/x-zpl",
    "application/vnd.brother-ql",
    "application/vnd.dymo-labelwriter",
})
CUPS_CONTENT_TYPE = "image/png"

_device_lock = threading.Lock()


def route_for(content_type):
    """'raw', 'cups', or None when this bridge cannot deliver this kind of payload.

    A missing content type means raw, because that is what this bridge did before it
    knew about content types at all -- an older app version (or a plain curl) still
    works rather than breaking.
    """
    ctype = (content_type or "").split(";")[0].strip().lower()
    if not ctype:
        return "raw"
    if ctype in RAW_CONTENT_TYPES or ctype == "application/octet-stream":
        return "raw"
    if ctype == CUPS_CONTENT_TYPE:
        return "cups"
    return None


def _run_lp(command):
    """Runs `lp`. Kept as its own function so the spooling logic below is testable
    without a printer or a CUPS install."""
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


def _spool_to_cups(payload):
    """Hand an image to CUPS. Returns (ok, error_message).

    `lp` takes a path rather than reading stdin here, so the payload goes to a
    temporary file -- and that file is removed even when the spool fails, because a
    failed print job that also slowly fills /tmp is two problems.
    """
    if not shutil.which("lp"):
        return False, (
            "CUPS isn't installed on this machine (no 'lp' command). Install cups-client "
            "and a queue for your printer, or set a printer type this bridge can drive "
            "directly."
        )

    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        handle.write(payload)
        handle.close()

        command = ["lp"]
        if CUPS_QUEUE:
            command += ["-d", CUPS_QUEUE]
        command.append(handle.name)

        result = _run_lp(command)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "lp failed").strip()
        return True, ""
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    def _respond(self, status, body: bytes | str = b""):
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
            cups = bool(shutil.which("lp"))
            body = (
                f'{{"ok": {str(connected or cups).lower()}, "device": "{PRINTER_DEVICE}", '
                f'"device_present": {str(connected).lower()}, "cups": {str(cups).lower()}}}'
            )
            self._respond(200 if (connected or cups) else 503, body)
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
        payload = self.rfile.read(length)
        if not payload:
            self._respond(400, "empty body")
            return

        content_type = self.headers.get("Content-Type")
        route = route_for(content_type)
        if route is None:
            self._respond(
                415,
                f"this bridge can't print {content_type!r}. It takes ZPL, Brother QL or "
                "Dymo bytes, or a PNG for CUPS. Update the code in label-printer/pi/ on "
                "the Pi if the app has started sending something else.",
            )
            return

        if route == "raw":
            if not os.path.exists(PRINTER_DEVICE):
                self._respond(503, f"printer not connected (no {PRINTER_DEVICE} -- check the USB cable/power)")
                return
            try:
                with _device_lock:
                    with open(PRINTER_DEVICE, "wb") as f:
                        f.write(payload)
            except OSError as exc:
                self._respond(502, f"couldn't write to printer: {exc}")
                return
        else:
            ok, detail = _spool_to_cups(payload)
            if not ok:
                self._respond(502, f"couldn't spool to CUPS: {detail}")
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
