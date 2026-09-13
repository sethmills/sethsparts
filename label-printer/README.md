# Label print-bridge

Source for the small piece that lives outside this Django app but makes the
"Custom label" page's Print button work (see `docs/HANDOFF.md` for full
context). Kept here for version control/backup — **not** auto-deployed by
`git pull` like the main app; copy changes to the Pi manually (scp).

- `pi/server.py` — small stdlib-only HTTP service that runs on the Raspberry
  Pi as the `label-printer` systemd service (`pi/label-printer.service`),
  listening on `127.0.0.1:9020` behind its own Cloudflare Tunnel
  (`label.sethsparts.com`, added as an extra public hostname on the same
  tunnel as `led.sethsparts.com`). Receives `POST /print` from the Django app
  and gets the payload to the printer one of two ways.
- All label *rendering and encoding* (fonts, size, bold/italic, optional
  barcode, and the printer's own command language) happens on the Django side
  (`inventory/label_printing.py` and `inventory/label_drivers.py`), not here.

## The two routes

The bridge looks at the request's `Content-Type` and picks one:

| Content type | Route | What happens |
|---|---|---|
| `application/x-zpl` | raw | bytes written straight to `PRINTER_DEVICE` |
| `application/vnd.brother-ql` | raw | same |
| `application/vnd.dymo-labelwriter` | raw | same |
| `image/png` | CUPS | image written to a temp file, then spooled with `lp` |
| anything else | — | refused with **415** and an explanation |

**Raw** is the default path and the one this was built for: the app produced
the printer's own command stream, so anything in between is a chance to
corrupt it. **CUPS** exists for printers nobody has written an encoder for —
the app sends a PNG and the queue's own driver does the work. Anything else is
refused rather than guessed at, because writing a JPEG to a raw printer device
prints pages of binary noise, at the printer.

A request with **no** `Content-Type` is treated as raw, which is what this
bridge did before it understood content types at all.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `LABEL_PRINTER_KEY` | *(none — everything is rejected)* | shared secret; must match the app's `LABEL_PRINTER_KEY` |
| `LABEL_PRINTER_PORT` | `9020` | listen port |
| `PRINTER_DEVICE` | `/dev/usb/lp0` | raw USB device node for the raw routes |
| `PRINTER_CUPS_QUEUE` | *(blank — the default queue)* | CUPS queue name for the `image/png` route |

`GET /health` reports which of the two are actually available
(`device_present`, `cups`), so you can tell "the printer is unplugged" from
"CUPS isn't installed" without guessing.

## One-time Pi setup

1. `scp -r label-printer/pi seth@<pi-ip>:/home/seth/label-printer`
2. `sudo usermod -aG lp seth` then log out/in (or reboot) — the printer's USB
   device node is normally owned by `root:lp` when it appears, and the
   service runs as `seth` (least-privilege, matching `led-controller`'s use
   of the `dialout` group for the Scorpio's serial port).
3. `sudo mkdir -p /etc/label-printer && sudo tee /etc/label-printer/env` with:
   ```
   LABEL_PRINTER_KEY=<same value as LABEL_PRINTER_KEY in Hetzner's /opt/sethsparts/.env>
   ```
   Add `PRINTER_CUPS_QUEUE=<queue>` too if you're using the CUPS route, and
   `PRINTER_DEVICE` if the printer isn't on `/dev/usb/lp0`.
4. `sudo cp /home/seth/label-printer/label-printer.service /etc/systemd/system/`
   then `sudo systemctl daemon-reload && sudo systemctl enable --now label-printer`
5. In the Cloudflare Zero Trust dashboard, on the **same tunnel** already used
   for `led.sethsparts.com`: add another public hostname, `label.sethsparts.com`
   → `http://localhost:9020`.
6. Add `LABEL_PRINTER_URL=https://label.sethsparts.com` and the matching
   `LABEL_PRINTER_KEY` to Hetzner's `/opt/sethsparts/.env`, then redeploy.

Both env secrets (`LABEL_PRINTER_KEY` on the Pi's `/etc/label-printer/env`,
and the matching value in Hetzner's `/opt/sethsparts/.env`) must stay in
sync — neither is committed here.

## Using the CUPS route

For a printer with no encoder in `inventory/label_drivers.py`:

1. On the Pi: `sudo apt install cups cups-client`, add the printer, and note
   the queue name (`lpstat -p`).
2. Set `PRINTER_CUPS_QUEUE=<queue>` in `/etc/label-printer/env` and restart
   the service.
3. In the app: Settings → Labels → printer type **"Any printer, via CUPS"**.

The app then sends a PNG at the resolution set on that page. Worth setting that
box to the printer's real dot density: CUPS can scale, but a label printed at
the wrong density comes out the right shape and the wrong size.

## What has actually been tested

Only the ZPL route, on a Zebra GK420T, which is what every label this project
prints goes through. The Brother QL and Dymo encoders are written from those
manufacturers' own command references (`inventory/label_drivers.py` cites
each one) and have **never been tried on the printers they target**. The CUPS
route is untested here too, but it has the least to get wrong: it hands the
image to whatever driver is installed for the queue.

If you're the first person to try one of the untested routes, the app will
have printed nothing useful, and `sudo journalctl -u label-printer` plus the
raw payload from `inventory/label_drivers.py`'s tests is where to start.
