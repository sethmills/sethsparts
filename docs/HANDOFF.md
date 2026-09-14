# Seth's Parts — handoff / continuation notes

Read `README.md` first (repo layout, local dev, deploy, feature tour), then this file. This doc is a dated running log — newest entries at the bottom — plus the "current live state" facts below that don't change often. There is no build history outside this repo; if you're picking this up from a fresh clone or a different assistant, everything you need is in here and in git history.

## Current live state (last refreshed 2026-09-13)

- **Live site:** https://sethsparts.com (Django + SQLite, Docker, Cloudflare Tunnel — no nginx/Caddy).
- **Server:** `root@95.217.21.132` (Hetzner, hostname `content-hub`), app at `/opt/sethsparts`.
- **Deploy flow:** `git push` → on the server: **back up `data/db.sqlite3` first**, then `cd /opt/sethsparts && git pull --ff-only && docker compose up -d --build`. Back up first because the container runs `migrate` before gunicorn on every start, so a deploy is also a migration run against the live database. The server has its own **read-only** deploy key (`.deploy_key`, gitignored) — separate from whatever key pushes to GitHub.
- **GitHub:** private repo `sethmills/sethsparts`, `main` branch — private for now, but written for release: treat every diff as if it were already public.
- **Version / releases:** `inventory/version.py` is `0.1.0`, and `v0.1.0` is tagged and pushed. The update check asks GitHub (`releases/latest`, then `tags`), so a tag that only exists locally does nothing at all — publishing a release means pushing the tag (item 26).
- **Secrets:** live only in `/opt/sethsparts/.env` on the server (gitignored, never committed) — see `.env.example` in the repo root for the full list with explanations: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `TUNNEL_TOKEN` (required), plus optional `VOICE_SEARCH_API_KEY`, `LED_CONTROLLER_URL`/`KEY`, `LABEL_PRINTER_URL`/`KEY`, `KIOSK_AUTOLOGIN_TOKEN`/`USERNAME`.
- **Cloudflare:** one account, multiple tunnels — `sethsparts.com` (the main site, Hetzner-hosted) and `sethsparts-led-controller` (runs on the workshop Pi itself, currently carrying **two** public hostnames on its "Published application routes" tab: `led.sethsparts.com` → `localhost:9000` and `label.sethsparts.com` → `localhost:9020`). **Gotcha worth remembering:** this tunnel's dashboard "Hostname routes" tab is empty/unused — routes actually live under the differently-named "Published application routes" tab. Don't assume a tunnel's routes aren't configured just because one tab looks empty; check both.
- **Logins:** the app has its own login page at `/login/` (item 25), with **Log out** in the More menu. The Django admin keeps its own separate login at `/admin/login/`. Username `seth` for both; passwords were set by Seth directly (not recorded here).
- **Workshop Pi:** `seth@192.168.1.92`, hostname `pi5` (a Raspberry Pi 5; the original Pi 4 was fully migrated off and is no longer part of anything live). Hosts: the kiosk display, `led-controller` (systemd system service) driving a Feather RP2040 Scorpio over USB serial, `label-printer` (systemd system service) driving a Zebra GK420T over USB, and `kiosk-helper`/`screen-idle` (systemd **user** services, `loginctl enable-linger seth`).
- **Drawer numbering:** the 3 original parts-cabinet containers (#38/#39/#40) have drawers labeled "Drawer 1"–"Drawer 27" (a=1-9, b=10-18, c=19-27). Two more cabinets exist: #119 "Cabinet 4" (9 drawers, 28-36, one LED strip, no bins — oversized/different items) and #120 "Cabinet 5" (5 drawers, 37-41, no LED mapping yet). Only drawers 1-27 have the 16-bin subdivision (`Bin`/`SubBin` models).
- **Pi kiosk display:** boots straight into a kiosk Chromium pointed at `https://sethsparts.com/kiosk-autologin/?token=...`, which mints a real session server-side (never Seth's actual password) — see `pi-kiosk/README.md` for the full autostart chain. The on-screen keyboard toggle that used to exist here was removed (never rendered above the fullscreen kiosk surface); Seth uses a physical keyboard now.
- **Parts-review workbook:** `docs/parts_review.xlsx`, regenerated via `scripts/export_parts_review.py --merge <path-to-prior-export>` — merges in whatever Seth already typed into the "fill in" columns by Part ID, so re-running never clobbers his progress. He's still actively working through it, alongside `docs/clarification_workstream.md`.
- **Hardware bridges, all verified working live:** LED locate (row/column readout, see item 19 below), Zebra label printing (item 18), kiosk auto-login. If something in one of these areas seems broken, check the relevant systemd service on the Pi and its Cloudflare Tunnel hostname before assuming it's a code bug — most past issues here were connectivity/config, not logic.
- **Test suite:** `./venv/bin/python manage.py test inventory` — 759 tests, ~41s, fully offline (external HTTP mocked, no hardware needed). Also `./venv/bin/python scripts/mutation_check.py` — 75 deliberate breakages, currently 75/75 caught; it has to stay at 100% before a deploy. See "Tests" in `README.md`, and item 21 below.

## Backlog — requested this session, not yet built

Seth said explicitly: finish "the site" work below before the Raspberry Pi phase; hold the Amazon-matching pass until he finishes his spreadsheet edits; the dad-sharing item has no action yet, just keep it in mind.

### 1. Label printing (Zebra GK420T) — do this first, it's clearly scoped
Seth owns a Zebra GK420T thermal label printer, connected via **USB** (confirmed). Feasible on a Raspberry Pi: set it up as a CUPS raw queue (Pi OS is Debian/ARM, CUPS runs natively; a raw queue passes ZPL bytes straight through with no rasterization) — this is the better foundation for the Pi print-bridge than writing directly to `/dev/usb/lp0`, since CUPS handles permissions/queueing.

3 label sizes owned, bought from these Amazon listings, sizes/purpose confirmed by Seth:
1. https://www.amazon.com/dp/B0888DMQ3Q — 4"×2", direct thermal, 750/roll — **general-purpose labeling**
2. https://www.amazon.com/dp/B09S9V5LQZ — 1"×0.5", thermal, perforated, 16 rolls/38,880 labels — **barcodes**
3. https://www.amazon.com/dp/B01GJGC2OK — 2"×1", direct thermal, 12 rolls/15,600 labels — **totes**

Two label types needed:
- **Big-number labels** — for totes/custom storage, just a large easily-visible number.
- **Barcode + text labels** — for containers/drawers, barcode plus an abbreviated text description (e.g. "Container 1 Drawer 5"). Design/format is left to me.

Also wants an **impromptu label** option — print an ad hoc label on the spot, not tied to any existing container/drawer.

Proposed home: a new top-level nav tab (Seth said "perhaps make it a separate tab", design otherwise open).

**Open question to resolve before building:** how is the GK420T actually connected — USB to a specific machine, or does it have network/serial capability? The site runs on a remote Hetzner server; if the printer is USB-only on Seth's local machine, "print from the platform" needs either (a) generate a ZPL file the browser downloads and Seth sends to the printer via his own OS print dialog, or (b) a small local print-bridge/agent on whatever machine the printer is plugged into that polls the site or receives pushed jobs. Don't assume — ask Seth how the printer is connected, or investigate once we're in the Raspberry Pi phase (see item 8) since that Pi may end up being the printer's host.

### 2. Voice search via Home Assistant Assist — ✅ built (app side); HA-side config below, not yet applied
**Correction:** no Amazon/Alexa involved at all, deliberately — Seth's voice device is an **M5Stack Atom Echo** running as a Home Assistant Assist voice satellite (ESP32, wake word → HA's own Assist conversation pipeline, entirely local to HA). Wants: ask a question by voice, get back which drawer/container has the part.

App-side (built): `GET /api/locate/?q=<query>` (`views.api_locate_part`), reuses `build_search_query` from `inventory/search.py`. Auth is a shared-secret key (not session login, since this is machine-to-machine from HA) — checked via `X-Api-Key` header or `?key=` param against `settings.VOICE_SEARCH_API_KEY`, read from the `VOICE_SEARCH_API_KEY` env var (add it to `/opt/sethsparts/.env` on the server, and to local `.env` for testing — not committed, same pattern as `DJANGO_SECRET_KEY`). Returns JSON: `{"query": ..., "count": N, "matches": [{"name", "manufacturer", "locations": [...], "quantity_summary"}]}`, top 5 matches ordered by the existing search relevance.

HA-side (not yet applied — needs Seth to add this to his own HA config, which lives outside this repo):
1. A `rest_command` calling `http://<mac-or-server-host>:<port>/api/locate/?q={{ query }}` with the `X-Api-Key` header set to the shared secret.
2. A custom sentence (`custom_sentences/en/locate_part.yaml`) matching phrases like "where is {query}" / "find {query}" / "locate {query}".
3. An intent script that calls the rest_command, then speaks back `matches[0].locations` joined, or "I couldn't find that" if `count` is 0.
See Home Assistant docs for exact custom-sentence/intent-script YAML syntax on Seth's HA version before pasting — not verified against his actual instance from this session.

### 3. LED "find the part" indicator strips — ✅ app-side groundwork built; hardware/topology still pending
Individually-addressable LED strips (confirmed **WS2812B/NeoPixel**) already run horizontally above/below each drawer, across the outside of the cabinets. Wiring topology across cabinets is **not finalized** ("something more complex, not sure yet" — not a simple one-strip-per-cabinet-in-order layout), and there's **no Raspberry Pi wired up yet** — Seth explicitly asked for the app-side design/code to be written ahead of the hardware, to run once both exist.

Built: `Drawer` gained three optional fields (migration `0008_...`) — `led_strip` (logical strip name/ID, free text), `led_start_index` (0-based), `led_count` — deliberately just a "logical strip name + index range" so it stays correct regardless of whatever the actual wiring topology turns out to be. Editable via `/admin/` (`DrawerAdmin` now lists them) — **nothing is populated yet**, by design, until Seth finalizes the wiring.

A drawer with `led_strip` + `led_start_index` set shows a "💡 Locate" button on its detail page (`views.locate_drawer_led`, POST to `/drawers/<pk>/locate-led/`), which POSTs `{strip, start_index, count}` as JSON to `{LED_CONTROLLER_URL}/locate` (env var, unset by default — button shows a friendly "not configured" message instead of erroring) with an optional `X-Api-Key: {LED_CONTROLLER_KEY}` header. Both env vars are already wired into `docker-compose.yml` as optional. All three failure paths (no mapping set, no controller URL configured, controller unreachable) were tested via Django's test client and fail gracefully with a `messages.error`, never a 500.

**Progress since the Pi arrived:** Pi is up (hostname `sethsparts`, Debian 13 trixie, `seth@192.168.1.227`, Mac's SSH key now trusted — no more password needed). Confirmed a Raspberry Pi Feather RP2040 **Scorpio** (Adafruit #5650, 8-channel PIO-driven NeoPixel driver — a good fit given Pi 5's native `rpi_ws281x` GPIO driving is broken, see below) is wired to the Pi over USB and enumerates at `/dev/ttyACM0` (currently running some pre-existing Arduino-core firmware — VID `2e8a`, "PicoArduino" — will be reflashed once the relay protocol is written).

Cloudflare Tunnel for the Pi is fully live end-to-end: a new tunnel (separate from the `sethsparts` one on Hetzner) runs as a systemd service on the Pi (`cloudflared.service`, installed via the arm64 `.deb`, no Docker on this Pi), routing `led.sethsparts.com` → `http://localhost:9000`. Verified with `curl https://led.sethsparts.com` → 502, which is the *expected* result (tunnel reaches the Pi; nothing listens on :9000 yet). `LED_CONTROLLER_URL=https://led.sethsparts.com` and a freshly generated `LED_CONTROLLER_KEY` are now set in `/opt/sethsparts/.env` on Hetzner and confirmed loaded into the running container (`docker compose up -d`, no rebuild needed for an env-only change).

**Receiver service — ✅ built, deployed, and verified end-to-end (minus real LEDs).** `/home/seth/led-controller/server.py` on the Pi (stdlib `http.server`, no extra deps beyond the already-installed `pyserial`), running as systemd service `led-controller` (`/etc/systemd/system/led-controller.service`, config in `/etc/led-controller/env` — `LED_CONTROLLER_KEY` there matches the one in Hetzner's `.env`). Listens on `127.0.0.1:9000` only (same "tunnel-only exposure" pattern as the main Django container). Verified live through `https://led.sethsparts.com`:
- `GET /health` → lists configured strip names (currently empty on purpose).
- `POST /locate` with wrong key → 403.
- Unmapped strip name → 409 with a clear "add it to strip_map.json" message.
- Mapped strip name → opens `/dev/ttyACM0` and writes the command (confirmed via the current, unrelated Arduino firmware not replying — expected until the Scorpio has our firmware).

`/home/seth/led-controller/strip_map.json` is the **exact "input that info when done to match" file** — currently `{}`. Once cabinet wiring is decided, add one line per logical strip name (matching what you'll type into `Drawer.led_strip` in `/admin/`), e.g. `{"cabinet1": 0, "cabinet2": 1}`, mapping to the Scorpio's physical channel number (0-7). No restart needed — the service re-reads it on every request.

**Scorpio firmware — ✅ written, staged, not yet flashed.** CircuitPython (`adafruit_neopxl8`'s `NeoPxl8` driver — chosen over Arduino since it's far easier for me to iterate on and deploy over SSH once the board mounts as a USB drive). Files staged at `/home/seth/led-controller/scorpio-firmware/` on the Pi (`boot.py` — opens a second USB "data" serial channel so the protocol never collides with the CircuitPython REPL; `code.py` — parses `{"cmd": "locate"/"clear"/"ping", ...}` JSON lines, drives the right channel/pixel-range, auto-clears a locate after `duration_ms` so nothing stays lit forever). `STRAND_LENGTH = 100` is a placeholder max-pixels-per-channel in `code.py` — bump it if any single strip ends up longer than that.

**✅ Full pipeline verified end-to-end (2026-08-30), minus visible LEDs.** Seth flashed CircuitPython 10.2.1 onto the Scorpio (bootloader mode → drag UF2 from circuitpython.org onto `RPI-RP2`); I then copied `adafruit_neopxl8`/`adafruit_pioasm`/`adafruit_pixelbuf` (from the matching Adafruit bundle release) plus `boot.py`/`code.py` onto the resulting `CIRCUITPY` drive over SSH. One gotcha worth remembering: `usb_cdc.enable()` in `boot.py` only takes effect after a **true hardware reset** (`microcontroller.reset()`, or physical reset button) — a soft reset (Ctrl-D) re-runs boot.py/code.py but does *not* re-enumerate USB, so the second serial ("data") channel silently stayed absent until a real reset. After that, the board enumerates as two stable devices: `/dev/serial/by-id/usb-Adafruit_Feather_RP2040_Scorpio_..._-if00` (console/REPL) and `...-if02` (our data channel — this is what `SCORPIO_SERIAL_PORT` in `/etc/led-controller/env` on the Pi now points to).

Tested with a temporary `strip_map.json` entry (`{"cabinet-test": 0}`, reset back to `{}` afterward) by POSTing straight to `https://led.sethsparts.com/locate` — got `{"ok": true, "scorpio_reply": "{\"ok\": true}"}`, confirming every hop: Django's Locate button → Hetzner → Cloudflare Tunnel → Pi `led-controller` service → USB serial → Scorpio `code.py` → `NeoPxl8`. Nothing lights up yet only because no physical LED strip is wired to the Scorpio's channels.

**Still needed:**
1. LEDs (arriving today per Seth) wired to the Scorpio's channel outputs.
2. The wiring topology decision + populating `led-controller/pi/strip_map.json`-style entries in the real `/home/seth/led-controller/strip_map.json` on the Pi, and each Drawer's `led_strip`/`led_start_index`/`led_count` in `/admin/` on Seth's Parts.
3. Once real strip lengths are known, double check `STRAND_LENGTH = 100` in `scorpio-firmware/code.py` is still ≥ the longest strip on any one channel (raise it and redeploy to `CIRCUITPY` if not).

### 4. Intake / add-product form — ✅ built
`/intake/?container=<number>` or `/intake/?drawer=<pk>` (`views.part_intake`), linked as "+ Add a part here" from container and drawer detail pages. Only Name is required; Category, Manufacturer, Electronic, Description, Quantity, Reorder threshold, Reorder/buy link, and a new **Datasheet link** field are all optional. Submitting creates the `Part` and a `StockItem` at the pre-filled location in one step, then redirects back to that container/drawer. Added `Part.datasheet_url` (migration `0007_part_datasheet_url`) since the existing `Attachment` model requires an actual uploaded file and doesn't fit a quick reference-link use case.

### 5. "Tagging" section — ✅ built
`/tagging/` (`views.tagging_list` / `views.tagging_update`), linked in the top nav. Filters by status (needs review / needs clarification / both), by location (dropdown of containers/drawers that currently hold a flagged part, with counts), and by name/description search. Each flagged Part renders as its own card/form (manufacturer, category, description, reorder URL, enrichment status) that saves directly back to the `Part` record via POST and redirects back to the same filtered view — no spreadsheet round-trip. Verified against the live local DB (313 parts currently in the queue).

### 6. Amazon order-history matching — do not start until Seth says his spreadsheet pass is done
He uploaded `/Users/seth/Downloads/amazon_order_history.xlsx` for this. When the time comes:
- Don't just trust the URLs Seth already put in the spreadsheet as ground truth for manufacturer — independently verify/determine the actual manufacturer, especially for discontinued SparkFun items (a source having *related documentation* isn't the same as being the actual maker).
- Cross-reference remaining unmatched `Needs Review`/`Needs Clarification` items against the Amazon order history to find likely purchases.
- Produce a revised list of **potential** Amazon matches for Seth to confirm yes/no on — don't write these into the DB unconfirmed.
- For confirmed matches: pull relevant spec/description info from the Amazon product page itself, or at minimum link the product URL on the Part page so Seth can dig in later.

### 7. Sharing the repo with his dad — no action item, just keep in mind
Seth wants to eventually let his dad clone this and self-host his own instance (with or without my help), plus some setup documentation. Nothing to build now, but when designing new features, avoid baking in Seth-specific assumptions where it's easy not to (e.g. this is why hostnames/secrets already live in `.env`, not hardcoded). Revisit properly when he actually asks to move on this.

### 8. Raspberry Pi + touchscreen — explicitly "after we finish the site"
Planned as the main physical interface device for:
- The 2 USB barcode scanners he owns (1 wired, 1 wireless) — currently unusable by the app except via a phone camera, since there's no local device to plug them into.
- Controlling the LED strips (item 3) and "other future peripherals" directly.
- Possibly hosting/driving the Zebra printer too (see item 1's open question) — **research whether the GK420T has a Linux/Raspberry Pi driver path** (it's a ZPL-native printer; generally works fine on Linux via CUPS with a Zebra driver, or even raw ZPL sent directly over USB/network without CUPS at all — worth confirming specifics, but Seth said explicitly to pick this up after the site work, so don't build/research deeply until then).

### 9. UI polish, kiosk keyboard, and product photos — ✅ built (2026-08-30, ad hoc requests)
Visual refresh (logo mark, card shadows, consistent spacing, styled message banners, `@media (pointer: coarse)` touch sizing) landed first — see git history for that commit. Three follow-up asks from the same session:

- **Kiosk on-screen keyboard:** squeekboard was already installed/running on the Pi but had no way to show/hide with Chromium in kiosk mode (its usual toggle lives on the taskbar, which kiosk mode hides). Added a "⌨ Keyboard" button, visible only on touch devices (`.touch-only`, `@media (pointer: coarse)`), in the site's own header — it calls a small new local service (`pi-kiosk/keyboard-toggle/`) over `http://127.0.0.1:9091/toggle`, which flips squeekboard's `sm.puri.OSK0.Visible` property via DBus (`busctl --user`). Runs as a systemd **user** unit (needs the graphical session's DBus bus) with `loginctl enable-linger seth` so it survives without an active login. Chromium needed `--unsafely-treat-insecure-origin-as-secure=http://127.0.0.1:9091` added to `kiosk-launch.sh` since the page is HTTPS and would otherwise mixed-content-block the call.
- **Logo/nav cleanup:** fixed the header brand wordmark wrapping/misaligning next to the icon (`white-space: nowrap` + `line-height: 1` on the flex container) and restyled nav links as visible pill buttons (persistent background/border, not just on hover).
- **Product photos:** part detail pages now have an "Add a photo" section — a plain file input (works everywhere, phone browsers offer camera-or-gallery natively on tap, no special code needed) plus a `.touch-only` "📷 Take a photo" button that opens a live `getUserMedia` preview and uploads a captured frame. One JS code path serves both the Pi kiosk and any phone visiting the site, since `getUserMedia` automatically uses whichever camera is actually present on that device — verified against the Pi's real camera (an OV5647 module via libcamera) directly over SSH before writing the UI (`enumerateDevices` found it as `"ov5647"`; `getUserMedia` returned a live 640x480 stream). Reuses the existing `Attachment` model (`doc_type=image`, already rendered by the Documentation section) via a new `add_part_photo` view — no schema changes needed. Bumped `DATA_UPLOAD_MAX_MEMORY_SIZE`/`FILE_UPLOAD_MAX_MEMORY_SIZE` to 20MB (Django's 2.5MB default is too small for phone camera photos).

### 10. Screen blanking + robust Pi-detection — ✅ built (2026-08-31)
Two follow-ups from item 9, both because Seth is swapping which physical display is attached to the Pi:

- **Pi-only buttons now use runtime service detection, not touch/screen-size.** The "⌨ Keyboard" and "⏻ Desktop" buttons were gated on `pointer: coarse`, which doesn't actually distinguish "the Pi" from "any touchscreen" (would've also shown on Seth's phone, and said nothing about which *display* is attached). Changed to a `.pi-only` class, hidden by default, revealed only when a tiny inline script in `base.html` successfully fetches `http://127.0.0.1:9091/health` at page load (short `AbortController` timeout) — that service only ever runs on the Pi itself, so this stays correct regardless of which screen or touch device is involved, including future display swaps. The photo-capture button stays on the original `.touch-only`/`pointer: coarse` gating since it's genuinely meant for both the Pi and any phone, per item 9. `kiosk-helper/server.py` gained the `/health` route plus a CORS header (needed since this fetch has to actually read the response, unlike the fire-and-forget `no-cors` calls the other two buttons use).
- **Screen blanking:** new `pi-kiosk/screen-idle/` — `screen-idle.sh` runs `swayidle -w timeout 180 <screen-off.sh> resume <screen-on.sh>` as systemd user service `screen-idle`. `screen-off.sh`/`screen-on.sh` call `wlopm` (a dedicated wlr-output-power-management CLI tool, confirmed installed and working against labwc) against whatever output name `wlopm` itself currently reports first — deliberately not hardcoded to `DSI-1`, so it keeps working after the display swap as long as the new display responds to standard Wayland output-power-management (confirmed: `wlr-randr` on this Pi does *not* support power toggling, but the dedicated `wlopm` tool does). Wake triggers (touch, mouse movement, barcode scanner) all come for free from swayidle's own idle-notify-based resume detection — the barcode scanner is just a USB HID keyboard, so "any input" already covers it, no per-device-type code needed. 180s timeout is arbitrary/adjustable (`IDLE_SECONDS` in `screen-idle.sh`). Verified by manually running `screen-off.sh`/`screen-on.sh` directly and confirming `wlopm`'s reported state actually flipped, and separately confirmed swayidle correctly fires on labwc's idle protocol via a short-timeout test before wiring up the real 180s service. **Not yet tested against the new display** — if it doesn't respond to `wlopm`, the fallback would be the DSI backlight sysfs path (`/sys/class/backlight/10-0045/bl_power`, confirmed present for the *current* touchscreen) instead, but that's panel-specific and won't carry over to a different display, so only worth building if `wlopm` turns out not to work on the replacement.

### 11. LED wiring topology (confirmed so far), USB camera/mic, and the Pi 5 migration (2026-08-31)

**LED channel mapping confirmed, indices still pending.** Seth has the LEDs (WS2812B, as expected) but hasn't stuck them down/counted per-drawer yet. Confirmed cabinet↔Scorpio-channel mapping, now in `led-controller/pi/strip_map.json.example`:
- Channel 0/1 = cabinet 1 (drawers 1-9) left/right
- Channel 2/3 = cabinet 2 (drawers 10-18) left/right
- Channel 4/5 = cabinet 3 (drawers 19-27) left/right
- Channel 6 = cabinet 4 (drawers 28-36) **left only so far** — channel 7 (cabinet 4 right) not confirmed yet, and note all 8 Scorpio channels are spoken for by cabinets 1-4 alone if the left/right pattern holds, meaning cabinet 5 (drawers 37-41, containers #119/#120) likely won't get LED indicators unless a second controller is added later — don't assume, ask if it comes up.

This is exactly why `Drawer` LED info became a separate `DrawerLedSegment` related model (see item 10's commit) instead of flat fields — each drawer needs entries on *two* strips (left+right), both firing together when located, not one.

**Still needed before any of this lights up:** per-drawer LED counts/start-indices once Seth sticks the strips down and counts (his words: "I have to stick the LEDs down and count how many per drawer"), populated as `DrawerLedSegment` rows via `/admin/` (one row per drawer per side it has LEDs on).

**USB camera (replacing the Pi camera for photo capture):** no code changes needed. The `getUserMedia({video: {facingMode: 'environment'}})` call in `part_detail.html` already uses a bare (non-`exact`) constraint, so browsers treat it as a preference, not a requirement — it'll happily fall back to whatever camera is actually present, including a generic USB webcam with no facing-mode metadata at all. Should be plug-and-play once Seth has the camera; worth a quick live check at that point but nothing to build now.

**USB camera's built-in mic for HA voice, replacing the Atom Echo — answered, not built:** technically possible. The relevant project is [Wyoming Satellite](https://github.com/rhasspy/wyoming-satellite) (USB mic/speaker + a Linux box → local wake-word satellite for HA's Assist pipeline, using openWakeWord) — **but it's no longer actively maintained**, superseded by **Linux Voice Assistant** (same idea, newer ESPHome-based protocol, HA's current recommended approach for a Pi + USB mic). Either way it needs: a wake-word engine running continuously on the Pi, and — importantly — **a speaker**, since a mic alone only covers half of a voice interaction (HA speaks responses back via TTS). Given the Pi will already be running the kiosk browser, consolidating voice-satellite duty onto it means resource contention and a second thing that can break if the kiosk crashes/reboots, versus the Atom Echo's small dedicated always-on hardware. My lean: keep the Atom Echo unless Seth specifically wants to consolidate — his call. Not building either path until he decides and the camera/mic hardware is actually in hand.

**Switching to a Raspberry Pi 5 "for everything"** (SD card still being formatted as of 2026-08-31, not ready yet). Once Seth gives SSH access to the fresh Pi 5, full checklist of everything currently living on the Pi 4 that needs re-setting-up there (all sourced in this repo, so it's mostly re-running deploy steps, not re-figuring-out how):
1. Basic OS setup: confirm Raspberry Pi OS + labwc/lightdm (same as Pi 4) or note if different; set hostname, enable SSH, copy Mac's SSH key over (`ssh-copy-id`), confirm `sudo` access.
2. Desktop autologin (`autologin-user=seth` in `/etc/lightdm/lightdm.conf` — Pi 4 already had this out of the box; verify same on Pi 5's image or set it via `raspi-config`).
3. Kiosk: deploy `pi-kiosk/kiosk-launch.sh` → `~/.config/kiosk-launch.sh`, `pi-kiosk/sethsparts-kiosk.desktop` → `~/.config/autostart/`, `pi-kiosk/sethsparts-kiosk-relaunch.desktop` → `~/Desktop/`.
4. `pi-kiosk/kiosk-helper/` → `~/kiosk-helper/`, install as systemd user service (`~/.config/systemd/user/kiosk-helper.service`) — needs squeekboard already installed on the OS image (`apt install squeekboard` if not).
5. `pi-kiosk/screen-idle/` → `~/screen-idle/`, install as systemd user service. Re-verify `swayidle`/`wlopm` are installed (`apt install swayidle wlopm`) and that `wlopm` still works against whatever labwc/output setup the Pi 5 + (possibly new) display present — re-run the same functional test used on the Pi 4 (manually toggle `screen-off.sh`/`screen-on.sh` and confirm via `wlopm`'s own listing) before trusting the timer.
6. `loginctl enable-linger seth` (needed for both user services to survive without an active login).
7. Chromium + squeekboard: confirm both present on the Pi 5's OS image (`apt install chromium squeekboard wfplug-squeek` if not).
8. LED controller: `led-controller/pi/server.py` → `~/led-controller/server.py`, `led-controller/pi/led-controller.service` → systemd **system** service (not user — this one doesn't need the desktop session), `strip_map.json` seeded from the now-updated `strip_map.json.example` above. Scorpio board physically moves to the new Pi's USB port — serial device path will very likely change (was `/dev/serial/by-id/usb-Adafruit_Feather_RP2040_Scorpio_..._-if02` on the Pi 4; re-discover via `ls /dev/serial/by-id/` after plugging in, update `SCORPIO_SERIAL_PORT` in `/etc/led-controller/env` accordingly).
9. Cloudflare Tunnel for `led.sethsparts.com`: the tunnel token itself isn't tied to specific hardware — install `cloudflared` fresh on the Pi 5 (same `.deb` approach as before) and run `cloudflared service install <same token>` — no Cloudflare dashboard changes needed, same hostname keeps working.
10. USB barcode scanner(s) + new USB camera: just plug in, should be plug-and-play (HID keyboard emulation for the scanner, standard UVC webcam for the camera) — nothing to pre-configure.
11. Once confirmed working end-to-end, decommission the Pi 4 (or repurpose — Seth's call, not assumed here).

### 12. Real LED data seeded + two led-controller bugs found and fixed (2026-08-31)

Seth stuck the LEDs down and measured. **Corrected channel mapping** (differs from the earlier guess in item 11 — he'd had cabinets 1 and 3 backwards): channel 0/1 = cabinet 3 (drawers 19-27) left/right, 2/3 = cabinet 2 (10-18), 4/5 = cabinet 1 (1-9), 6 = cabinet 4 (28-36) **left only, intentionally no right strip**. Updated in `led-controller/pi/strip_map.json.example` and deployed to the live Pi's `/home/seth/led-controller/strip_map.json`.

Real per-drawer LED ranges captured in `inventory/management/commands/seed_led_segments.py` (`STANDARD_PATTERN` for cabinets 1-3's six strips, `CABINET4_LEFT_PATTERN` for channel 6's own measured layout) — idempotent (`update_or_create`), run with `python manage.py seed_led_segments` (add `--dry-run` to preview). **Already run against both local dev and production** — 63 `DrawerLedSegment` rows created in each.

**Two real bugs in `led-controller/pi/server.py` found and fixed while verifying this end-to-end** (both deployed to the live Pi):
1. It only bound `127.0.0.1` (IPv4). cloudflared's ingress target is the hostname `localhost`, which it can resolve to `::1` (IPv6) — an IPv4-only bind then looks exactly like "connection refused" to the tunnel even though the service is genuinely up and healthy. Symptom was oddly specific: GETs worked (hit whichever pooled connection happened to be fine), POSTs reliably failed. Fixed by binding both loopback families (two `ThreadingHTTPServer` instances, one `AF_INET` one `AF_INET6`, same `Handler`).
2. `termios.error` (raised when writing to a USB serial device that's vanished mid-session) isn't reliably a `serial.SerialException`/`OSError` subclass, so it went uncaught and crashed the request-handling thread with **no HTTP response at all** — looked like a dead/hung server from any client's perspective (and Cloudflare's edge additionally swaps *any* 5xx from the origin for its own generic error page, which is why `curl` showed a bare Cloudflare 502 with no detail even after the first fix). Broadened to catch any `Exception` in that one narrow serial-I/O boundary (deliberate, documented in the code — this is exactly the kind of place a broad except is correct: a hardware I/O boundary where any failure should uniformly degrade to "couldn't reach the Scorpio"), and now discards the cached connection object on any failure so the next request reopens fresh instead of repeatedly hitting the same broken file descriptor.

**Current hardware state:** the Scorpio is physically disconnected right now (Seth mid-installation — confirmed via `lsusb` showing no USB devices at all, not even the mouse/keyboard). Once it's reconnected, `POST /locate` should work end-to-end immediately — the mapping, seed data, and both server fixes are already live. Worth a real end-to-end test (a "Locate" click from a real drawer page) once the hardware's back, since everything so far has only been verified with the Scorpio unplugged (i.e. verified it *fails cleanly*, not yet verified it *lights something up*).

### 13. Pi 5 migration — ✅ done (2026-08-31)

Migrated everything from the Pi 4 to the new Pi 5 (`seth@192.168.1.92`, hostname `pi5` — **note: Seth first said `.192`, actual IP is `.92`**, Mac's SSH key now trusted, no more password needed). The Pi 5 image already shipped with chromium/squeekboard/swayidle/wlopm/pyserial preinstalled — only `cloudflared` needed installing. Deployed and verified: `pi-kiosk/kiosk-launch.sh` + autostart + relaunch desktop shortcut, `kiosk-helper` (systemd user service), `screen-idle` (systemd user service), `loginctl enable-linger seth`, `led-controller` (systemd **system** service, using the **real** `strip_map.json` from item 12 — not the placeholder example) with `LED_CONTROLLER_KEY` matching Hetzner's, and `cloudflared` registered with the **same** `led.sethsparts.com` tunnel token (tunnels aren't tied to hardware — no Cloudflare dashboard changes needed). **Stopped and disabled `cloudflared` on the old Pi 4** first, to avoid Cloudflare load-balancing between two different physical connectors for the same tunnel during the transition. Confirmed end-to-end: `curl https://led.sethsparts.com/health` from this Mac returns 200 with all 7 real strip names, served from the Pi 5.

**Note for whenever the Scorpio gets plugged into the Pi 5:** `/etc/led-controller/env`'s `SCORPIO_SERIAL_PORT` isn't set yet (server.py defaults to `/dev/ttyACM0`, a placeholder) — once it's connected, find the real path via `ls /dev/serial/by-id/` (will differ from the Pi 4's, new USB port) and set it explicitly, matching the Pi 4 setup pattern from item 10.

**Extra, unplanned work that came up along the way (all fixed, not just noted):**
- **NVMe boot, on Seth's request.** The Pi 5 had a 1TB NVMe drive attached but booting from the 29GB SD card. First clone attempt (`rpi-clone`) failed — that tool's NVMe partition naming is buggy on this system (referenced `/dev/nvme0n11` instead of the real `/dev/nvme0n1p1`). Redid it manually: `parted` to mirror the SD card's MBR layout (8389kB-offset 512M FAT32 boot + rest-of-disk ext4 root) scaled to the full 1TB, `mkfs`, `rsync -aHAX` both partitions (excluding pseudo-filesystems and recreating their mount-point stubs on the destination), then updated `cmdline.txt`/`fstab` PARTUUIDs to match the new partitions. Hit a **second, real hardware issue** along the way: `mkfs.ext4` failed with NVMe controller I/O timeouts/resets under sustained write load — traced to `/boot/firmware/config.txt` having `dtparap=pciex1_gen=3` (typo: `dtparam` misspelled, so it silently never applied) combined with what looks like PCIe Gen 3 signal instability on this HAT/cable. Fixed the typo and set it to `pciex1_gen=1` (conservative/stable) rather than leaving Gen 3 un-applied by accident; formatting and the full clone succeeded cleanly afterward with no further errors. Set boot order via `raspi-config nonint do_boot_order B2` (NVMe/USB before SD). Confirmed booting from `/dev/nvme0n1p2` (916GB free) across multiple reboots since. **If Seth ever wants to try bumping back to Gen 2 or 3 for more throughput, that's an experiment for him to run once the base setup is trusted-stable — I deliberately didn't chase that today.**
- **Keychain/keyring password nag on every reboot, on Seth's request.** Root cause took three tries to actually land on: (1) tried hiding the three `gnome-keyring-*` XDG autostart `.desktop` entries — didn't work, wasn't the actual trigger; (2) found and commented out `pam_gnome_keyring.so` in `/etc/pam.d/lightdm` (both already `optional`, so safe) — still didn't work, because `systemctl restart lightdm` doesn't tear down an already-autologin'd session, so PAM's session-open hooks never re-ran in my test (only a full reboot exercises them, matching how Seth actually saw it); (3) actual root cause: `org.freedesktop.secrets`/`org.gnome.keyring`/`org.freedesktop.impl.portal.Secret` are D-Bus **service-activation** files (`/usr/share/dbus-1/services/`) that auto-spawn `gnome-keyring-daemon` the moment *any* app queries the Secret Service API, independent of both autostart and PAM. `apt remove gnome-keyring` was considered and rejected — `rpd-common` (the desktop meta-package) depends on it, so removal risks cascading into other desktop components. Fixed properly via the standard override mechanism instead: three `Exec=/bin/true` service files in `~/.local/share/dbus-1/services/` (user-level, higher priority than the system dir, no root package changes). Verified clean across a fresh reboot — no `gnome-keyring-daemon` process at all now.

**LED hardware testing (2026-08-31, after the Pi 5 move) — ⏸️ paused, suspected wiring issue.** Scorpio + LEDs moved to the workshop with the Pi 5, reconnected fine (new serial path `/dev/serial/by-id/usb-Adafruit_Feather_RP2040_Scorpio_DF6254209F700C33-if02`, same physical board, `SCORPIO_SERIAL_PORT` updated in `/etc/led-controller/env` on the Pi 5). First real test — `POST /locate` for `cabinet1-left` start=0 count=10 through the live `led.sethsparts.com` tunnel — **worked**, Seth confirmed visual light-up.

Then ran a full-strip diagnostic sweep (all 7 channels, count=100, only 3s apart with the default 12s hold — in hindsight too aggressive, meaning multiple full-length strips were likely lit simultaneously) and hit real problems: strips lighting in an unexpected order, **cabinet1-left not lighting at all**, and several LEDs stuck on showing the wrong color (green). Sent explicit `clear` commands to all 7 channels directly over serial (all acknowledged `{"ok": true}`) and reran a much more conservative test (20 LEDs, 4s hold, 5.5s spacing, zero overlap between strips) — same problem persisted on a retest.

**Seth's diagnosis (his call, not something I detected in software): the power wiring uses solid-core wire, which is prone to fatigue fractures/intermittent breaks** — consistent with the symptoms (a strip not lighting at all, others glitching under higher current draw).

**Update (2026-09-01): rewired with stranded wire, retested, problem persists.** Also at this point: new touchscreen wired in via **HDMI-A-2** (was DSI before — confirmed `wlopm`/`screen-idle` picked this up automatically with zero code changes, exactly the point of not hardcoding an output name), barcode scanner dongle present (`Racal Data Group Tera 5100 dongle`, generic HID, should just work), Scorpio reconnected at the same `.../−if02` serial path. Ran the same conservative one-channel-at-a-time test (20 LEDs, 4s hold, 5.5s spacing, zero overlap) twice after the rewire — same "something still not right" result each time (Seth's words; specifics not re-confirmed against the exact original symptom list of cabinet1-left-dark + stuck-green, just re-flagged as still wrong). **Seth is now going to physically check the wiring with a multimeter** (continuity per strip, voltage under load) rather than keep software-side retesting — next step is whatever that turns up, not another blind retest. **Camera: not yet confirmed connected** — `lsusb`/`v4l2-ctl --list-devices` on the Pi 5 show no standalone USB webcam, only the SoC's own internal ISP/codec video nodes (`pispbe`, `rpi-hevc-dec`) — worth double-checking the physical connection once other hardware issues are sorted, not yet verified working.

**Old Pi 4 status:** still physically set up, `cloudflared` stopped/disabled there (so it's no longer part of the LED tunnel), kiosk-helper/screen-idle/led-controller still technically running but unused. Not decommissioned/wiped — that's Seth's call once he's confirmed the Pi 5 fully replaces it in practice (per item 11's original plan).

### 14. Wiring fixed, physical strip↔logical-name mapping confirmed via live test, bin-row animations + light controls — ✅ done (2026-09-09)

**Wiring issue from item 13 resolved** (Seth checked physically after rechecking wiring + rebooting the Pi) — a live `/locate` test firing all 7 channels in sequence, one at a time (13s apart, safely longer than the fixed hold), confirmed every strip lights cleanly. **Confirmed physical-strip-position ↔ logical-strip-name mapping** (positions numbered 1-7 right-to-left across the physical cabinets): position 1=`cabinet3-left`, 2=`cabinet3-right`, 3=`cabinet2-left`, 4=`cabinet2-right`, 5=`cabinet1-left`, 6=`cabinet1-right`, 7=`cabinet4-left` — confirmed by re-firing in an order designed to light 1→7 sequentially if the hypothesis was right, and it was. Then ran the real `/drawers/<pk>/locate-led/` app endpoint for all 36 mapped drawers (1-36; the 5-drawer cabinet #120, drawers 37-41, still has no LED mapping) in that same physical order — Seth confirmed all 36 lit correctly.

**New real per-drawer LED ranges from Seth's own measurements**, replacing the earlier placeholder guesses in `seed_led_segments.py`: `cabinet1-left`/`cabinet2-*`/`cabinet3-*` are flat 10-LEDs-per-drawer; `cabinet1-right` and `cabinet4-left` use an uneven 9/9/10/10/10/9/10/10/9 spacing (different physical strip product than the rest, per Seth). Re-run and deployed to both local and production DBs — see the command for exact values.

**New feature, built and live-tested end-to-end: bin-row-aware "locate" animation + a Light Controls page.** Each drawer is subdivided into 16 bins (4 rows of 4); `StockItem.bin_number` (1-16, optional, migration `0010_stockitem_bin_number`) captures which bin a part sits in, with a `bin_row` property (`((bin_number-1)//4)+1`). Editable inline on the part detail page's "Where it lives" table, alongside a new per-StockItem "💡 Locate" button (`locate_stock_item` view/`/stock/<pk>/locate/`) distinct from the existing per-drawer one — it passes the computed row (1-4) through to the LED controller so the animation can convey bin-level detail, not just "somewhere in this drawer."

Scorpio firmware (`code.py`) rewritten with a real per-channel animation state machine (previously just instant on/off): a locate now **breathes 3 times** (3.6s smooth 0→1→0 pulse each, tuned up from an initial single 2.4s pulse per live feedback — "breathe didn't animate very long" the first time, "perfect" after retuning), then **flashes solid `row` times** (only if a bin row was given — a plain drawer-level locate just keeps breathing), then repeats, for a **30s total** (bumped from an initial 20s, also per live feedback) before auto-clearing. Verified the exact flash-count and breathe-pulse-count logic via a local Python simulation (stubbing out `board`/`usb_cdc`/`adafruit_neopxl8`) before ever touching real hardware — caught that a naive "count brightness transitions" test metric over/undercounts near a breathe peak's flat top and at window boundaries; the actual firmware logic was correct once verified with a cleaner test.

Two new modes, mutually exclusive with locate and each other: **`room_light`** (fills every channel solid, no auto-clear, for ambient room lighting — live-tested on/off, confirmed) and **`demo`** (~15s, purely for fun/showing off). Demo mode's first version (a simultaneous rainbow gradient across all 8 channels at once) got live feedback ("i'd rather have it be a single cluster moving from strand one down then up the next") — rebuilt as a single comet with a fading tail that serpentines through the channels (down channel 0, back up channel 1, etc.), color slowly cycling as it travels; verified the serpentine direction and comet position via simulation, then live-confirmed ("perfect"). Both plus a persistent `brightness`/default-`color` setting (`set_defaults` command) are exposed on a new `/lights/` **Light Controls** page (linked in the nav as "💡 Lights") — brightness slider, default-color picker, room-light on/off with its own color picker, and a "Run demo" button. Pi controller (`led-controller/pi/server.py`) extended to relay all of this: `/locate` now accepts optional `row`/`duration_ms`/`color` overrides (default duration 30000ms, up from 12000), plus new `/room_light`, `/demo`, `/set_defaults` endpoints.

**Deploy reminder for both of these files** (per the README at the top of `led-controller/`, neither is auto-deployed by `git pull`): `scorpio-firmware/code.py` → `scp` straight to `/media/seth/CIRCUITPY/code.py` on the Pi, then `sync` — CircuitPython auto-reloads on file change, no reset needed unless `boot.py` itself changes (that needs a real hardware reset per item 3's original note). `pi/server.py` → `scp` to `/home/seth/led-controller/server.py`, then needs `sudo systemctl restart led-controller` — **I don't have and won't ask for Seth's sudo password**, so this step needs Seth to run that one line himself each time (he's done it twice now without issue). If this becomes a recurring friction point, a narrow `NOPASSWD` sudoers rule scoped to just this one `systemctl restart` command was offered but not yet set up — Seth's call.

**Still open:** cabinet 5 (drawers 37-41, container #120) has no LED mapping at all — only 8 Scorpio channels exist and 8 are already spoken for by cabinets 1-4's left/right pairs (cabinet 4 only has a left strip). Would need a second controller/Scorpio to cover it; not something to build without Seth asking.

### 15. Kiosk auto-login, layout redesign for the real screen, squeekboard fix, persistent back/home nav — ✅ done (2026-09-09/10)

**Kiosk auto-login.** The Pi kiosk was booting to a login screen instead of straight into the app. Added `kiosk_autologin` view (`inventory/views/auth.py`) — takes a long-lived shared-secret token (`KIOSK_AUTOLOGIN_TOKEN`, compared with `secrets.compare_digest`), mints a real Django session for the configured kiosk user (`KIOSK_AUTOLOGIN_USERNAME`, default `seth`) via `login()`, never touches Seth's actual account password. `kiosk-launch.sh` now points Chromium at `/kiosk-autologin/?token=...&next=/` instead of the plain site URL, so every kiosk launch (including after a Chromium profile wipe) re-establishes a session on its own. Hit one real bug: `KIOSK_AUTOLOGIN_TOKEN`/`KIOSK_AUTOLOGIN_USERNAME` were in Hetzner's `.env` but missing from `docker-compose.yml`'s `environment:` list, so the container never actually saw them (confirmed via no `Set-Cookie` at all on the response) — added both. Confirmed working end to end.

**Kiosk layout redesign.** Seth reported the layout "doesn't look great" on the kiosk screen — traced to two wrong assumptions: the CSS had a `@media (max-width: 860px)` block still sized for the *old* 800×480 DSI touchscreen (replaced back in item 13 by a 1920×1200 HDMI panel), and `pointer: coarse` doesn't reliably fire for this Pi's touch hardware either. Replaced both with sizing keyed off the existing `.pi-kiosk` runtime-detected class (see item 9) — the one signal that's actually guaranteed correct on this specific device regardless of screen swaps. Widened `main` to 1400px, enlarged buttons/nav/inputs/table cells. Also split the header nav into primary links + a "More ▾" `<details>` dropdown (too many top-level links for one row), and rebuilt the part detail page's "Where it lives" section from a cramped multi-button table into one `.location-card` per location (qty/bin fields + Locate/Remove buttons, each with room to breathe). Verified by forcing `.pi-kiosk` on and checking computed layout at the real 1920×1200 resolution before deploying (a screenshot at a small custom viewport in the dev sandbox is not trustworthy — devicePixelRatio scaling makes correct layouts look broken; check computed styles/accessibility tree, or screenshot at the real target resolution).

**Squeekboard (on-screen keyboard) not responding.** The "⌨ Keyboard" button's `POST /toggle` was reaching `kiosk-helper` fine but returning 502 — root cause: squeekboard wasn't running at all. Raspberry Pi OS's stock autostart entry (`/etc/xdg/autostart/squeekboard.desktop`) only launches squeekboard through a wrapper (`/usr/bin/sbtest`) that first checks `libinput list-devices` for a touch device — a check that loses a race against the USB touch controller's enumeration at boot on this Pi, so it silently no-ops and squeekboard never starts (confirmed: `graphical-session.target`/`xdg-desktop-autostart.target` never activate on this labwc session at all, so the OS's own generated systemd unit for it never even gets a chance to run). Fixed with a dedicated systemd **user** unit, `pi-kiosk/squeekboard/squeekboard.service` → `~/.config/systemd/user/squeekboard.service`, launching `/usr/bin/squeekboard` directly (no touch-detection needed — this kiosk always has a touchscreen) with `WAYLAND_DISPLAY=wayland-0` set explicitly (systemd user units don't inherit it otherwise), `WantedBy=default.target` — same reliable pattern already proven by `kiosk-helper.service`. Enabled + started; `/toggle` now returns 200 and actually shows/hides the keyboard. Minor cosmetic note, not fixed: squeekboard logs "gb.yaml... missing" and falls back to a US keyboard layout — this squeekboard version's package doesn't ship a UK layout resource; not blocking, worth a look only if Seth cares about the exact key layout.

**Persistent back/home navigation.** Clicking through to reference docs (cached PDFs, external product/datasheet links) left no way to get back — `--kiosk` Chromium hides all browser chrome (no address bar, no back button, no tab strip), and every outbound link across the site (reference docs, part reorder/datasheet links, attachment sources) used `target="_blank"`, so the click opened a *new* tab, leaving the original one (and any nav) unreachable. Removed `target="_blank"`/`rel="noopener"` from all of these (`reference_list.html`, `part_detail.html`, `reorder.html`, `project_detail.html`) so they navigate in the same tab and build real browser history, and added persistent "← Back" (`history.back()`) and "🏠 Home" buttons to the header, `.pi-only` like the existing Keyboard/Desktop buttons. Verified the history mechanics directly (navigate to a cached file, then back — lands cleanly on the previous page) rather than trusting click-coordinate tests in the dev sandbox, which have their own scaling quirks at non-standard viewport sizes.

### 16. Demo mode as a toggle, live color pickers, bulk bin-barcode scanning, moving-day intake — ✅ built (2026-09-10)

**Demo mode is now on/off, not timed.** Was a single "Run demo" button firing a fixed ~15s animation; now two buttons like room light ("Turn on"/"Turn off"). Firmware (`scorpio-firmware/code.py`) demo state dropped its `"end"` timestamp — `render_demo` just keeps running every loop tick until an explicit `{"cmd": "demo", "on": false}` clears it. `pi/server.py` and `led_demo` (inventory/views/lights.py) now relay `on` through instead of a duration. **Not yet deployed to the Pi/Scorpio** — `code.py` needs `scp` + `sync` (auto-reloads), `pi/server.py` needs `scp` + Seth's own `sudo systemctl restart led-controller` (same as every prior firmware/server change, per item 14).

**Color pickers apply immediately.** The default-locate-color and room-light-color `<input type=color>`s now fire `this.form.requestSubmit()` on `change` (i.e. once a color is actually picked/confirmed, not continuously while dragging) — no more separate "Save"/"Turn on" tap needed to see the new color take effect. Room light in particular: picking a new color while it's already on updates it live; picking one while it's off turns it on with that color (a deliberate direct-manipulation choice — "I picked pink" and the light responding is the whole point of a color picker here).

**Bulk bin-barcode scanning.** New `Bin` model (`drawer` FK + `bin_number` 1-16 + unique `barcode_id`) — distinct from `StockItem.bin_number`, which records which bin a *part* sits in; `Bin` is the physical-sticker-on-a-slot registry. Only drawers 1-27 (containers #38/#39/#40, cabinets 1-3) get bins — cabinet 4 (drawers 28-36) holds oversized/different items with no bin subdivisions, per Seth. `/bins/` (`bin_setup` view) auto-seeds all 432 `Bin` rows (idempotent `bulk_create`, safe to hit repeatedly) and shows per-drawer progress with a Scan/Continue link into `/bins/scan/`. That page (`bin_scan` view + template) loads the full ordered list of 432 positions as JSON up front (`json_script`), then runs entirely client-side: an autofocused text input captures a scan, `Enter` fires a `fetch` POST to `/bins/<pk>/scan/` (`api_scan_bin`), and on success the JS advances to the next position and refocuses — zero taps between scans, matching how a USB HID barcode scanner actually behaves (types the code, sends Enter). A barcode already linked to a different bin is rejected with a 409 and a named conflict ("already linked to #38 / Drawer 1 bin 1") rather than silently overwriting. Verified locally end-to-end: seeding (exactly 432 rows across the right 27 drawers in the right order), a real scan-and-advance via a simulated Enter keypress, and the duplicate-barcode rejection path.

**Moving-day intake.** Seth's about to move and will be re-boxing things into black totes for the garage — three small tools for that:
- `/intake/new-box/` (`quick_add_container`) — assigns the next container number, creates it immediately (type free-text with a datalist of existing types, default "black tote"; optional room), and redirects straight into the existing `print_labels` flow for that one barcode (reuses the same `C<number>` scheme and SVG/print pipeline as `/labels/`, nothing new there) — print it and stick it on the box before contents are even sorted out.
- New `ContainerPhoto` model + a "Photos" section on the container page, for a quick reference shot of what's inside. The camera-capture JS (get a live preview, capture a frame, upload) was previously only on the part detail page — factored it out into a shared partial (`_photo_capture.html`, parameterized by `upload_url`) and reused it for both parts and containers rather than duplicating it.
- New `IntakeNote` model (container FK, text, source `typed`/`voice`, `reviewed` flag) — a "Contents notes" section with a plain textarea plus a "🎙 Dictate" button using the browser's native `SpeechRecognition` API (interim + final results stream into the textarea live; feature-detected, so it just disables itself with an explanatory message on a browser that doesn't support it — no server-side speech-to-text integration needed). Notes save as free text, deliberately not auto-parsed into `Part`/`StockItem` rows — `/intake/queue/` lists everything unreviewed across all containers for Seth to work through later at his own pace, with a "Mark reviewed" action per note.

**Update (2026-09-10/11):** LED firmware/server changes deployed to the Pi + Scorpio and Django changes deployed to Hetzner. Demo on/off verified live end-to-end via curl against the production `/lights/demo/` endpoint through a kiosk-autologin session (turned on, confirmed it kept running well past the old ~15s cutoff, turned off, confirmed the "Demo stopped" message) — Seth visually confirmed the cabinets actually animated/went dark to match.

### 17. Browse page leads with drawers, not containers — ✅ built and deployed (2026-09-10)

Seth's day-to-day browsing is almost always "which drawer has X", not "which cabinet" — the old Browse page listed *containers* first (sorted by spreadsheet box number), so the ~41 drawers were buried inside their cabinet's card, sorted wherever that cabinet's number happened to fall among 70+ tote/box containers. Added a flat "Drawers" table at the very top of `/` (all 41, in real numeric order 1-41 via the same `_drawer_number()` regex-sort helper the bin-barcode feature already uses), each row linking straight to `drawer_detail`. The existing full container list (cabinets included, with their drawer pills) stays below under an "All locations" heading, unchanged — Seth explicitly wanted to keep that for organization, just not as the first click.

### 18. Custom label designer + Zebra GK420T print-bridge — ✅ done, verified end-to-end (2026-09-11)

**Custom label designer**, `/labels/custom/` (own top-level nav tab, "🏷 Custom label", alongside Lights — matches the "perhaps make it a separate tab" note from the original label-printing backlog item). Stateless/impromptu by design (nothing saved) — type text, optionally add a barcode value, pick one of the 3 physical label sizes Seth actually owns (4"×2" general, 2"×1" tote, 1"×0.5" barcode — see the Amazon links in the original backlog item), adjust font size, toggle bold/italic, see a live preview, hit Print. Every field auto-submits on `change` (same "no extra tap" pattern as the light-controls color pickers) so the preview updates itself.

Implementation (`inventory/label_printing.py`): rather than fighting ZPL's limited built-in fonts (no italic support at all, "bold" is a hack), the whole label is **rendered as a bitmap with Pillow** — real TTF files (DejaVu Sans regular/bold/oblique/bold-oblique, `apt-get install fonts-dejavu-core` in the Dockerfile; falls back to macOS's own Arial variants for local dev, then to PIL's built-in font as a last resort) give genuine bold/italic/size control, word-wrapping, and shrink-to-fit if the text is too long for the label. An optional barcode (reusing the existing `python-barcode` library, `ImageWriter` instead of the `SVGWriter` used elsewhere) gets composited above the text. The finished bitmap is packed into a single ZPL `^GFA` graphic-field command (ASCII hex, `^PW`/`^LL` set to the label's exact pixel dimensions at the GK420T's native 203dpi) — the Pi's print-bridge doesn't need to understand ZPL text/font semantics at all, just relay bytes. Verified locally: rendered all 3 sizes, bold, italic, the barcode+text composite on the smallest label, and the shrink-to-fit path with deliberately-too-long text — all correct on inspection. Also verified the full Django request/response cycle (preview generation, and the print action's graceful "not configured" error) via the test client and live in a browser.

**Print-bridge** (`label-printer/pi/server.py` + `label-printer.service`, mirrors `led-controller/pi/server.py`'s exact pattern): a thin stdlib HTTP relay on the Pi, `POST /print` writes the raw ZPL bytes it receives straight to `/dev/usb/lp0`, no CUPS. `LABEL_PRINTER_URL`/`LABEL_PRINTER_KEY` settings added (mirrors `LED_CONTROLLER_URL`/`KEY`) — empty by default, so Print just reports "not configured" until wired up. Files copied to `/home/seth/label-printer/` on the Pi already.

**Setup completed, all four steps done:**
1. `sudo usermod -aG lp seth` on the Pi + reboot — confirmed `seth` in the `lp` group, `/dev/usb/lp0` is `root:lp` mode 660 when the printer's connected.
2. `/etc/label-printer/env` with `LABEL_PRINTER_KEY` set, `label-printer.service` installed and running.
3. **Real gotcha found here**: the tunnel this Pi uses (`sethsparts-led-controller`) is a *remotely-managed* tunnel, but its routes don't live under the dashboard's "Hostname routes" tab (that was empty even for the already-working `led.sethsparts.com`) — they're under a 4th tab, **"Published application routes"**. Added `label.sethsparts.com` → `http://localhost:9020` there. DNS took a couple minutes to propagate to my local resolver (Cloudflare's own DoH resolver had it within seconds) — don't assume it's broken just because `host`/`dig` shows NXDOMAIN briefly right after adding a route.
4. `LABEL_PRINTER_URL=https://label.sethsparts.com` + matching `LABEL_PRINTER_KEY` added to Hetzner's `/opt/sethsparts/.env`, redeployed.

**Printer connection was flaky, now resolved.** It briefly enumerated then dropped earlier in the session (see original note below) — once Seth powered it on properly with media loaded, it enumerated cleanly and stayed up.

**First real print needed a media calibration.** Fresh 50×25mm label stock the printer had never measured before — first print landed cut-off/right-justified (printer's gap-sensor didn't know where labels started/ended). Fixed by sending a bare `~JC` ZPL calibration command through the print-bridge (printer auto-fed a couple of labels to measure the gap) — after that, a real print through the actual `/labels/custom/` page (not just a direct curl to the bridge) came out correctly centered. **This is a one-time-per-media-roll thing** — if Seth loads a different label size/stock later, expect the same "send `~JC` first" step to be needed again (worth adding a "Calibrate printer" button to the custom label page if this comes up often enough to be annoying — not built yet, hasn't been asked for).

Original note, now resolved: `lsusb`/`dmesg` on the Pi had shown the GK420T *was* detected once, then disconnected ~5 seconds later and didn't re-enumerate for a while — turned out to just be waiting on Seth to physically power it on with media loaded, not a real driver/cable fault.

### 19. Sub-bin barcoding + LED row/column position readout — ✅ done, verified live (2026-09-11)

**Sub-bins.** As Seth works through drawers 1-27 registering bin barcodes, he's finding some bins are further subdivided into 0-4 small/medium sub-containers, each with its own physical barcode. New `SubBin` model (`bin` FK, `position` 1-4, `size` small/medium, unique `barcode_id`) — deliberately *not* pre-seeded like `Bin` (there's no fixed count, added as discovered). New `/bins/<pk>/` (`bin_detail`) page ties it together: shows the bin's row/column, its stock contents (queried by `drawer`+`bin_number`, since `StockItem.bin_number` is a plain int, not an FK to `Bin`), a barcode register form, a "💡 Locate this bin" button, and the sub-bins list with per-sub-bin register/remove and an "+ Add sub-bin" form (capped at 4). `drawer_detail` now shows a 4-wide grid of its bins (✓ if barcoded, a count badge if it has sub-bins) linking into `bin_detail`; `go()` (the barcode-scan resolver) now also matches `Bin`/`SubBin` codes, same as it already did for containers/drawers.

**LED locate: row/column readout replaces the flash — final design, after 3 rounds of live correction.** Went through several iterations against the real hardware before landing on the right design:
1. First built a *centered* display on one strip (row LEDs left-of-center, column LEDs right-of-center, `row-1` count) per Seth's original worked example (bin 13 → 3 left, 1 right) — worked, but Seth found it hard to read (same-color LEDs blending together behind the frosted diffuser) and too brief.
2. Fixed readability: extended the static hold from 2s to 12s, and gave each lit LED its own distinct rainbow hue (`_hsv_to_rgb_int`, evenly spaced across however many LEDs are lit) instead of one flat color.
3. Found and fixed a real bug during this pass: odd-length segments (9 LEDs, `cabinet1-right`/`cabinet4-left`) left the true center pixel dark, which read as a "skipped" LED — folded it into the left/row group so the block is always contiguous.
4. Seth corrected the count formula: he actually wanted `row` LEDs (not `row-1`) on the left, confirmed with a second worked example (bin 7 = row 2/col 3 → 2 left, 3 right).
5. **Final correction, the actual intended design:** rather than one strip showing a combined row+column centered display, the drawer's *two separate physical strips* should each show one value — the `-left`-named strip lights `row` LEDs, the `-right`-named strip lights `col` LEDs. `_locate_drawer()` (inventory/views/lights.py) now includes `row` in the payload only for segments whose `led_strip` ends `-left`, and `col` only for `-right` — no firmware change needed for this split, since `_position_indices()` already handles either value being absent (just shows LEDs on one side of center, none on the other). Verified live against bin 13 (4 on the left strip, 1 on the right) — Seth confirmed it looks right.

Every step verified via a local Python simulation (stubbing `board`/`usb_cdc`/`adafruit_neopxl8`) before deploying to real hardware, catching the odd-segment gap bug before ever flashing it.

**Fully deployed**: Django side on Hetzner, firmware on the Scorpio (`code.py`, CircuitPython auto-reload), `led-controller/pi/server.py` restarted on the Pi.

### 20. Bulk intake entry point + in-app enrichment queue — ✅ done, deployed (2026-09-13)

**Bulk intake.** Seth noticed the intake queue had no way to actually add a note — only from a container's own page, one at a time. `IntakeNote.container` is now nullable; new `/intake/add/` (`bulk_intake`) takes a whole batch (one item per line — typed or dictated, with voice results split onto their own line at each recognized phrase boundary) and either assigns them all to a container now or leaves them unassigned. `/intake/queue/` gained an inline assign/reassign dropdown per note (`assign_intake_note_container`) for the "sort out later" path.

**Enrichment queue.** `classify_enrichment_queue` and `ingest_enrichment` (from the original Phase 3 enrichment work) already existed but were CLI-only — no in-app way to trigger them. New `/enrichment/` dashboard: status counts, a "🔍 Classify now" button (runs the classifier live — pure DB logic, no web calls, safe any time), a worklist JSON export of `pending` parts for a research pass to work from, and a results-upload that runs `ingest_enrichment` via `call_command` on the uploaded file. Verified end-to-end with the test client (classify, export, and a real import against a live Part, reverted after). **Important framing, told to Seth directly**: the actual web research (finding product pages/pinouts/datasheets/pricing) needs a live agent making real requests — nothing the deployed container can run unattended on a schedule for free. This page makes the *trigger-and-apply* halves a normal in-app action; the research step is still "ask Claude to process the exported worklist," which matches what Seth said he was fine with ("maybe just a manual trigger").

### 21. Test suite + mutation check — ✅ done (2026-09-13)

**Why this came first, ahead of any feature work.** The repo had `inventory/tests.py` as the
untouched Django stub — a single `# Create your tests here.` and nothing else. Every bit of
verification described in this log (all that "verified via the test client", "verified end-to-end",
"verified with a simulated Enter keypress") was real when it happened, but none of it was
committed, so it only ever existed in the session that did it. That's survivable with one assistant
holding continuous context across the whole project; it is the main thing that makes
handing the repo between assistants risky, because any change is then verified only by whoever
made it. So this landed before features: a committed suite, so the verification stops being
ephemeral and either assistant can change something safely.

**What's there now.** `inventory/tests/` is a package (the stub `tests.py` is deleted), one module
per area, 211 tests, running offline in ~7s with no hardware and no network:

| Module | Covers |
|---|---|
| `test_models.py` | `normalized_name` on save, BOM version numbering per-project, bin row/column for all 16 positions, `BuildConsumption.short`, `__str__` formats used in templates and LED error messages |
| `test_search.py` | Synonym expansion, whole-word-only matching, the four searchable fields, the 150-result cap, empty-query behaviour at both the helper and view level |
| `test_scan_resolution.py` | `go()` resolving container → drawer → bin → sub-bin, cross-model code collision order, not-found path, login wall |
| `test_stock_and_builds.py` | FIFO consumption ordering and spill-over, free-text quantities never decremented, short-stock honesty, build-against-latest-revision, reorder threshold boundary |
| `test_bins.py` | Eligibility (38/39/40 only), seeding idempotency, numeric drawer sorting, scan/409-conflict/400 paths, sub-bin 4-cap |
| `test_led.py` | The row-goes-left / column-goes-right split, drawer-level locate sending neither, per-strip failure isolation, all three "not configured" paths, colour/brightness normalisation |
| `test_labels.py` | All 3 physical sizes at 203dpi, bold/italic combinations, barcode compositing, shrink-to-fit, hand-checked ZPL bit-packing, unconfigured-printer path |
| `test_intake.py` | Bulk line splitting, blank/whitespace rejection, unassigned notes, source validation, quick-add numbering staying monotonic across gaps |
| `test_voice_api.py` | Every 403/400 path on the shared-secret endpoint, payload shape, 5-result cap, `quantity_raw` preferred over `quantity` |
| `test_kiosk_auth.py` | Correct token mints a real session, wrong/missing token logs nobody in, unset token rejects everything, exact-match including case |

**`scripts/mutation_check.py` — the part that actually matters.** A passing suite proves nothing on
its own; what matters is whether it fails when the code it protects is broken. The script applies
10 real mutations (reverse the FIFO consumption order, swap the LED row/column split, cut
`BINS_PER_DRAWER` to 8, drop the bin-scan conflict check, disable synonym expansion, off-by-one the
ZPL row stride, make an empty kiosk token match anything, and so on), runs the relevant tests, and
reports anything that stayed green. **Result: 10/10 caught.** Adding tests for a new area without
running this leaves you guessing whether they'd catch a regression.

**Two findings worth a human's eye — both pinned as-is, neither silently "fixed":**

1. **`build_search_query("")` returns an empty `Q()`, and `filter(Q())` matches every row.** The
   helper is a footgun: an empty query is *permissive*, not empty. Both current callers guard
   before calling (`parts_search` checks `if query:`; `api_locate_part` returns 400 on a blank `q`),
   so the shipped behaviour is correct — `/search/` with no params shows nothing, which is tested.
   But a future caller that forgets the guard leaks the whole inventory into a search result.
   Pinned both ways: the permissive helper behaviour with a FOOTGUN docstring, and the view-level
   guard that actually protects the user.
2. **Blank quantity is rejected, but blank bin number clears.** `update_stock_quantity` does
   `int(raw)`, so submitting an empty field raises `ValueError` and shows "'…' isn't a whole
   number" while leaving the old value intact; `update_stock_bin` explicitly clears to `None` on
   blank. Since `StockItem.quantity=None` is a meaningful state (the spreadsheet's "10 aprox"), not
   being able to return a quantity to unknown is arguably a gap — but it's the shipped behaviour and
   changing it alters production data handling, so it's flagged rather than altered. Seth's call.

**Also fixed along the way:** the README's local-dev steps said `cd tor-inventory` (the directory was
renamed) and `python3 -m venv venv`, which fails on any machine whose default `python3` is below
3.12 — Django 6.1 requires 3.12+. Both corrected, with a note explaining why the version matters.
Added a "Tests" section covering the conventions (behaviour contracts over snapshots; pin surprising
intentional behaviour with an explanatory docstring so a later "fix" trips the test) and a fifth step
in "Picking this up with a different AI assistant".

**Not done in *this* step (superseded immediately after — see item 22):** `inventory/views.py` was
still a single 1,465-line file with 71 view functions when this landed. That split was the intended
next job, and doing it *after* this rather than before was deliberate: it meant moving code with a
committed safety net in place instead of with nothing to catch a mistake.

**Verified:** `manage.py test inventory` → 211 tests, OK. `scripts/mutation_check.py` → baseline
PASS, 10/10 mutations caught. `manage.py check` → no issues. Nothing deployed — this is branch
`hardening/test-suite`, no production behaviour changed.

### 22. Split views.py into inventory/views/ — ✅ done (2026-09-13)

**What changed.** `inventory/views.py` (1,465 lines, 71 view functions, 2 constants) is now a
package, one module per topic. Nothing about the app's behaviour changed — this is pure
reorganisation, verified as such (see below).

| Module | Lines | Holds |
|---|---|---|
| `views/__init__.py` | 185 | Facade — re-exports all 73 names so both existing import styles keep working |
| `views/_shared.py` | 60 | `_current_stock`, `_reorder_link`, `_consume_stock`, `_slugify_drawer_code`, `_location_choices`, `_drawer_number` |
| `views/browse.py` | 185 | browse, scan, `go()`, container/drawer detail, barcode registration |
| `views/bins.py` | 218 | Bin seeding, bulk bin scanning, bin detail, sub-bins |
| `views/parts.py` | 192 | Part intake/detail, stock quantity + bin editing |
| `views/labels.py` | 148 | Label generation, printing, barcode SVGs |
| `views/intake.py` | 136 | Moving-day capture, quick box creation, dictated notes |
| `views/searching.py` | 92 | `parts_search` + the HA voice endpoint |
| `views/tagging.py` | 95 | Tagging/review worklists |
| `views/projects.py` | 100 | Projects, BOMs, builds, reorder dashboard |
| `views/enrichment.py` | 177 | Enrichment queue, export, reference docs |
| `views/lights.py` | 174 | Everything that talks to the LED controller |
| `views/auth.py` | 22 | Kiosk auto-login |

**The import paths are deliberately unchanged.** `inventory/urls.py` does `from . import views` and
calls `views.browse` etc.; the test suite does `from inventory.views import _locate_drawer`. Both
are served by `views/__init__.py`, which imports every name from its topic module. That file exists
*only* to keep those two paths stable — new views go in the topic module they belong to, not there.
So this refactor touched exactly one file (`urls.py` untouched, tests untouched).

**How it was done, and why that matters.** The split was generated by an AST script that copied each
top-level block **byte-for-byte** by line range rather than retyping anything — a hand-move of 1,465
lines is where transcription errors live. The generator hard-failed on any unassigned block. It then
computed each module's imports from what that module's code actually resolves.

**Three real bugs the generator hit, all worth remembering if this is ever repeated:**

1. **The import header leaked into the first function of every module.** Import nodes were skipped
   without advancing the "last block ended at" cursor, so the first block's line range started at
   line 1 and swallowed the whole 36-line header. Symptom: a stray duplicate
   `from .models import (…)` in every module. *My first verification missed this* because it
   re-derived line numbers from the generated file, inheriting the same blind spot — the fix was to
   add an explicit "nothing but a docstring and imports may precede the first def" check.
2. **`django.db.models` also ends with `"models"`.** The test for "this is the app's models import"
   matched it too, so `Count/Max/Q/Sum` were silently dropped from the import pool — which only
   *appeared* to work because bug 1 was accidentally supplying them via the leaked header. Fixed by
   requiring a relative import (`node.level >= 1 and module == "models"`).
3. **Relative imports need one more dot inside the package.** `from .skills import …`-style lines
   (`from .search import build_search_query`) silently became `inventory.views.search`, which is a
   different module that doesn't exist. Now rewritten to add a dot per level.

Plus one subtler one: the first version detected needed imports by scanning AST `Name` nodes, which
cannot tell a global reference from a **local variable that shares the name**. `_tagging_location_choices`
has a local `labels = {}`, so it grew a spurious `from .labels import labels` — harmless today (the
local shadows it) but exactly the kind of thing that becomes a circular import later. Replaced with
`symtable`, which resolves scope properly; specifically, only `is_global()` counts, because a `free`
variable is bound by an *enclosing function* (the genexpr inside that same function sees `labels` as
free), not at module scope.

**Verified — this is a refactor, so the bar is "provably identical behaviour":**

- **Structural:** all 73 top-level blocks present in the package, **0 bodies differing**, every
  original body found verbatim in the generated source. No statement other than a docstring or an
  import precedes the first `def` in any module. No duplicate imports.
- **Import surface:** `len(views.__all__) == 73`, no duplicate exports, package imports cleanly.
- **Behaviour:** `manage.py check` → no issues. **`manage.py test inventory` → 211 tests, OK.**
- **`scripts/mutation_check.py` → 10/10 mutations caught**, with anchors repointed at the new module
  files. That last one is the real proof for a refactor: each mutation now breaks a *different file*
  than it used to (the FIFO order in `views/_shared.py`, the LED split in `views/lights.py`, the
  kiosk token in `views/auth.py`) and the same tests still catch them — so the logic genuinely moved
  intact rather than being quietly dropped.
- `mutation_check.py` also reports `anchor not found` if logic moves, which is intentional: it
  doubles as a tripwire for future refactors.

**Deploy reminder:** nothing here changes behaviour, but the production checkout is still on
`a7903aa` (3 doc-only commits behind `main`) — a deploy would also pick up items 20–22.

### 23. Community sharing — data model, instance identity, pin signing — ✅ foundation built (2026-09-13)

First slice of the cross-instance feature planned in `docs/PLAN_community_sharing.md`. This is the
**model layer only** — no views, no URLs, no UI yet — because the model is the part that is expensive
to change once Seth's and his dad's instances hold real data.

**What exists now** (migration `0014_communityidentity_communityprofile_peer_and_more`):

- `CommunityIdentity` — this instance's Ed25519 keypair, singleton, generated on first use. The public
  half is the instance's stable identity on the network.
- `CommunityProfile` — whether this instance appears on maps, plus an approximate location.
- `Peer` — another workshop's instance, with the credentials for talking to it.
- `PairingCode` — one-time, 24-hour invite codes.
- `PeerSearchLog` — an audit log of what each peer has searched.
- `Category.is_shareable` — per-category opt-in, default off.

**The decision that shaped everything else: three separate permissions.** Whether an instance appears
on the map (`CommunityProfile.discoverable`), whether a given workshop can *search its parts*
(`Peer.shares_parts`, default **off**), and whether a given workshop *exchanges map pins* with it
(`Peer.exchanges_pins`, default **on**) are independent. Collapsing any two would mean connecting for
pins — which is exactly what the default seed connection does — silently handing over inventory
access. The two per-peer flags are flags rather than a type so that the same person can be a pin
neighbour without being a search peer.

**Location is postcode-AREA only.** UK outcode or US ZIP centroid; a full UK postcode identifies
roughly fifteen households, so publishing one publishes a doorstep. The geocoder returns the centroid
directly, which is why there is no rounding or grid-snapping anywhere in this feature. Note what is
*not* stored: the postcode the owner typed. Keeping it would mean a serialisation mistake could leak
it, and nothing needs it once the centroid exists.

**Why Ed25519, and not a shared secret or a chain.** A pin is relayed between instances that have
never met, so it must be verifiable by a node that does not hold the publisher's secret — which rules
out HMAC. A chain adds consensus and, decisively, immutability: an append-only ledger cannot honour
the erasure the rest of this feature promises (§5.2, §7 of the plan). Signatures plus timestamps give
authentication and freshness, which is all the map needs.

**Bug found and fixed while testing.** `v` (the pin format version) was in the pin dict but *not* in
the signed bytes — `canonical_pin` always signed the module constant. A relaying instance could
therefore relabel a pin in transit and the signature would still verify, meaning the pin's own
statement about its format was the one field nothing checked. `canonical_pin` now takes the version as
a parameter, and `verify_pin` passes the version the pin claims *and* refuses versions it does not
know. Both halves are needed: the first stops relabelling, the second stops guesswork. See
`test_the_version_is_inside_the_signed_bytes` and
`test_a_correctly_signed_pin_from_a_future_version_is_still_rejected`.

**Verified:**

- `manage.py check` → no issues.
- **`manage.py test inventory` → 280 tests, OK** (was 211; +69 across `test_community_crypto.py` and
  `test_community_models.py`). `test_community_crypto.py` is a `SimpleTestCase` — the signing rules are
  plain functions with no database access, so they are tested exactly rather than through a view.
- **`scripts/mutation_check.py` → 24/24 mutations caught** (was 10/10). The 14 new mutations target the
  privacy defaults — flipping `shares_parts`, `is_shareable` or `discoverable` to `True` by default —
  and the signing rules, including the version bug above. Flipping any of those defaults now fails the
  suite loudly, which is the point: they are the feature's promises, not implementation details.
- Private-key handling asserted three ways: it never appears in `__str__`, never in `repr`, and is
  absent from `CommunityIdentityAdmin.fields` — so it cannot be read back out through the admin.
- `cryptography==50.0.1` added to `requirements.txt`. It installs from wheels on both macOS and Linux,
  so the Pi and the Docker image need no compiler.

**Not built yet:** pairing views/URLs/UI, the location geocoder, the noticeboard service, pin
publishing and sync, the map page. Next slice is pairing.

### 24. Making it releasable: portability, a setup wizard, and a library you own — ✅ built (2026-09-13)

A long session whose single goal was: **this should be something other people can run**,
not just Seth's install. Six pieces, each committed and verified separately.

**Portability.** Audited the app for anything that ties it to one operating system, and
found it portable by construction already — no POSIX-only imports, no Unix process
APIs, no shell-outs, and all hardware reached over HTTP through settings that default
to empty. The hardware code is correctly quarantined in `pi-kiosk/`,
`led-controller/pi/` and `label-printer/pi/`. Four things did block a Windows user:
gunicorn (needs `fork()`; `waitress` added behind a `sys_platform == "win32"` marker),
four file reads with no explicit encoding (Windows defaults to cp1252, and the data
involved is `µ`, `Ω` and `×`), no Windows font in the label renderer, and a
leaked-handle `json.load(open(...))` that the new guard caught rather than the manual
audit. `inventory/tests/test_portability.py` now enforces all of it by reading the
source, because a rule nobody runs is a rule that erodes.

**Site settings, and everything that was hardcoded to Seth.** The app called itself
"Seth's Parts" in 27 templates, used `Europe/London` for every timestamp, and had
exactly one unit for quantities. `SiteSettings` is now a row holding the owner's
answers — name, timezone, country, unit system, hardware addresses — and the same
pages are both the first-run wizard and the settings pages, because a wizard you can
only run once is a wizard people work around. A timezone middleware renders every
timestamp in the owner's zone; that was a real bug for a US install, not a nicety.

**Units.** `Part.default_unit` and `StockItem.unit`, blank meaning *inherit*. `each` is
the default and renders as a bare number, so all 1,379 production rows display exactly
as they did. Deliberately not a conversion layer: converting would silently rewrite
numbers somebody counted by hand.

**The reference library is now the owner's.** Categories were a hardcoded choices
list, so you could add a document but never the shelf it belonged on. They are rows
now, with full editing — rename, reorder, add, delete — and documents get the same.
Deleting a shelf with documents on it is refused rather than cascading. Migration 0018
converts the column to a foreign key on live rows; it also gives the old column a
default before dropping it, without which **reversing the migration fails** with a NOT
NULL constraint, because the column gets re-added to a table that already has
documents in it. Both directions verified against a seeded database.

**Documents are archived locally.** Datasheets rot, so a link is not a document. When
a link is added the app fetches a copy and serves that; the URL stays as provenance.
It refuses non-http schemes, caps size so one bad URL cannot fill the disk, and
records *why* a fetch failed — a document behind a login wall stays as a link that
says so. A failed refresh never discards an earlier good copy. Repurchase links are
deliberately excluded: a cached product page shows a stale price.

**Setup wizard, help, geocoding, update check.** The wizard covers the account (the
only unauthenticated write in the app, and it 404s on both GET and POST once an account
exists), name and place, lights, printer, reference library, community opt-in and
public address. Six help pages, including how to lay out a workshop — advice that
earns its place because the app will happily let you put everything in one drawer.
Geocoding reduces even a full postcode to its **district** before storing anything.
The update check reads GitHub releases, is off-switchable, caches for a day, and makes
**no request during a page render** — a settings page that phones home on every load
is a surprise, and it would fail offline.

**Verified end to end:** `manage.py test inventory` → **581 tests OK** (was 211 at the
start of the day). `scripts/mutation_check.py` → **47/47 mutations caught** (was 10/10),
each new mutation targeting a real decision: the privacy defaults, the pin-signing
rules, the setup gate, the archive guards, the account step, and the pairing
credentials. Every migration was exercised against a real database with rows in it,
forward and back.

**Still to do:**
- **Printer driver layer.** The settings page offers Zebra / Brother QL / Dymo / CUPS,
  but only the ZPL renderer is implemented and only ZPL has been tested against real
  hardware. `SiteSettings.label_driver` is stored and read; the drivers behind it are
  the next piece of work.
- ~~**Pushing LED config to the Pi.**~~ **Done — see item 25.** The wizard now records
  each strip's channel and pushes the map to a new `POST /strips` endpoint on the
  controller, so `strip_map.json` no longer has to be edited on the Pi by hand.
- **Community pins and the map.** Pairing works end to end (short code, handshake,
  revocation, search log). Publishing signed pins, exchanging them with peers, and the
  MapLibre/OpenFreeMap map page are designed (`docs/PLAN_community_sharing.md`) and not
  yet built. `inventory/community.py` has the signing core, tested.
- **A first release tag.** `inventory/version.py` says `0.1.0` and nothing has been
  tagged in git, so the update check compares against nothing. Tag a release before
  telling anyone about the update check.

### 25. The app's own login page, and the LED strip map pushed to the Pi — ✅ done (2026-09-13)

Two pieces of work, both committed locally on top of `12172b4`. **Not pushed, not
deployed** — production is unchanged at `12172b4`.

**The login page.** The app had no login of its own: `LOGIN_URL` was `/admin/login/`,
so the first thing anyone landing on a fresh install saw was a Django admin page, and
`/login/` — the address a person actually types — was a 404. That is the wrong front
door for something other people are meant to clone and run, which is where item 24's
release work is heading (and it's the thing worth fixing before the repo is ever made
public).

The fix is deliberately small. `AppLoginView`/`AppLogoutView` are subclasses of
Django's own `LoginView`/`LogoutView`, so credential checking, session handling and the
`next`-URL safety are unchanged library code rather than hand-rolled. What's new: the
page belongs to the app (`inventory/templates/inventory/login.html`, styled from the
app's own stylesheet, no admin chrome), it lives at `/login/`, and `/logout/` exists at
all — there was previously **no way to sign out anywhere in the app**. The admin keeps
`/admin/login/`, untouched.

Two things found while verifying, both worth remembering:

- **Django's `LoginView` puts `site_name` into the template context itself**, from
  `get_current_site()`. Without `django.contrib.sites` that is a `RequestSite`, whose
  `.name` is the bare host — so the page greeted the owner with `sethsparts.com`
  instead of the name they chose, silently overriding the context processor.
  `AppLoginView.get_context_data` puts the owner's own name back; there's a test.
- **The onboarding redirect deliberately does NOT exempt `/login/`**, though it does
  exempt `/admin/login/`. On an install with no account there is nothing to log in
  with, and the wizard is where that account gets created, so sending a visitor there
  is the more useful of the two. That reasoning is now a comment in `middleware.py`,
  so the asymmetry doesn't read as an oversight.

**The LED strip map** — the in-flight work item 24 left open, now finished and
committed as `d413343`. The wizard records which controller output each strip is
plugged into and pushes it to a new `POST /strips` endpoint on the Pi, which validates
the range and writes `strip_map.json` atomically. Three quiet failure modes are handled
on purpose: a blank channel box clears the channel rather than saving `0` (channel 0 is
a real output), unwired strips are left out of the push rather than sent as nulls, and
a 404 from the controller is explained as "the Pi is running older code" with the fix.
`LedStrip.channel` is nullable so "named but not plugged in yet" is representable.

**Verified:** 635 tests OK (+18 from 617), including a new
`inventory/tests/test_login.py`; five new mutations (58 total) aimed at the decisions
that make the login real rather than cosmetic — `LOGIN_URL` reverting to the admin's,
the template falling back to the admin's, a signed-in visitor being shown the form
again, logout landing on the admin login, and `/login/` being exempted from the
onboarding redirect. The whole flow was also walked by hand against a live `runserver`
on a throwaway database: CSRF token issued, a wrong password re-renders with an error
and no session, the right password 302s to `/`, the navigation carries a logout form,
`GET /logout/` is 405, `POST /logout/` 302s to `/login/`, and `/` afterwards 302s to
`/login/?next=/`. Migration `0023` (LED) was exercised against a real database with
1,379 stock rows in it: forward from `0013`, back to `0022`, forward again, row counts
unchanged.

### 26. A printer driver layer, and the first release tag — ✅ done (2026-09-13)

**The driver layer.** `SiteSettings.label_driver` had four choices and one implementation:
only ZPL existed, only ZPL had been near hardware, and the resolution was hardcoded to the
GK420T's 203dpi. The settings page offered Brother QL, Dymo and CUPS anyway, which is the
kind of claim that turns into a stranger's bug report.

New `inventory/label_drivers.py` holds one class per printer language, each with its own
bytes, its own default resolution, its own print-head width, and — the part that matters
most — a `tested` flag:

| Driver | Bytes | Default | Tested on real hardware? |
|---|---|---|---|
| Zebra / ZPL | `^GFA` graphic field | 203 | **Yes** — a GK420T, which is every label this app has printed |
| Brother QL | QL raster commands (`ESC i a`, `g` lines) | 300 | No |
| Dymo LabelWriter | `SYN` raster lines | 203 | No |
| CUPS | PNG handed to `lp` | 300 | No |

The two untested encoders are written from the manufacturers' own command references, cited
in the module and in `label-printer/README.md`, and **the UI now says so**: the settings page
and the custom-label page name the driver and state plainly whether anything has ever tried
it. That honesty is the feature — a driver that silently produces plausible-looking bytes
for a printer nobody here owns is worse than no driver at all.

`label_printing.py` keeps the rendering (shared by every printer) and gained a configurable
resolution: `SiteSettings.label_dpi`, blank meaning "the resolution that goes with the
printer type". That exists because printer families span resolutions — a GK420T is 203dpi and
the 300dpi model is otherwise the same machine — and rendering at the wrong one gives a label
of the right shape and the wrong size.

**Print heads are fixed widths**, so a 4" label is 812 dots at 203dpi and cannot go on a Dymo
(448) or a Brother QL (696) at all. Rather than sending it and letting the printer clip it
silently, `print_label` refuses with a message naming both numbers, and the settings page
shows a fits/doesn't-fit verdict for each label size.

**The bridge** (`label-printer/pi/server.py`) now looks at the content type: printer bytes go
straight to the raw USB device node as before, a PNG goes to CUPS via `lp`, and anything else
is refused with a **415** rather than written to a printer as binary noise. `/health` reports
whether the device and CUPS are actually available, so "printer unplugged" and "CUPS isn't
installed" stop looking identical.

**Verified:** 687 tests OK (was 635). The new `inventory/tests/test_label_drivers.py` pins
the byte layouts the manuals specify — line widths, bit order, the media declaration, the
print-area offset — which is the most a machine that isn't holding the printer can do, and it
gives whoever first tries a Brother or a Dymo a single place to compare against. Seven new
mutations (65 total, all caught) cover the silent failures: ignoring the saved resolution,
sending an over-wide label, crashing instead of falling back to ZPL, mirroring the raster
bits, shortening a raster line, writing a PNG to the raw device, and storing a nonsense
resolution. Migration `0024` was exercised against the real database (1,379 stock rows):
forward, back, forward.

**The first release tag.** `v0.1.0` tags this commit. Until now `inventory/version.py` said
`0.1.0` and nothing in git was tagged, so the update check compared against nothing at all —
anyone pressing the button would have been told "no releases or tags published yet". The tag
is **local only**; neither it nor tonight's commits have been pushed.

Worth being precise about what that does and does not fix: `updates.py` asks **GitHub**
(`releases/latest`, then `tags`), so a tag that has never been pushed is invisible to the
very thing it exists to fix. Cutting it was the right first step, but the update check only
starts working when the tag reaches GitHub — `git push origin v0.1.0` — and that is a push,
so it waits for Seth.

**A bug found in the mutation tool itself, worth knowing about.** `scripts/mutation_check.py`
restored each file it mutated — but restoring the *content* is not enough. Python decides
whether cached bytecode is current by comparing the source file's mtime at one-second
resolution, so a restore landing in the same second as the mutation leaves the *mutated*
`.pyc` on disk; the next test run loads it and fails against a tree that is perfectly clean.
That is exactly what happened here and it cost a confusing detour through a green-to-red
suite. The script now deletes the module's cached bytecode after each restore.

The symptom, if you ever see it again: the suite fails immediately after a mutation run that
reported all caught, and the failing assertion contradicts what the source plainly says.
`find . -name "*.pyc" -not -path "./venv/*" -exec rm -f {} +` clears it. (macOS `find` has no
`-newermt`, so filtering by age silently matches nothing — delete them all.)

**Not done on purpose:** pushing and deploying. Production is still `12172b4`.

### 27. Community pins and the map — ✅ built (2026-09-13)

The last piece of the community feature, and the one it started from: workshops that opt in
appear as anonymous pins, pins travel between connected instances, and opting out deletes
them.

**The pin format went to v2 to make removal possible.** A pin now carries `gone`, and a
removal is a *newer signed entry* rather than the absence of one. The subtlety that drove
the design: **a removal signs no coordinates at all.** The first version of this signed the
coordinates exactly as a pin does — which meant a node could only pass a removal on while
still holding the location it had just deleted, so every holder would have had to keep the
data it agreed to destroy in order for the deletion to spread. A test caught it (a re-served
removal failed its own signature), and the rule that came out of it is the right one: a
removal is a statement about a key, not about a place. `PIN_VERSION` is 2 because the
payload shape changed and the version is inside the signed bytes; the old format is refused
rather than guessed at.

**The opt-out deletes, and what remains holds nothing.** Deleting the row outright would
have been the obvious implementation and it is wrong: the next stale copy of the old pin,
relayed by someone who had not heard about the removal, would resurrect a workshop that had
asked to be forgotten. So the location is cleared to NULL and what remains is the key, its
newest signed timestamp, the signature and a boolean. The load-bearing test in
`test_community_pins.py` relays a week-old copy of a removed pin and asserts the map still
shows nothing.

**Opting out is pushed, not waited for.** Turning discoverability off publishes the removal
to every pin-exchanging connection immediately, best effort — a peer being offline must not
stop the owner switching their own pin off, and every change re-sends the whole statement
anyway. It is sent only when the answer actually changed, because re-pushing an unchanged
pin on every Save would be noise (and a settings page that quietly talks to peers each time
is a surprise).

**Gossip is bounded and the origin is never named.** Entries carry a hop count that each
receiver increments, so a relay cannot under-report it to defeat the limit; entries at the
limit are not forwarded; entries nobody refreshes expire after 180 days. Which neighbour a
pin came from is *not stored at all* — the plan forbids disclosing it, and not holding it is
the strongest version of that.

**The map page makes no requests.** Pins arrive from a button or from
`manage.py sync_community_pins` (cron-able). A page render that quietly contacts several
strangers' servers would be a surprise, would fail offline, and would announce this
instance's interest to everyone it knows — the same reasoning as the update check. MapLibre
GL is **vendored** into `inventory/static/inventory/vendor/` rather than loaded from a CDN,
and the tile style is a setting (`COMMUNITY_MAP_STYLE`) defaulting to OpenFreeMap's dark
style: no API key, no account, no cookies, and self-hostable.

**A peer's name is shown only if you already know them.** The pin an owner publishes stays
anonymous even when they set a display name, because a pin is gossiped network-wide and that
name only ever went to the people they told. The map labels a pin by matching its key
against the connections list, and escapes the name, because it arrived over the network from
someone else's server.

**Verified:** 757 tests OK (was 687). The peer endpoint is authenticated with the
per-connection key using `secrets.compare_digest`; it refuses a revoked connection and
refuses a connection that does not exchange pins, and there are tests for all three. Nine
new mutations (74 total, all caught) break the things that would otherwise fail quietly:
skipping signature verification, dropping newest-wins, storing a removal as a live pin,
ignoring the hop limit, letting a non-pin connection read the map, honouring a revoked key,
publishing the owner's name to the network, publishing the pin instead of the removal when
opting out, and never telling anyone about the change at all. Migration `0025` was exercised
against the real database (1,379 stock rows): forward, back, forward.

**Not built, deliberately:** connect requests between strangers (plan §8.4) need the
noticeboard relay, and the noticeboard is optional by design — the gossip network covers
people who are already connected, which is the case that matters for Seth and his dad.

### 28. Seth read it: a comment rendering on the page, and a README that had drifted — ✅ done (2026-09-13)

Both found by Seth, both by looking at the thing rather than by running the tests.

**A template comment was rendering as text.** Django's `{# ... #}` is a *single-line*
comment; across lines the template engine does not see a comment at all, it sees text — so
`base.html`'s note about the logout form appeared at the bottom of the More menu with its
braces attached. Twice, in fact: `community/map.html` had the same mistake in the head of
the map page. I had already fixed a third instance in `login.html` earlier the same night
and never looked for the others, which is the actual lesson — so the fix is
`inventory/tests/test_templates.py`, which scans every template for a `{#` that does not
close on its own line, and separately compiles every template (a tag typo is a 500 on
whichever page uses it, whenever that page is next visited). There is a mutation for the
first check, so it has to keep working: 75 mutations, 75 caught.

**The README described an app that no longer exists.** Most of it was right; the parts that
had drifted were the parts nobody re-reads. "A second instance isn't built yet" predated
the whole community feature; the label printer was still "relays raw ZPL to a Zebra
GK420T" after it became a four-driver layer; the view list was missing four modules; the
test counts were from two rounds of work ago; and several built features were not mentioned
at all (the setup wizard, in-app help, the update check, kiosk mode, the Home Assistant
endpoint, the reference library). Fixed, plus the deploy steps — which were missing the
database backup, now load-bearing because the container migrates on every start — and a new
"Migrations" section documenting the exercise-it-against-real-data rule. The "current live
state" block at the top of this file had the same drift and was refreshed with it.

Worth noting for whoever picks this up: the docs are the only part of this repo with no
test behind them, so they are the part that rots. Three of tonight's entries exist because
somebody read something instead of running something.

### Backlog / discussed, not built

- **Guided install for a clone deployment (Seth's dad).** Explicitly deferred — "not at this moment... when we are finished." Eventual goal: clone this repo for someone else's workshop (different LED array, possibly different label printer, same drawer/row/bin structure), with a guided setup covering rebranding (app name/URL), flashing the Scorpio, and — the biggest architectural difference — running fully locally on that person's own Pi instead of an externally-hosted server like Seth's Hetzner setup. Revisit once Seth considers his own instance "complete."
- **Cross-instance community part search.** Seth's idea: opt-in search across other self-hosted instances' inventories (share-code gated), so if he doesn't have a part he can see if a community member does, then coordinate pickup directly — no payments, no in-app messaging beyond "here's how to reach them." Full planning doc written: **`docs/PLAN_community_search.md`** — a private friends-list model (not a public directory), category-level opt-in sharing, a thin machine-to-machine search endpoint peers call into each other, and a separate `/network-search/` page (kept explicitly apart from the main `/search/` so Seth's own results never get diluted with other people's inventory). Deliberately not built yet — Seth wants to see another AI assistant's attempt at implementing it against that spec before it's reviewed/merged.

## Files Seth has shared, still relevant

- `/Users/seth/Downloads/amazon_order_history.xlsx` — for backlog item 6, later.
- `docs/parts_review.xlsx` (in this repo) — living document, regenerate via the merge flow whenever Seth sends back an updated copy.
