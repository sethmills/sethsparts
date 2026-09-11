# Zebra GK420T print-bridge

Source for the small piece that lives outside this Django app but makes the
"Custom label" page's Print button work (see `docs/HANDOFF.md` for full
context). Kept here for version control/backup — **not** auto-deployed by
`git pull` like the main app; copy changes to the Pi manually (scp).

- `pi/server.py` — small stdlib-only HTTP service that runs on the Raspberry
  Pi as the `label-printer` systemd service (`pi/label-printer.service`),
  listening on `127.0.0.1:9020` behind its own Cloudflare Tunnel
  (`label.sethsparts.com`, added as an extra public hostname on the same
  tunnel as `led.sethsparts.com`). Receives `POST /print` (raw ZPL bytes,
  fully rendered already) from the Django app and writes them straight to the
  printer's raw USB device node (`/dev/usb/lp0` by default — only exists
  while the printer is actually plugged in and powered on).
- All label *rendering* (fonts, size, bold/italic, optional barcode) happens
  on the Django side (`inventory/label_printing.py`), not here — this bridge
  is intentionally dumb, just a relay, same pattern as `led-controller/pi/server.py`.

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
