# Seth's Parts — handoff / continuation notes

Read this first in a new session. Full build history (Phases 1-6, architecture decisions, verification steps) lives at `/Users/seth/.claude/plans/luminous-enchanting-kernighan.md` on Seth's Mac — this doc is the forward-looking backlog plus current live-state facts, not a repeat of that history.

## Current live state

- **Live site:** https://sethsparts.com (Django + SQLite, Docker, Cloudflare Tunnel — no nginx/Caddy, matches the pattern of Seth's other two Hetzner apps, content-hub and Mollie's black book).
- **Server:** `root@95.217.21.132` (Hetzner, hostname `content-hub`), app at `/opt/sethsparts`. My Mac's SSH key (`seth@mac-studio-hermes`) is already trusted there.
- **Deploy flow:** `git push` from `~/tor-inventory` → on the server: `cd /opt/sethsparts && git pull && docker compose up -d --build`. The server has its own **read-only** deploy key (`.deploy_key` in that dir, gitignored) — separate from my push key.
- **GitHub:** private repo `sethmills/sethsparts`, `main` branch.
- **Secrets:** live only in `/opt/sethsparts/.env` on the server (`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `TUNNEL_TOKEN`) — never committed.
- **Cloudflare:** Seth has an API token scoped to `Account.Cloudflare Tunnel:Edit` + `Zone.DNS:Edit` for sethsparts.com only — ask him for it again if needed (session-scoped, not saved anywhere persistent by me).
- **Admin login:** username `seth`, password was set by Seth directly (not recorded here).
- **Drawer numbering (just changed this session):** the 3 original parts-cabinet containers (#38/#39/#40) now have drawers labeled "Drawer 1"–"Drawer 27" (was "drawer a1".."drawer c9") — a=1-9, b=10-18, c=19-27. Two new cabinet containers were added: #119 "Cabinet 4" (9 drawers, 28-36) and #120 "Cabinet 5" (5 drawers, 37-41). See `inventory/management/commands/renumber_drawers.py` — already run against both local and live DBs, don't re-run.
- **Pi kiosk display:** the same Pi (`sethsparts` / `192.168.1.227`) that hosts the LED controller also boots straight into a kiosk Chromium pointed at `https://sethsparts.com` — desktop autologin was already configured (`autologin-user=seth` in `/etc/lightdm/lightdm.conf`, session `rpd-labwc`); added `~/.config/autostart/sethsparts-kiosk.desktop` (the correct place for this — Raspberry Pi OS's default `/etc/xdg/labwc/autostart` runs `lxsession-xdg-autostart`, which is what actually processes `~/.config/autostart/*.desktop`; a per-user `~/.config/labwc/autostart` would have fully *replaced* the system one instead of extending it, losing the panel/wallpaper — avoided that). The autostart entry runs `~/.config/kiosk-launch.sh`, which waits (up to 30s) for the site to actually respond before launching Chromium, so it doesn't race Wi-Fi coming up on boot. Chromium uses its own persistent profile at `~/.config/chromium-kiosk` so cookies (i.e. the login session) survive reboots. To make that actually stick, `SESSION_COOKIE_AGE` in `config/settings.py` is now 1 year (was Django's 2-week default) and `SESSION_EXPIRE_AT_BROWSER_CLOSE = False` is explicit — deployed to Hetzner already. **Seth still needs to log in once** on the kiosk screen itself (Claude won't/shouldn't ever type his password) — after that one login it should stay logged in indefinitely.
- **Parts-review workbook:** `docs/parts_review.xlsx`, regenerated via `scripts/export_parts_review.py --merge <path-to-prior-export>` — this merges in whatever Seth already typed into the "fill in" columns by Part ID, so re-running never clobbers his progress. He's still actively working through it.

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

## Files Seth has shared, still relevant

- `/Users/seth/Downloads/amazon_order_history.xlsx` — for backlog item 6, later.
- `docs/parts_review.xlsx` (in this repo) — living document, regenerate via the merge flow whenever Seth sends back an updated copy.
