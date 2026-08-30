#!/bin/bash
# Waits for the site to actually be reachable (WiFi/DNS can lag a few seconds after
# boot) before opening kiosk Chromium, so the first paint isn't a connection error.
for i in $(seq 1 30); do
  curl -s -o /dev/null -m 2 https://sethsparts.com && break
  sleep 1
done
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
  https://sethsparts.com
