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
product. Two instances can also find each other: a workshop that opts in appears
on a map as an anonymous pin, and connecting to one lets you search its parts if
you both choose. Standing up a *second* instance for someone else is most of the
way there — the setup wizard covers rebranding and hardware — but flashing a
Scorpio for their wiring and running it entirely on their own Pi is still to
come. See "Cloning this for someone else" below.

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
  - `label-printer/` — gets finished label bytes to a thermal label printer over
    USB: the printer's own command stream where the app has an encoder (ZPL,
    Brother QL, Dymo), or a PNG handed to CUPS for anything else.
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
  community.py            Pin signing/verifying (no Django imports, so it tests alone)
  community_pins.py       The map's data: gossip, newest-wins, deletion on opt-out
  updates.py              The version check (reads a cache; the button does the fetching)
docs/
  HANDOFF.md              Start here after this file -- running log + backlog
  RUNNING.md              User-facing: install it, run it, add hardware later
  PLAN_community_*.md     Design notes behind the community features
scripts/
  export_parts_review.py  Regenerates the parts-review workbook (kept locally)
  mutation_check.py       Verifies the test suite actually catches broken logic
led-controller/           LED "find the part" system -- Pi bridge + firmware
label-printer/            Print-bridge for the label printer (raw USB bytes, or CUPS)
pi-kiosk/                 Pi touchscreen kiosk setup (Chromium, autologin, etc.)
Dockerfile
docker-compose.yml
requirements.txt
.env.example              Every environment variable this app reads, documented
```

**Not in this repo, deliberately:** anything that is *this workshop's* contents rather than
the app itself. The parts-review workbook and the clarification worklist (`docs/`,
gitignored), the database, `media/`, and `.env` all stay on the machine that owns them. A
clone gets the code, not somebody else's inventory — and nothing here needs them to work.

## View layout

`inventory/views/` is a package, one module per topic, rather than one big `views.py`:
`browse`, `parts`, `bins`, `labels`, `intake`, `searching` (part search + the Home
Assistant endpoint), `tagging`, `projects`, `enrichment`, `lights` (everything that talks
to the LED controller), `reference` (the document library), `community` (connections,
the pins endpoint and the map), `setup` (the wizard), `help`, `auth` (login/logout and
kiosk auto-login), and `_shared` (helpers several of them need).

`views/__init__.py` re-exports every view, so `inventory/urls.py`'s
`from . import views` + `views.browse`, and the test suite's
`from inventory.views import _locate_drawer`, both keep working. **That facade exists
only to keep those import paths stable** — put a new view in the topic module it belongs
to, not in `__init__.py`.

## Install it

Two copy-paste routes. `docs/RUNNING.md` is the long version of both, with the optional
pieces (hardware, community, public access) explained one at a time.

> The repository is private while the release is being finished, so `git clone` needs
> access today — see "Cloning this for someone else". The commands below are what they
> will be once it's public.

### Docker — any machine, including a Pi

Nothing else is needed: no Python, no database, no Cloudflare, no domain, no tunnel token.

```bash
git clone https://github.com/sethmills/sethsparts.git
cd sethsparts

# Two secrets are required. Generate them rather than inventing them.
cat > .env <<EOF
DJANGO_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
EOF

docker compose up -d
```

Open <http://localhost:3200>. The first thing you get is a setup wizard — it creates your
account, then asks about the optional pieces one at a time, all skippable. Your data is
`./data/` next to the compose file (`db.sqlite3` plus `media/`), so **backing up is copying
that folder**.

To use it from another machine on your network, change the port mapping in
`docker-compose.yml` from `"127.0.0.1:3200:3200"` to `"3200:3200"` and add the names you'll
use to `DJANGO_ALLOWED_HOSTS`. Public access is a separate, optional step (Cloudflare
Tunnel) — see `docs/RUNNING.md`.

### Raspberry Pi

The same container route, plus Docker itself and one compose edit:

```bash
# 1. Docker (not installed on Pi OS by default). 64-bit Pi OS required.
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"      # log out and back in for this to take effect

# 2. The app, exactly as above
git clone https://github.com/sethmills/sethsparts.git
cd sethsparts
cat > .env <<EOF
DJANGO_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
DJANGO_ALLOWED_HOSTS=parts.local,localhost
EOF

# 3. In docker-compose.yml, change  "127.0.0.1:3200:3200"  to  "3200:3200"
#    (otherwise only the Pi itself can reach it), then:
docker compose up -d
```

Then open `http://<the Pi's address>:3200` from anything on your network. Add that address
to `DJANGO_ALLOWED_HOSTS` too — Django refuses hosts it doesn't recognise, which is the
usual cause of a "400 Bad Request" on first setup.

Worth knowing before you start:

- **The image is multi-arch** (`python:3.12-slim`, and every dependency publishes aarch64
  wheels), so it builds on a Pi 4/5. It has only been built and run on x86-64 so far — the
  Pi in this workshop runs the LED and label bridges, not the app — so the first arm64
  build is plausible but unproven.
- **The non-Docker route needs Python 3.12+.** Pi OS *Bookworm* ships 3.11, so Django 6.1
  won't install there; Pi OS *Trixie* (Debian 13, Python 3.13) works. If you're on
  Bookworm, use the container.
- **The Pi bridges are separate.** `led-controller/`, `label-printer/` and `pi-kiosk/` are
  copied onto a Pi and run as their own services, with their own READMEs. None of them are
  needed to use the app, and running the app *itself* on the same Pi is fine.

### Without Docker (development or a bare-metal install)

```bash
git clone https://github.com/sethmills/sethsparts.git
cd sethsparts

python3 -m venv venv                      # must be 3.12 or newer
source venv/bin/activate                  # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000>. For anything beyond your own machine, run it under a real
server rather than `runserver` — `gunicorn` (Linux/macOS) or `waitress` (Windows) are both
already in `requirements.txt`; see `docs/RUNNING.md`.

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

The suite lives in `inventory/tests/` (one module per area: models, search, scan
resolution, stock/builds, bins, LED, labels and the label drivers, intake, the Home
Assistant endpoint, kiosk auth, community crypto/pairing/pins, reference, help, site
settings, templates). It uses Django's own test database, so it never touches
`db.sqlite3`. External HTTP — the Pi's LED controller, the label print-bridge and other
workshops — is mocked, so the whole suite runs offline: **759 tests in about 40 seconds,
no hardware needed.**

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

`scripts/mutation_check.py` is the safety net for the safety net — 75 deliberate
breakages (reverses the FIFO consumption order, swaps the LED row/column split,
disables the bin-scan conflict check, puts the login wall back on the Django admin page,
drops the "newest pin wins" rule, turns a signed removal back into a location...), each
followed by the tests that ought to notice, reporting anything that stayed green:

```bash
./venv/bin/python scripts/mutation_check.py
```

A test suite that passes proves nothing; this proves it *fails* when the code it
claims to protect is broken. Run it after adding tests for a new area — a
mutation that isn't caught is a blind spot. It edits the working tree in place
(restoring each file as it goes), so don't run it alongside a local test run or a
commit, and **it must be at 100% before a deploy.** A mutation that reports `!! anchor
not found` means the code it targets has been rewritten — that is the script telling you
to move the anchor, not that the behaviour is gone.

### Migrations

Every migration gets exercised against a copy of the **real** database before it ships —
forward, back, forward again — rather than only against a fresh test database. That is
the difference between finding out now that a column cannot be added to a table with
1,379 rows in it, and finding out mid-deploy:

```bash
cp /path/to/a/populated/db.sqlite3 /tmp/mig.sqlite3
DJANGO_DB_PATH=/tmp/mig.sqlite3 ./venv/bin/python manage.py migrate            # forward
DJANGO_DB_PATH=/tmp/mig.sqlite3 ./venv/bin/python manage.py migrate inventory <previous>
DJANGO_DB_PATH=/tmp/mig.sqlite3 ./venv/bin/python manage.py migrate            # forward again
```

Compare row counts after each step, and run `makemigrations --check --dry-run`: a model
change with no migration is a lie the test suite cannot see.

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
cp data/db.sqlite3 "data/db.sqlite3.pre-deploy-$(date +%Y%m%d-%H%M%S).bak"   # always
git pull --ff-only
docker compose --profile tunnel up -d --build   # --profile tunnel: production runs the
                                                # Cloudflare tunnel, which is opt-in
```

Back up first even though nothing in a deploy should touch the data: the container
runs `migrate` before gunicorn on every start, so **a deploy is also a migration run
against the live database** — the backup is the difference between reverting the code
and restoring the app. Then check `docker logs sethsparts` for the migrations and for a
clean gunicorn boot, and compare a row count or two (`SELECT COUNT(*) FROM
inventory_stockitem`) against that backup — the only thing that catches a migration
which quietly ate data.

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
- **Setup wizard** (`/setup/`) — what a fresh install shows first: your account, then the
  workshop's name, timezone and units, then the optional pieces one at a time (lights,
  label printer, reference library, community, access). Every step is skippable, and every
  step stays available afterwards under Settings, because a wizard you can only run once
  is a wizard people work around.
- **In-app help** (`/help/`) — the same ground as this README, written for whoever uses the
  workshop rather than whoever wrote it, including what the community feature does and
  does not share.
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
  `led-controller/`. Which strip is plugged into which controller output is
  recorded in the wizard and pushed to the Pi, so the wiring map lives in the app
  rather than in a JSON file on the Pi. `/lights/` is the manual side of it: default
  colour and brightness, the room light, and a demo sweep to check the wiring before
  trusting the locate feature.
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
- **Community connections** (`/community/`) — pair with another workshop by swapping a
  short-lived code, then choose per connection what it may do. Showing each other on the
  map and searching each other's parts are separate permissions **on purpose**, so
  connecting for the map never hands over your inventory. Revoking takes effect
  immediately, including for the map endpoint.
- **Reference library** (`/reference/`) — pinouts, datasheets and cheat sheets, organised
  by category, with an optional archive step that fetches and keeps a local copy of what a
  link points at (http/https only, size-capped, and never for repurchase links, which
  rot). Includes a resistor colour-code calculator.
- **Reorder dashboard** (`/reorder/`) — everything at or below its low-stock threshold in
  one list to work through.
- **Full export** (`/export/`) — the database and media as a zip, so "your data" is
  something you can hold rather than a promise.
- **Home Assistant** (`/api/locate/?q=…`) — a machine-to-machine lookup keyed by
  `VOICE_SEARCH_API_KEY`, so an Assist intent can answer "where are the M3 screws?" with
  the drawer or box they're in.
- **Update check** — the settings page compares `inventory/version.py` against this
  project's GitHub releases and tags when you press the button. Never during a page
  render, and it never updates anything by itself; it also tells you when you're current.
- **Kiosk mode** — a Pi touchscreen pointed at `/kiosk-autologin/?token=…`, which mints a
  real session server-side (never the owner's password). See `pi-kiosk/`.

## Cloning this for someone else

The goal is for Seth's dad (or anyone else) to clone this repo and stand up
their own instance for their own workshop — a different LED array, possibly a
different label printer, but the same drawer/row/bin structure.

**What's already true:** the app is platform-agnostic — nothing shells out, nothing
assumes macOS or Linux paths, and a test enforces both — the setup wizard covers
rebranding and every piece of hardware configuration, the label printer is a driver
layer rather than one hardcoded printer, and `docs/RUNNING.md` is a from-scratch guide
that assumes nothing about the machine. `docker compose up -d` is the whole install.

**What's still missing:** flashing a Scorpio for someone else's LED wiring, and running
the whole thing on their own Pi — tunnels, backups and all — rather than on an
externally-hosted server. Deliberately deferred until Seth considers his own instance
finished; see the backlog in `docs/HANDOFF.md`.

## Community search (specified, not built)

Cross-instance search across your connections, opt-in and category-scoped, kept on its
own page rather than merged into local search. The groundwork is in place — connections,
per-connection permissions (`Peer.shares_parts`), rate limiting on the claim endpoint, and
a log of what connected workshops have searched for — but there are no routes for the
search itself yet. Full spec: `docs/PLAN_community_search.md`.

## Safety

This is software that switches physical things — it lights an LED output to
point at a drawer, and sends bytes to a label printer. Read this before wiring
anything up.

- **The app validates what it sends but cannot know what's wired where.** LED
  channels are range-checked on both the app side and the Pi side, and a label
  too wide for the print head is refused rather than silently clipped. But a
  strip mapped to the wrong channel will happily light the wrong drawer — the
  app cannot tell you your wiring is wrong, only that the number it was given
  is a legal one.
- **Do not power LED strips from the Pi.** Addressable strips draw far more
  current than a GPIO pin or the Pi's own 5 V rail can supply. Size and fuse a
  separate supply for the strips; the Pi only sends data.
- **Never put mains voltage on the controller's outputs.** If your strips or
  their supply need mains, that part is ordinary electrical work and separate
  from anything here.
- **The label printer bridge writes to a raw USB device node or a CUPS queue.**
  The app runs no printer driver itself and cannot detect that a printer is
  unplugged — `/health` on the bridge is what distinguishes "unplugged" from
  "not installed".
- The MIT licence in `LICENSE` disclaims warranty and liability. That is the
  legal form of the paragraph above.

## Credits and prior art

This app did not come from nothing. **InvenTree** ([inventree.org](https://inventree.org),
[github.com/inventree/inventree](https://github.com/inventree/inventree)) was the reference
point that made it imaginable: the shape of the data model — parts, stock items, categories,
locations, bills of materials — and the decision to self-host a proper inventory system
rather than keep feeding a spreadsheet both started there. The first build leaned on it
heavily, and was then adapted to this workshop's way of working and grew the parts that are
specific to it: barcode-first browsing, the 16-bin drawer grid, the LED "find the part"
indicators, label printing, and the community map.

They deserve the credit, and it is worth saying plainly: **if you want a mature, multi-user
inventory platform** — purchasing, suppliers, build orders, a full API, an active community
— use InvenTree. It is a serious project. This is one person's smaller tool, shaped by a
physical workshop and a barcode scanner.

InvenTree is MIT-licensed, as this is.

## Licence

MIT — see `LICENSE`. Copyright (c) 2026 Seth Mills.

Third-party code redistributed here (MapLibre GL JS, vendored so the map page
makes no third-party requests, and the fonts the label renderer uses) is
covered in `THIRD_PARTY_NOTICES.md`, including the map-data attribution
required by OpenStreetMap's ODbL — **don't remove the map's attribution
control.**

## Picking this up with a different AI assistant / on a different machine

1. Read this file, then `docs/HANDOFF.md` top to bottom — its "Current live
   state" section at the top has the load-bearing facts (server address,
   deploy flow, where secrets live, what's mid-flight), and everything below
   that is a dated log of what's been built and why, newest at the bottom.
2. `led-controller/README.md`, `label-printer/README.md`, and
   `pi-kiosk/README.md` each cover their own hardware bridge in detail —
   read the relevant one before touching that part of the system.
3. Per-workshop working files are deliberately **not** in this repo (they're
   gitignored): `docs/parts_review.xlsx`, the review workbook, and
   `docs/clarification_workstream.md`, a standing worklist of inventory items too
   ambiguous to enrich automatically. Both exist only on the owner's machine, and
   neither is something to "complete" in one pass — the worklist gets worked through
   opportunistically.
4. When you finish a unit of work, add a dated entry to `docs/HANDOFF.md`
   (what changed, why, how it was verified) rather than just leaving it in
   git history — that log is what makes picking this up cold actually
   tractable, for a human or another assistant.
5. Run the test suite before and after any change — `./venv/bin/python
   manage.py test inventory`. It is the shared safety net that lets two
   different assistants work on this repo without holding the whole context in
   one head. See the "Tests" section for the conventions it follows.
