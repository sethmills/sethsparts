#!/usr/bin/env bash
# The host side of the web "Upgrade now" button.
#
# The app's web process can't git-pull or rebuild its own container, so the button
# only writes a marker file (data/upgrade-request). This script — run by a systemd
# timer (see sethsparts-upgrade.timer) — notices the marker and applies the upgrade
# safely, then writes the outcome to data/upgrade-result where the Settings page
# shows it.
#
# Safe by construction, in the ways that matter:
#   * never runs without a request marker
#   * backs up the database first
#   * git pull --ff-only (a non-fast-forward aborts rather than clobbering anything)
#   * the result is always written, success or failure
set -euo pipefail

cd /opt/sethsparts
REQUEST=data/upgrade-request
RESULT=data/upgrade-result

[ -f "$REQUEST" ] || exit 0   # nothing requested

echo "Upgrade started $(date -Is)" > "$RESULT"

cp data/db.sqlite3 "data/db.sqlite3.pre-upgrade-$(date +%Y%m%d-%H%M%S).bak"

if ! git pull --ff-only origin main >> "$RESULT" 2>&1; then
  echo "FAILED: git pull was not a fast-forward (local changes on the host?)." >> "$RESULT"
  rm -f "$REQUEST"
  exit 1
fi

if ! docker compose --profile tunnel build >> "$RESULT" 2>&1; then
  echo "FAILED: docker build." >> "$RESULT"
  rm -f "$REQUEST"
  exit 1
fi

docker compose --profile tunnel up -d >> "$RESULT" 2>&1
echo "OK: upgraded $(date -Is)" >> "$RESULT"
rm -f "$REQUEST"
