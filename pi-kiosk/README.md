# Pi kiosk display

Source for the Raspberry Pi's kiosk setup (see `docs/HANDOFF.md` for full
context). Kept here for version control/backup — **not** auto-deployed; copy
changes to the Pi manually (scp + the relevant `systemctl`/`lightdm` restart).

- `kiosk-launch.sh` → `/home/seth/.config/kiosk-launch.sh` on the Pi. Waits
  for the site to respond, then launches Chromium in `--kiosk` mode against
  `https://sethsparts.com`, with a persistent profile (`~/.config/chromium-kiosk`)
  so the login session survives reboots, and
  `--unsafely-treat-insecure-origin-as-secure=http://127.0.0.1:9091` so the
  page's touch-only header buttons can call the local kiosk-helper service
  despite being served over HTTPS (mixed-content would otherwise block it —
  safe here since this Chromium instance only ever visits our own site).
- `sethsparts-kiosk.desktop` → `/home/seth/.config/autostart/sethsparts-kiosk.desktop`.
  The actual autostart mechanism Raspberry Pi OS's default `/etc/xdg/labwc/autostart`
  already runs `lxsession-xdg-autostart` for — **don't** put this in
  `~/.config/labwc/autostart` instead, that file fully replaces (rather than
  extends) the system default and would kill the panel/wallpaper.
- `sethsparts-kiosk-relaunch.desktop` → `/home/seth/Desktop/sethsparts-kiosk-relaunch.desktop`.
  A double-clickable icon on the Pi's actual desktop that re-runs
  `kiosk-launch.sh` — the way back in after using the header's "⏻ Desktop"
  button to exit the kiosk. May need `chmod +x` and a one-time "Trust this
  launcher" click in the file manager before it'll run without a warning.
- `kiosk-helper/server.py` → `/home/seth/kiosk-helper/server.py`, run as the
  systemd **user** service `kiosk-helper/kiosk-helper.service` →
  `~/.config/systemd/user/kiosk-helper.service` (needs the graphical
  session's DBus bus for the keyboard route, hence a user unit;
  `loginctl enable-linger seth` keeps it running independent of active login
  state). Listens on `127.0.0.1:9091` only. Two routes, both called from
  touch-only buttons in the site's own header (invisible on desktop/mouse):
  - `POST /toggle` — show/hide squeekboard (already installed and running on
    this Pi) via its `sm.puri.OSK0.SetVisible` DBus method — squeekboard
    normally toggles from the taskbar, which kiosk mode hides.
  - `POST /exit-browser` — kills Chromium, revealing the desktop underneath
    (pcmanfm-pi/wf-panel-pi keep running regardless; only the kiosk browser
    is fullscreen over them). Use the relaunch desktop icon above to get
    back into the kiosk afterward.
- `squeekboard/squeekboard.service` → `~/.config/systemd/user/squeekboard.service`,
  enabled + started the same way as `kiosk-helper.service`. Raspberry Pi OS
  ships squeekboard preinstalled, but its stock autostart entry
  (`/etc/xdg/autostart/squeekboard.desktop`) only launches it via a wrapper
  script (`/usr/bin/sbtest`) that checks `libinput list-devices` for a touch
  device first — a check that loses a race against the USB touch
  controller's enumeration at boot on this Pi, so squeekboard silently never
  starts. This unit launches `/usr/bin/squeekboard` directly (no touch
  check needed — this kiosk always has a touchscreen), with
  `WAYLAND_DISPLAY=wayland-0` set explicitly since systemd user units don't
  otherwise inherit it. `sm.puri.OSK0.SetVisible` (what `kiosk-helper`'s
  `/toggle` route calls) only exists on the session bus once this is
  actually running.
