#!/bin/bash
export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-0
OUT=$(wlopm | head -1 | awk '{print $1}')
[ -n "$OUT" ] && wlopm --off "$OUT"
