# Continue work on sethsparts

Copy the block below into a fresh session to pick this up.

---

We're making my inventory app releasable to other people. Project is at `~/work/sethsparts` (GitHub `sethmills/sethsparts`), live at sethsparts.com on a Hetzner box (`ssh hetzner`, `/opt/sethsparts`, Docker + Cloudflare Tunnel).

**Standing rules — please follow these:**
- **Always ask before `git push` or deploying.** Ask every time, even branches, even if I said yes earlier in the session.
- Never spend money or credits without asking.
- Don't use `open` or Preview on my Mac — ask for URLs/paths instead.
- ComfyUI is off unless I say "darkroom".

**How this codebase is written (please match it):**
- Comments explain *why*, not what. The reasoning and the rejected alternative are the valuable part.
- Every behaviour change gets tests, in `inventory/tests/test_<topic>.py`.
- Run the suite before every commit: `./venv/bin/python manage.py test` (Python 3.12 venv already exists at `./venv`). Currently **757 tests, ~39s**.
- `./venv/bin/python scripts/mutation_check.py` must stay at **100%** (now 74 mutations). It deliberately breaks real decisions and checks the suite notices. Add a mutation for anything security- or privacy-relevant you build. If it reports "anchor not found", logic moved and the anchor needs repointing.
- Migrations must be exercised **against a real database with rows in it**, forward and back — not just a fresh test database. `DJANGO_DB_PATH=/tmp/x.sqlite3 ./venv/bin/python manage.py migrate` is the pattern.
- `inventory/tests/test_portability.py` reads the source and fails on POSIX-only imports, shell-outs, or file access without an explicit `encoding=`. Don't fight it; it exists so the app keeps running on Windows.
- Tests must never touch the network — `inventory/tests/__init__.py` blocks outbound HTTP and will fail loudly. Patch `requests.get`/`requests.post` explicitly.
- The `pi-kiosk/`, `led-controller/pi/` and `label-printer/pi/` directories are Raspberry Pi hardware code and are exempt from the portability rules.

**Current state — everything committed and pushed; nothing in flight.**
- `main` is at **`3468525`** ("Licence it: MIT, and the notices a public release actually needs") — **pushed and in sync with origin, deliberately not deployed.** It touches only `LICENSE`, `THIRD_PARTY_NOTICES.md` and `README.md`, so deploying would change no behaviour; production deliberately stays on `17b0632`.
- GitHub detects the licence: `gh api repos/sethmills/sethsparts/license` reports **MIT** (path `LICENSE`). **The repo is still private** — visibility was left alone on purpose, so it is not yet cloneable by anyone else.
- Everything up to **`17b0632`** is pushed and deployed.
- Tag **`v0.1.0` is pushed** and present on origin, so the update check finally has something to compare against. (`inventory/version.py` says `0.1.0`.) Production is 3 doc-only commits past the tag, so `git describe` there reads `v0.1.0-3-g17b0632` — normal.
- **757 tests pass**, mutation check **74/74 caught**.
- Production verified after the deploy: 1,379 stock rows, 1,221 parts, 74 containers, 27 reference docs, one user (`seth`), **25 inventory migrations** applied. `/login/` returns 200 (the app's own page), `/` redirects to `/login/?next=/`, MapLibre is vendored and served by the app. No errors in the logs.
- Pre-deploy DB backups live in `/opt/sethsparts/data/*.bak` — two `pre-deploy` ones, plus a `pre-community` and a `pre-wizard` snapshot.

**The deploy procedure is codified** in the Hermes skill **`sethsparts-deploy`** — test, secret-scan, push, deploy, verify, plus the traps that have actually bitten (local `curl` returning 400 without `-H "Host: sethsparts.com"`; `docker compose exec -T` eating the rest of a piped script). Read that rather than re-deriving it.

**Then, in order of value:**

1. **Flip the repo to public — the licence is in place and pushed.** MIT is live on `main` (`LICENSE`; a Licence section in README; `THIRD_PARTY_NOTICES.md` reproducing MapLibre's BSD-3-Clause plus the map-data attribution obligation), and GitHub already detects it as MIT. All that remains is the visibility switch, which was deliberately left alone. The repo is **still private**, so `docs/RUNNING.md`'s `git clone https://github.com/sethmills/sethsparts.git` does not work for anyone else yet. Decide separately whether you want issues and PRs at all, and whether to cut a GitHub Release with notes alongside the existing `v0.1.0` tag.
2. **Deploy the LED demo change to the Pi and the Scorpio — it is built and tested but on no hardware.** Demo mode became on/off rather than a fixed ~15s animation (`render_demo` now runs until an explicit `{"cmd": "demo", "on": false}`). `led-controller/pi/code.py` needs `scp` + `sync` (it auto-reloads), and `pi/server.py` needs `scp` plus your own `sudo systemctl restart led-controller`. HANDOFF has this marked "not yet deployed".
3. **The three untested printer drivers.** Brother QL, Dymo LabelWriter and CUPS are written from the vendors' own command references and each carries a `tested` flag that the settings page shows honestly. Only ZPL has been near a printer (your GK420T). If you ever get one of the others, the byte layouts are pinned in `inventory/tests/test_label_drivers.py` — that file is the place to compare against.
4. **Not built, deliberately:** connect requests between strangers (plan §8.4) need a noticeboard relay, and the noticeboard is optional by design — the gossip network covers people who are already connected, which is the case that matters for you and your dad.

**Backlog, discussed and not built:**
- **Guided install for a clone deployment (your dad's).** Explicitly deferred — "not at this moment... when we are finished." Eventually: clone this repo for someone else's workshop (different LED array, possibly a different label printer, same drawer/row/bin structure), with a guided setup covering rebranding and flashing the Scorpio (**flashing is done now** — a skippable wizard/settings step plus the interactive `led-controller/pi/flash-scorpio.py`, which installs CircuitPython on a bare board and verifies the result), and the big architectural difference — running fully locally on that person's own Pi rather than on an externally-hosted box like your Hetzner setup. Revisit once yours feels "complete."
- **Cross-instance community part search** — your idea, full spec already written in **`docs/PLAN_community_search.md`** (private friends-list, category-level opt-in, a thin peer search endpoint, and a separate `/network-search/` page kept apart from your own `/search/` so your results never get diluted). Deliberately not built: you want to see another AI assistant's attempt at implementing it against that spec before it's reviewed.

**Worth reading before touching anything:** `docs/HANDOFF.md` items 21–27 (the test suite, the view split, community sharing, the wizard, the login page, the printer drivers, community pins — each with the reasoning and the rejected alternatives), `docs/RUNNING.md` (the new-user guide), `README.md`.

**Things built recently that you should not accidentally undo:**
- `/login/` is the app's own login page, deliberately not the Django admin's (`/admin/login/` still exists and is untouched). `/logout/` is POST-only, so a GET is a **405** — that's correct, not a bug. There is no password-reset email because the app sends none; the page says so and names `manage.py changepassword`.
- `each` is the default unit and renders as a bare number, so the existing ~1,379 stock rows look unchanged. Units are deliberately *not* a conversion layer.
- Document archiving (`inventory/archiving.py`) fetches local copies of linked documents. It refuses non-http schemes and caps size. Repurchase links must never be archived.
- The setup wizard's account step is the only unauthenticated write in the app and must 404 on **both** GET and POST once an account exists. On a fresh clone with no account, `/login/` redirects to the wizard — also deliberate.
- The community opt-in (`CommunityProfile.discoverable`) and the per-peer permissions (`Peer.exchanges_pins` / `Peer.shares_parts`) are separate on purpose. Connecting for map pins must never grant inventory access. This is the feature's central promise, and three mutations exist purely to protect those defaults.
- A removed community pin keeps a row with the location cleared to NULL. Deleting the row outright lets a stale copy of the old pin resurrect a workshop that asked to be forgotten.
- The update check and the community map both make **no request during a page render** — they read the cache; a button or a management command does the work. It phones GitHub and nowhere else, and can be switched off.
- The printer driver registry, the `SiteSettings` choices and the Pi bridge's accepted content types are three files deployed separately; drift between them presents as "nothing prints". A test asserts they agree.

## Files Seth has shared, still relevant

- `/Users/seth/Downloads/amazon_order_history.xlsx` — for the enrichment backlog, later.
- `docs/parts_review.xlsx` (**local only, gitignored — deliberately not in this repo**, along with `docs/clarification_workstream.md`) — living working files of this workshop's own inventory, regenerate via the merge flow whenever an updated copy comes back.
