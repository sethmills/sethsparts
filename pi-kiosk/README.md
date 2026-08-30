# Pi kiosk display

Source for the Raspberry Pi's kiosk setup (see `docs/HANDOFF.md` for full
context). Kept here for version control/backup — **not** auto-deployed; copy
changes to the Pi manually (scp + the relevant `systemctl`/`lightdm` restart).

- `kiosk-launch.sh` → `/home/seth/.config/kiosk-launch.sh` on the Pi. Waits
  for the site to respond, then launches Chromium in `--kiosk` mode against
  `https://sethsparts.com`, with a persistent profile (`~/.config/chromium-kiosk`)
  so the login session survives reboots, and
  `--unsafely-treat-insecure-origin-as-secure=http://127.0.0.1:9091` so the
  page's "Keyboard" button can call the local keyboard-toggle service despite
  being served over HTTPS (mixed-content would otherwise block it — safe here
  since this Chromium instance only ever visits our own site).
- `sethsparts-kiosk.desktop` → `/home/seth/.config/autostart/sethsparts-kiosk.desktop`.
  The actual autostart mechanism Raspberry Pi OS's default `/etc/xdg/labwc/autostart`
  already runs `lxsession-xdg-autostart` for — **don't** put this in
  `~/.config/labwc/autostart` instead, that file fully replaces (rather than
  extends) the system default and would kill the panel/wallpaper.
- `keyboard-toggle/server.py` → `/home/seth/keyboard-toggle/server.py`, run as
  the systemd **user** service `keyboard-toggle/keyboard-toggle.service` →
  `~/.config/systemd/user/keyboard-toggle.service` (needs the graphical
  session's DBus bus, hence a user unit; `loginctl enable-linger seth` keeps
  it running independent of active login state). Toggles squeekboard (already
  installed and running on this Pi) via its `sm.puri.OSK0.SetVisible` DBus
  method — squeekboard normally toggles from the taskbar, which kiosk mode
  hides, so this gives the page's own "Keyboard" button something to call.
  Listens on `127.0.0.1:9091` only.
