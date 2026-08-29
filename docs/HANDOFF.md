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
- **Parts-review workbook:** `docs/parts_review.xlsx`, regenerated via `scripts/export_parts_review.py --merge <path-to-prior-export>` — this merges in whatever Seth already typed into the "fill in" columns by Part ID, so re-running never clobbers his progress. He's still actively working through it.

## Backlog — requested this session, not yet built

Seth said explicitly: finish "the site" work below before the Raspberry Pi phase; hold the Amazon-matching pass until he finishes his spreadsheet edits; the dad-sharing item has no action yet, just keep it in mind.

### 1. Label printing (Zebra GK420T) — do this first, it's clearly scoped
Seth owns a Zebra GK420T thermal label printer and 3 label sizes, bought from these Amazon listings (fetch each for exact label dimensions before building anything — don't guess):
1. https://www.amazon.com/dp/B0888DMQ3Q
2. https://www.amazon.com/dp/B09S9V5LQZ
3. https://www.amazon.com/dp/B01GJGC2OK

Two label types needed:
- **Big-number labels** — for totes/custom storage, just a large easily-visible number.
- **Barcode + text labels** — for containers/drawers, barcode plus an abbreviated text description (e.g. "Container 1 Drawer 5"). Design/format is left to me.

Also wants an **impromptu label** option — print an ad hoc label on the spot, not tied to any existing container/drawer.

Proposed home: a new top-level nav tab (Seth said "perhaps make it a separate tab", design otherwise open).

**Open question to resolve before building:** how is the GK420T actually connected — USB to a specific machine, or does it have network/serial capability? The site runs on a remote Hetzner server; if the printer is USB-only on Seth's local machine, "print from the platform" needs either (a) generate a ZPL file the browser downloads and Seth sends to the printer via his own OS print dialog, or (b) a small local print-bridge/agent on whatever machine the printer is plugged into that polls the site or receives pushed jobs. Don't assume — ask Seth how the printer is connected, or investigate once we're in the Raspberry Pi phase (see item 8) since that Pi may end up being the printer's host.

### 2. Voice search via Alexa + Home Assistant
Seth has Echo devices already connected to his own Home Assistant setup. Wants: ask a question by voice, get back which drawer/container has the part.

Needs, at minimum: a search API endpoint in Seth's Parts (reuse the existing `inventory/search.py` synonym-matching logic) that takes a query and returns a location summary, callable from Home Assistant (e.g. a `rest_command` + intent script, or HA's Assist/conversation pipeline — **ask Seth exactly how his Echo devices talk to HA today** — native Alexa Smart Home skill vs. HA Voice/Assist satellites vs. something else — before designing the integration, since the mechanism differs a lot).

### 3. LED "find the part" indicator strips — explicitly deferred to the Raspberry Pi phase (item 8)
Individually-addressable LED strips already run horizontally above/below each drawer, across the outside of the cabinets. Seth wants a controller (Arduino or Raspberry Pi) that can light up the LEDs at a specific drawer's position, triggered either from a browser search or the voice search above. No LED strip protocol/model or per-cabinet LED count given yet — ask before building. Don't start this until the Pi hardware phase per Seth's own sequencing.

### 4. Intake / add-product form
A streamlined manual add-part flow. Must be reachable directly from a container/drawer detail page (so opening drawer #30 lets you start adding to that location immediately, pre-filled). Optional fields: datasheet links, product description, specs, reorder info — not all required, keep it fast to fill in for a quick add.

### 5. New "Tagging" section
A dedicated, login-gated site section for going drawer-by-drawer through the `needs_clarification`/`needs_review` Part queues as a table Seth can just work through directly in the browser — meant to reduce or replace the spreadsheet round-trip over time. Seth called it "Tagging." No detailed UI spec given — design is open, but it should let him: see one drawer's ambiguous items at a time (or filter/search across all), and fill in an answer (what it is / correct URL) that writes back to the `Part` record directly (i.e. skip the spreadsheet-export/reimport round trip for this data going forward).

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

## Files Seth has shared, still relevant

- `/Users/seth/Downloads/amazon_order_history.xlsx` — for backlog item 6, later.
- `docs/parts_review.xlsx` (in this repo) — living document, regenerate via the merge flow whenever Seth sends back an updated copy.
