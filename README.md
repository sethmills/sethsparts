# Seth's Parts

A self-hosted inventory system for a home workshop — parts, tools, and general
storage — originally imported from a spreadsheet, now a full Django app with
barcode scanning, BOM/build tracking, LED "find the part" cabinet indicators,
label printing, and more. Live at **sethsparts.com**.

This file is the orientation point for picking the project back up, whether
that's you or a different AI coding assistant. **Read `docs/HANDOFF.md` next**
— it's a continuously-updated running log of exactly what's built, what's in
progress, and what's next, in the order it happened. This README covers the
stable "how the project is put together" facts that don't change session to
session; HANDOFF.md covers the "what's true right now" facts that do.

## What this actually is

Seth catalogued his workshop (electronics parts cabinets, storage totes,
general tools) into this app so he can scan a barcode on a drawer/tote and see
what's in it, get low-stock alerts, plan builds against a bill of materials,
and — because the electronics cabinet drawers are further subdivided into 16
bins each — get a physical LED indicator lighting up exactly which drawer
(and which bin within it) has the part he's looking for.

It's built to run as one person's private, self-hosted tool — not a SaaS
product. A second instance for someone else's workshop is a real goal (see
"Cloning this for someone else" below) but isn't built yet.

## Architecture

- **Django + SQLite**, served by gunicorn, in one Docker container.
- **Cloudflare Tunnel** (`cloudflared`, a sidecar container) exposes it at the
  public domain with zero open ports on the host — no reverse proxy, no TLS
  cert management, all handled by Cloudflare.
- **Deploy = `git push` + a manual pull/rebuild on the server** (see
  "Deployment" below). There's no CI/CD pipeline; it's small enough not to
  need one yet.
- **Two small hardware bridges run on a Raspberry Pi** in the workshop, each
  reachable from the Django app over its own Cloudflare Tunnel hostname:
  - `led-controller/` — drives WS2812B LED strips lining the electronics
    cabinets, via a Feather RP2040 Scorpio, to light up the drawer/bin a part
    lives in.
  - `label-printer/` — relays raw ZPL to a Zebra GK420T thermal label printer
    over USB.
  - The same Pi also runs a **kiosk touchscreen** (`pi-kiosk/`) showing the
    site itself, auto-logged-in, as a physical terminal in the workshop.
  - Each of those three has its own README with full setup steps — this repo
    doesn't auto-deploy them, they're copied to the Pi manually.

## Repo layout

```
config/                  Django project settings/urls/wsgi
inventory/               The one Django app -- models, views, templates, admin
  views/                 View layer, one module per topic -- see "View layout"
  management/commands/   One-off/maintenance scripts (import, enrichment, etc.)
  migrations/
  templates/inventory/
  static/inventory/
  tests/                 The test suite -- one module per area, see "Tests" below
  label_printing.py       Renders custom labels; encodes via label_drivers.py
  label_drivers.py        One class per printer language (ZPL/Brother/Dymo/CUPS)
docs/
  HANDOFF.md              Start here after this file -- running log + backlog
  clarification_workstream.md   Parts too ambiguous for automated enrichment
scripts/
  export_parts_review.py  Regenerates docs/parts_review.xlsx (merge-safe)
  mutation_check.py       Verifies the test suite actually catches broken logic
led-controller/           LED "find the part" system -- Pi bridge + firmware
label-printer/            Zebra GK420T print-bridge
pi-kiosk/                 Pi touchscreen kiosk setup (Chromium, autologin, etc.)
Dockerfile
docker-compose.yml
requirements.txt
.env.example              Every environment variable this app reads, documented
```

## View layout

`inventory/views/` is a package, one module per topic, rather than one big `views.py`:
`browse`, `parts`, `bins`, `labels`, `intake`, `searching` (part search + the voice
API), `tagging`, `projects`, `enrichment`, `lights` (everything that talks to the LED
controller), `auth` (kiosk auto-login), and `_shared` (helpers several of them need).

`views/__init__.py` re-exports every view, so `inventory/urls.py`'s
`from . import views` + `views.browse`, and the test suite's
`from inventory.views import _locate_drawer`, both keep working. **That facade exists
only to keep those import paths stable** — put a new view in the topic module it belongs
to, not in `__init__.py`.

## Local development

Django 6.1 requires **Python 3.12 or newer**. On a machine whose default
`python3` is older (macOS still ships 3.11 in places), use an explicit
interpreter — creating the venv with the wrong one fails at install time with a
Django version error.

```bash
python3.12 -m venv venv          # must be 3.12+ — see note above
./venv/bin/pip install -r requirements.txt
./venv/bin/python manage.py migrate
./venv/bin/python manage.py createsuperuser
./venv/bin/python manage.py runserver 8800
```

Admin UI: http://localhost:8800/admin/ — useful for direct model editing
(bulk edits, fixing bad data) alongside the regular UI.

No `.env` is needed for local dev — `config/settings.py` falls back to
sensible local defaults for everything (SQLite in the repo root, debug mode
on, etc.). See `.env.example` for what production actually needs.

## Tests

```bash
./venv/bin/python manage.py test inventory
```

The suite lives in `inventory/tests/` (one module per area: models, search,
scan resolution, stock/builds, bins, LED, labels, intake, the voice API, kiosk
auth). It uses Django's own test database, so it never touches `db.sqlite3`.
External HTTP — the Pi's LED controller and the label print-bridge — is mocked,
so the whole suite runs offline in a few seconds and needs no hardware.

Two deliberate conventions worth knowing before you add tests:

- **Behaviour contracts, not snapshots.** Assert how two pieces of data relate,
  not today's constants. `assertEqual(BINS_PER_DRAWER, 16)` would be a
  change-detector; `_ensure_bins_seeded()` producing 16 rows per eligible drawer
  is the real contract.
- **Pin footguns and known limits explicitly.** Some tests assert behaviour that
  is *surprising but intentional* (an empty `build_search_query("")` matches
  everything; blank quantity input is rejected rather than cleared) with a
  docstring saying so. That is on purpose: if someone later "fixes" it, the test
  should fail and make them read the reasoning first.

`scripts/mutation_check.py` is the safety net for the safety net — it deliberately
breaks real logic (reverses the FIFO consumption order, swaps the LED
row/column split, disables the bin-scan conflict check, and so on), runs the
relevant tests, and reports anything that stayed green:

```bash
./venv/bin/python scripts/mutation_check.py
```

A test suite that passes proves nothing; this proves it *fails* when the code it
claims to protect is broken. Run it after adding tests for a new area — a
mutation that isn't caught is a blind spot.

### Re-running the spreadsheet import

The import is a one-time load, not a sync (`import_tor_inventory`). If you
need to redo it from scratch, wipe `db.sqlite3` and re-migrate first — running
it against an already-populated DB will collide on `Container.number`, which
is unique.

## Deployment

Production runs on a Hetzner VPS. There's no automation — deploying is:

```bash
git push                                      # from your machine
ssh <server>
cd /opt/sethsparts
git pull
docker compose up -d --build
```

`docker compose` runs two containers: the app itself, and `cloudflared` as a
sidecar that tunnels it to the public domain. Secrets live only in that
server's `/opt/sethsparts/.env` (gitignored) — see `.env.example` for the full
list and what each one does. The server pulls via its own **read-only** deploy
key, separate from whatever key you push with.

## Feature tour

- **Signing in** (`/login/`) — the app's own login page rather than Django's admin
  one, with **Log out** under **More** in the navigation. A fresh clone sends
  first-time visitors to the setup wizard instead, because until an account exists
  there is nothing to log in with. There is deliberately no password-reset email:
  `manage.py changepassword <username>` is the way back in. `/admin/login/` still
  exists for the Django admin itself.
- **Browse / Scan / Search** — `/` lists every drawer up front (day-to-day
  browsing is almost always "which drawer", not "which cabinet"), with the
  full container list below for when cabinet-level organization is what's
  wanted. `/scan/` takes a camera scan or a USB HID barcode scanner's input.
  `/search/` does fuzzy name/category/manufacturer search with a synonym map
  (`inventory/search.py`) so "display" finds OLED/TFT/e-ink parts, etc.
- **Bins & sub-bins** (`/bins/`) — the electronics cabinet drawers (1-27) are
  each subdivided into a 16-bin grid (4 rows × 4 columns); bins can further
  have 0-4 small/medium sub-bins. Both get their own physical barcode,
  scannable via a rapid bulk-scan flow (`/bins/scan/`) that auto-advances
  with zero taps between scans.
- **LED locate** — clicking "Locate" on a part/bin/drawer lights up the
  physical LED strip on that cabinet: breathes for a few seconds, then holds
  a static, multi-colored row/column readout (the drawer's left-side strip
  shows the row, the right-side strip shows the column) for ~12s. See
  `led-controller/`.
- **Custom label designer** (`/labels/custom/`) — type text, optionally add a
  barcode, pick one of the physical label sizes on hand, adjust font
  size/bold/italic, live preview, print — renders as a bitmap (real font
  control) and encodes it for whichever printer type is configured: ZPL,
  Brother QL raster, Dymo raster, or a PNG handed to CUPS. Sent to the printer
  via `label-printer/`. Only the ZPL path has been tested on real hardware;
  the others are written from the manufacturers' manuals and say so in the UI.
- **Moving-day intake** — `/intake/new-box/` quick-creates a new container
  with an auto-assigned number and an immediate printable barcode.
  `/intake/add/` captures a batch of typed/dictated notes about contents (one
  per line), optionally unassigned to a container until `/intake/queue/` is
  used to sort them out.
- **Enrichment queue** (`/enrichment/`) — finds product pages/images/pinouts/
  datasheets/pricing for parts worth the lookup. Classification is pure local
  logic (safe to run any time); the actual web research needs a live agent
  pass (there's a JSON worklist export for that), then the results get
  imported back through the same page.
- **Community map** (`/community/map/`) — opt in, and your instance appears as an
  anonymous pin at postcode-district level: no name, no address, no inventory. Pins are
  signed, so a workshop can pass on a pin it did not publish without being able to alter
  it, and they travel between connected instances rather than through any central
  service. Turning discoverability off publishes a signed removal that every holder acts
  on by deleting the location. The page itself contacts nobody; a button (or
  `manage.py sync_community_pins`) does the asking.
- **Projects / BOM / Build** — versioned bills of materials per project, with
  live stock-coverage math and a "Build" action that FIFO-consumes real stock
  and records what was actually available vs. requested.
- **Reorder dashboard**, **full export** (DB + media as a zip), **reference
  docs** section (pinouts/datasheets/cheat sheets, cached locally).

## Cloning this for someone else

The long-term goal is for Seth's dad (or anyone else) to clone this repo and
stand up their own instance for their own workshop — different LED array,
possibly a different label printer, but the same drawer/row/bin structure.
That needs a guided setup (rebranding the name/URL, flashing a Scorpio for
their wiring, and — the biggest difference — running entirely on their own
Pi locally instead of an externally-hosted server). **Not built yet** —
deliberately deferred until Seth considers his own instance finished. See the
backlog section of `docs/HANDOFF.md` for the current thinking.

## Community search (planned, not built)

Cross-instance search across a friends list of other Seth's-Parts
installs, opt-in and category-scoped, kept on its own page rather than
merged into local search. Full spec: `docs/PLAN_community_search.md`.

## Picking this up with a different AI assistant / on a different machine

1. Read this file, then `docs/HANDOFF.md` top to bottom — its "Current live
   state" section at the top has the load-bearing facts (server address,
   deploy flow, where secrets live, what's mid-flight), and everything below
   that is a dated log of what's been built and why, newest at the bottom.
2. `led-controller/README.md`, `label-printer/README.md`, and
   `pi-kiosk/README.md` each cover their own hardware bridge in detail —
   read the relevant one before touching that part of the system.
3. `docs/clarification_workstream.md` is a standing worklist of inventory
   items too ambiguous to enrich automatically — not something to "complete"
   in one pass, just work through opportunistically.
4. When you finish a unit of work, add a dated entry to `docs/HANDOFF.md`
   (what changed, why, how it was verified) rather than just leaving it in
   git history — that log is what makes picking this up cold actually
   tractable, for a human or another assistant.
5. Run the test suite before and after any change — `./venv/bin/python
   manage.py test inventory`. It is the shared safety net that lets two
   different assistants work on this repo without holding the whole context in
   one head. See the "Tests" section for the conventions it follows.
