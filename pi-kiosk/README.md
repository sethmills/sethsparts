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
  `~/.config/systemd/user/kiosk-helper.service` (`loginctl enable-linger seth`
  keeps it running independent of active login state). Listens on
  `127.0.0.1:9091` only. One route, called from a touch-only button in the
  site's own header (invisible on desktop/mouse):
  - `POST /exit-browser` — kills Chromium, revealing the desktop underneath
    (pcmanfm-pi/wf-panel-pi keep running regardless; only the kiosk browser
    is fullscreen over them). Use the relaunch desktop icon above to get
    back into the kiosk afterward.

  (An on-screen keyboard toggle used to live here too, calling squeekboard's
  `sm.puri.OSK0.SetVisible` over DBus. Removed — squeekboard's overlay never
  actually rendered above kiosk Chromium's fullscreen surface, a wlroots
  z-ordering quirk with fullscreen apps, and it's no longer needed now that
  there's a physical keyboard. The `squeekboard.service` unit that used to
  run alongside `kiosk-helper` should be disabled/removed too if still
  present: `systemctl --user disable --now squeekboard`.)
