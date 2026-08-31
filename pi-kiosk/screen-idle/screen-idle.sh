#!/bin/bash
# Blanks the Pi's display after IDLE_SECONDS of no input, wakes it on any
# input (touch, mouse movement, or the barcode scanner -- which is just a
# USB HID keyboard, so it's covered by "any input" already, no special
# handling needed). Uses wlopm (wlr-output-power-management) via
# screen-off.sh/screen-on.sh, which look up whatever output labwc currently
# has connected -- so this keeps working across display swaps without
# hardcoding an output name like "DSI-1".
export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-0

IDLE_SECONDS=600
DIR="$(dirname "$(readlink -f "$0")")"

exec swayidle -w \
  timeout "$IDLE_SECONDS" "$DIR/screen-off.sh" \
  resume "$DIR/screen-on.sh"
