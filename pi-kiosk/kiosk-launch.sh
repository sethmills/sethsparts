#!/bin/bash
# Waits for the site to actually be reachable (WiFi/DNS can lag a few seconds after
# boot) before opening kiosk Chromium, so the first paint isn't a connection error.
for i in $(seq 1 30); do
  curl -s -o /dev/null -m 2 https://sethsparts.com && break
  sleep 1
done

# Auto-login on every launch (device-pairing via a long-lived secret token in
# ~/.config/kiosk-launch/env -- never Seth's actual account password). This is what
# the kiosk lands the browser on, not the plain site URL: it establishes/refreshes a
# real Django session, then redirects to "/", so this is self-healing across profile
# wipes, hardware swaps, and session-cookie expiry, not just a one-time manual login.
source "$HOME/.config/kiosk-launch/env" 2>/dev/null || true
START_URL="https://sethsparts.com/kiosk-autologin/?token=${KIOSK_AUTOLOGIN_TOKEN}&next=/"

exec /usr/bin/chromium \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --disable-session-crashed-bubble \
  --disable-translate \
  --check-for-update-interval=31536000 \
  --unsafely-treat-insecure-origin-as-secure=http://127.0.0.1:9091 \
  --user-data-dir=/home/seth/.config/chromium-kiosk \
  "$START_URL"
