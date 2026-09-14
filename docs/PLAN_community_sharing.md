# Plan: community sharing, location, and discovery

**Status: design agreed, not built.** Supersedes `PLAN_community_search.md` (which
covered only the search half and remains correct on most of it).

This is the second revision — the first explored a lot of option space that the owner has
since closed, so it has been cut back to the decided design. Read this whole file
before writing code. If you are the implementing assistant: read `README.md` and the
"Current live state" section of `docs/HANDOFF.md` first. Leave a dated entry in
`docs/HANDOFF.md` when done.

---

## 1. What this is

Workshops running this app can optionally find each other, and optionally share parts
with each other. Built for the maintainer and their family first, released publicly second.

Three things, deliberately separate, each off by default:

| # | Feature | What it needs |
|---|---|---|
| 1 | **Pairing** — share parts with a workshop you know | nothing central |
| 2 | **Discoverability** — appear as an anonymous pin on other people's maps | the noticeboard |
| 3 | **Connect requests** — ask a pin you can see to connect | the noticeboard |

Feature 1 is the thing the maintainer and their family actually need. Features 2 and 3 are the map.

## 2. Privacy model — three independent levels

Private by default, always.

| Level | What the owner does | What anyone else learns | Default |
|---|---|---|---|
| **Private** | nothing | nothing at all — not on any map, not in any list | ✅ **default** |
| **Discoverable** | opts in, enters a postcode/ZIP | an **anonymous pin** at postcode-area level. No name, no inventory, no contact details | opt-in |
| **Connected** | pairs with a specific person via a short code | that person can search the categories the owner ticked | opt-in, per person |

**These are not linked.** Being discoverable does not make you searchable, and being
someone's peer does not put you on the map. Keep them separate in the UI, the model,
and the code — that separation is the privacy backbone.

**Requirement:** the discoverability choice is asked **during initial setup**,
so a new owner decides consciously rather than never finding the setting. Changeable
at any time in Settings.

## 3. Location

### 3.1 Postcode / ZIP area level, no grid maths

An earlier draft snapped coordinates to a grid. That is unnecessary: the geocoders
hand back the right granularity directly.

| Format | Size | Households | Publish? |
|---|---|---|---|
| UK full postcode (`SW1A 1AA`) | a street | **~15** | ❌ **never** |
| UK outcode (`SW1A`) | a district | thousands | ✅ |
| US ZIP (`90210`) | km² urban, 100s km² rural | thousands | ✅ |
| US ZIP+4 | a block | a few | ❌ never |

**For the UK the unit is the outcode, never the full postcode.** A full UK postcode
identifies roughly fifteen households — publishing one publishes a doorstep. It
is less precise than "ZIP code level" sounds, and
deliberately so.

### 3.2 Geocoding — researched and verified live

Geocoding runs **once, at setup**. The result is stored locally. It is not a runtime
dependency, so free-tier limits never matter.

| Country | Service | Key? | What we take |
|---|---|---|---|
| UK | `api.postcodes.io` | none | **outcode** → centroid (the service exposes the right granularity directly) |
| US | `api.zippopotam.us` | none | ZIP → centroid |
| anywhere else | `nominatim.openstreetmap.org/search?format=json` | none | first result with `type=postcode` |

Verified during design: postcodes.io resolves both `postcodes/SW1A1AA` and
`outcodes/SW1A`; Zippopotam returns `34.0901, -118.4065` for `us/90210`; and
**`zippopotam.us/gb/SW1A1AA` returns HTTP 404** — it does *not* handle UK. Assuming
one service covers both countries is the obvious first bug. Nominatim resolved both a
UK postcode and a US ZIP, with a real `User-Agent` required and **max 1 req/s**.

If geocoding is unreachable, let the owner enter coordinates by hand or skip location
— levels 1 and 3 keep working without it.

## 4. Pairing with a short code

1. **A** opens Community → *Invite a workshop*. A sees a **pairing code**
   (e.g. `K7F2-9QX3` — 8 chars, Crockford base32 so no ambiguous `0/O` or `1/I/L`),
   valid **24 hours**, **single use**, plus A's public URL.
2. A sends both, out of band, however they like.
3. **B** opens Community → *Add a workshop*, types A's URL and the code.
4. B calls `POST A/api/peer/claim/` with the code and B's own URL.
5. A validates — matches, unexpired, unused, within rate limits — creates a `Peer`
   row for B with a fresh per-peer key, returns it.
6. B stores the key. Both are connected.

8 chars of base32 is ~40 bits, so guessing is not the threat; the real protections are
**single use, 24-hour expiry, and rate limiting**. Compare with `secrets.compare_digest`.
TLS is already mandatory (Cloudflare Tunnel).

**Also required:**

- **Revocation** as a first-class action, not a delete-and-hope. A revoked peer's key
  is rejected immediately, and revoking must be one click.
- **An access log** — record each inbound peer search (peer, time, query, hit count)
  and show it to the owner. For a public release this is the difference between "trust
  me" and "check for yourself".
- **`contact_note`** (resolved): an email is fine to expose, but present it as a
  **"Contact" action in the UI that reveals a `mailto:`**, not an address printed into
  every search result.

### 4.1 Prerequisite: peers must be reachable

Direct peer search needs **each instance reachable from the internet** (this project's
live instance uses a Cloudflare Tunnel). But the stated goal for a family member is
*running entirely on their own Pi locally* — a LAN-only instance **cannot be searched by
anyone**. This is the main
setup hurdle for the public audience and must be documented as a prerequisite, not
discovered by confused users.

## 5. The noticeboard — the maintainer runs it

**Decided:** the maintainer hosts the noticeboard on their own server, and the documentation says
plainly that it is a hobby service for this small community, that anyone can opt out,
and that anyone can run their own instead.

That closes the bootstrap problem (see §6) and is the pragmatic answer at this scale.
The obligations it creates are small *because* of the design: a pin is an anonymous
postcode-area location with no name, and removal actually works (§5.2).

### 5.1 What it stores — and what it never stores

```
instance_id   opaque random 128-bit id (also the deletion credential)
public_key    the instance's signing key (see §7)
cell_lat      postcode-area centroid
cell_lon      postcode-area centroid
country       ISO code
updated_at
```

**Never stored:** names, inventory, exact coordinates, the postcode/ZIP itself, email,
peer URLs, IP addresses, or anything linking a row to a person. No accounts, no
passwords. A display name is **not** part of the map — the map shows anonymous pins.

### 5.2 Opt-out must genuinely remove, not hide

The load-bearing requirement. When an owner switches
discoverability off:

1. The instance calls `DELETE /pin/<instance_id>` on the noticeboard.
2. The row is **gone** on the next read — not flagged, not hidden.
3. Removal is tested as carefully as opt-in. A test asserting the row is absent from
   the board's output after opt-out, not merely that a flag flipped.

The same path is the GDPR erasure mechanism: possession of `instance_id` is the only
credential needed, and it is one request, no account, no support ticket.

A pin not refreshed within N months expires automatically, so abandoned instances do
not accumulate.

## 6. Discovery — the connections ARE the network

**This design is better than the first draft of this plan.** An earlier
revision proposed a central list of noticeboard URLs and explicitly *rejected*
peer-to-peer gossip because a brand-new instance has nobody to ask. The fix closes
that hole: **ship every new install already connected to one seed peer** (the
maintainer's instance), and the map feature only unlocks once you have at least one
connection.

The network is then the graph of connections, not a service:

1. Install ships with **one default gossip neighbour** — the maintainer's instance.
2. Because you have ≥1 connection, the map feature is available.
3. Your instance asks its neighbours *"what pins do you know about?"*
4. Neighbours reply with the signed pins they hold, including ones they learned from
   *their* neighbours, forwarded with a hop limit so it doesn't loop forever.
5. **Newest valid signed entry per key wins** (§7), so forwarding cannot corrupt
   anything — a relayed pin is still verified against its origin signature.

**Why this beats a central service:**

| | Central noticeboard | Peer gossip (this) |
|---|---|---|
| If the operator stops hosting | feature dead until fixed | connect to any other workshop and you are back |
| Load | one machine holds everything | spread across participants |
| "Who runs it" | a service someone must maintain | nobody; peers are already running |
| Bootstrap | solve with a URL | solve with a seed peer |

**Fallback, and it should be written in the docs exactly this way:** if the maintainer's
instance goes offline or is retired, all a user has to do is become connected with any
other workshop and the map starts updating again — they are back inside the network.
No migration, no reconfiguration, no data loss. Shipping 2–3 seed peers instead of one
would reduce the single dependency further, once other instances exist.

### 6.1 Two relationships, deliberately separate

The "maintainer connected to every install by default" needs a permission split, or it becomes a privacy
problem: being connected to the maintainer must **not** mean the maintainer can search
that workshop's inventory, or every install would be sharing its parts by default.

| Relationship | Grants | Default |
|---|---|---|
| **Gossip neighbour** | exchange anonymous pins only. **No inventory access, ever.** | the seed peer, on every install |
| **Sharing peer** (§4) | search the categories the owner ticked | opt-in, person by person |

They may be the same person; they are never the same permission. This is the same
principle as §2 — visible on the map ≠ searchable — applied to the seed peer.

The seed relationship must be **removable in one click**, and removal must actually
sever it (same standard as §5.2), with the docs saying plainly that the maintainer is
connected by default and can be removed at any time.

### 6.2 What gossip does and does not spread

The anonymous pin is public-by-design and is *meant* to spread — that is what makes a
map possible. The opt-in wording must say so honestly: *"your pin will be visible to
workshops across the network"*, not *"only to people you connect with"*.

What must never spread: inventory, names, contact details, exact coordinates, or the
postcode/ZIP itself. Also, a node should not disclose **which neighbour it learned a
pin from** — otherwise the social graph can be inferred by watching who receives what.

**Rejected:** a central list of noticeboard URLs as the *primary* mechanism. It works,
but it needs a maintained list and an operator, and it dies with them. Keep the board
service (§5) available as an option — it costs little and helps anyone behind a
firewall — but the network should not depend on it.

## 7. Sign entries from day one (and why not a blockchain)

A question worth settling: whether everyone could be a noticeboard, gossiping to keep the most recent
state — a blockchain. The instinct is right; the tool is wrong.

**What the design actually needs is authentication and freshness, not consensus.**
Everyone holding a copy, newest-wins, tamper-evident — that is signatures plus
timestamping. A blockchain adds consensus, which is the expensive part (mining or
staking, syncing a chain before participating, a Pi running a node), and buys nothing
here.

**The decisive objection is §5.2.** Erasure means data must be **deleted**. An
append-only ledger is the opposite: once written, a pin is on every node forever and
marking it "removed" leaves the location data in place. **An immutable chain cannot
honour "forget me"** — the requirement rules out the technology.

**Instead, sign the pins.** Each instance generates a keypair; a pin is
`{public_key, cell, timestamp, signature}`:

- Any instance can hold a full copy, and **nobody can forge or alter another's pin** —
  they cannot sign as them. That is the tamper-evidence.
- **Newest valid signed entry per key wins.** No consensus is needed because there is
  exactly one legitimate writer per entry.
- **Removal is a newer signed entry**, and each node can genuinely delete superseded
  data. A chain could not.
- Sync is: exchange lists, merge, keep the newest valid entry per key.

**This is the one decision to get right now.** Building it server-only and adding
signatures later means rewriting the format and every client. Signing costs almost
nothing today and makes the federated version a config change. It also means a scraped
board yields blobs nobody can tamper with, rather than a database someone can corrupt.

For later reference only: this is close to what **Nostr** already does (relays
gossiping signed events, many relays read in parallel, newest wins). If the fully
decentralised version is ever wanted, the format maps onto it almost 1:1. Do not build
on it now.

## 8. The map

- An **anonymous pin** at postcode-area level. No name, no inventory, no contact
  details, nothing beyond the pin itself and its country.
- Connected workshops may show their name and appear distinctly. Everyone else is an
  unlabelled pin.
- **Clicking a pin offers "request to connect"** — nothing more. That opens a connect
  request (§8.4); no information about that workshop is revealed by the click.
- Real pan/zoom to anywhere, not just a picture of a neighbourhood.

### 8.0 The stack — open source end to end, no signup

**Decided:** MapLibre GL + OpenFreeMap. Chosen over Google Maps and over Leaflet, after
checking the terms rather than assuming.

| Layer | Choice | Why |
|---|---|---|
| Map library | **MapLibre GL JS** (v4.x) | Open-source fork of Mapbox GL. Vector tiles, so zoom is smooth and continuous rather than stepped like the Google Maps people expect. Single `<script>` + stylesheet, no build step. |
| Tiles + styles | **OpenFreeMap** public instance | Explicitly free for any number of views and requests. **No API keys, no registration, no user database, no cookies.** The whole production setup is open source, so it can be self-hosted (§8.3). Four ready styles incl. `dark`, which matches this app. |
| Map data | OpenStreetMap (ODbL) | Attribution required and always shown. |

**Why not Google Maps.** It requires an API key tied to a **Google Cloud billing
account with a card on file**, even to use the free tier — Google's own docs state
billing must be enabled. For one instance that is nearly free, but **every person who
clones this project would need their own billing account**, which turns "clone and run"
into a signup-and-add-a-card exercise. It is the wrong default for a hobbyist project.
If an owner specifically wants Google imagery, that can be an opt-in extra where they
supply their own key — never the default.

**Why not Leaflet after all.** Leaflet is perfectly good and remains a fine fallback,
but it serves *raster* tiles, which in practice meant pointing at
`tile.openstreetmap.org` — free, but donation-funded, with a usage policy that forbids
bulk/offline use and explicitly asks that the tile URL not be hardcoded. Vector tiles
from OpenFreeMap remove that dependency and that policy risk, and give a better map.

**Attribution is mandatory** for both OpenFreeMap and OpenStreetMap contributors, must
be visible, and must not be hidden behind a toggle or off-screen.

### 8.1 Configuration, not hardcoding

Both the style URL and the tile source are **settings**, defaulting to OpenFreeMap, never
hardcoded — so an operator can point at their own without a software update.

**Vendor MapLibre locally** rather than CDN-loading it. The workshop Pi can have flaky
connectivity, and a self-hosted app should not depend on a third-party CDN to render its
own map.

### 8.2 If someone chooses OSM raster tiles anyway

Keep the option, with the caveats recorded: the OSM tile policy permits normal
interactive human viewing with visible attribution, but **forbids** bulk/prefetch
downloading and offline caching of areas, requires a valid identifying `User-Agent`,
requires honouring cache headers (≥7 days), and states explicitly that the tile URL
should not be hardcoded. Fine for a single self-hosted instance; not fine for a widely
distributed app all pointing at donation-funded servers.

### 8.3 Self-hosting the tiles (the zero-dependency option)

For anyone who wants no third party at all:

- **OpenFreeMap can be self-hosted** — its production setup is open source, which is the
  straightforward path to the same styles served from your own machine.
- **Protomaps** is the lighter-weight alternative: the world basemap as a single
  `.pmtiles` file, servable from static hosting with no tile server. Build a **regional
  extract** rather than the whole planet — a workshop app only cares about its own
  country, which makes the file size tractable.

Document both as opt-in. Neither should be required to get a working map.

### 8.4 Connect requests (blind relay)

Clicking a pin sends a request through the noticeboard, which relays it. Neither side
learns anything about the other until both agree:

1. Your instance asks the board to relay a connect request to `<opaque id>`.
2. The board forwards: *"a workshop in your region would like to connect."* No name,
   no URL, no exact location.
3. They accept or decline.
4. **Only on mutual acceptance** do the two instances exchange URLs and complete a
   normal pairing (§4), including the short-code confirmation.

Rate-limit requests per instance and per board, and **make blocking possible from the
receiving side** — this is the one place strangers can contact each other, so it needs
those controls before it ships, not after.

## 9. Legal position

Not legal advice; the framework checked against ICO guidance.

UK GDPR's definition of personal data **explicitly names location data** as an
identifier, so the question is only whether a person is identifiable. A postcode-area
pin usually falls short of that — but not always (a rural area with one workshop in it
is identifiable locally), and the board would log IP addresses on registration, which
are personal data regardless.

**The relevant relief:** UK GDPR does **not** apply to processing "in the course of a
purely personal or household activity" with no connection to a professional or
commercial activity. For a small board among people who know each other, that is likely
in play. It is not in play for a public service.

**Design already handles the obligations:** consent is explicit and revocable in the
product; data is minimised to a coarse cell and an opaque id; erasure is one
`DELETE`; and unrefreshed pins expire. What remains is to publish a short plain-English
notice before the board is advertised publicly, and to handle a breach notification
(ICO, within 72 hours) if that ever arises.

**Also worth restating:** publishing the code does not make the maintainer the
controller for other people's instances — only for the board they run, because that is
the only place they determine what happens to the data. That is why the board is optional and the
format is portable.

**And the risk that is not legal:** a map of home workshops full of tools is a target
list. Postcode-area granularity and anonymity mitigate it substantially; do not
undermine that by adding names, exact locations, or finer pins to the default view.

## 10. Releasing publicly

- No maintainer-specific assumptions: board URL, tile URL, instance name and country are all
  configuration with sensible defaults.
- The board must remain optional and independently runnable, so nobody is forced to
  trust the maintainer's, and the maintainer is not obliged to serve strangers.
- Country handling must not be hardcoded to UK/US — postcodes.io and Zippopotam are
  the good paths, Nominatim is the general case that keeps everyone else working.
- Documentation *is* the feature: the tunnel prerequisite (§4.1), pairing, what peers
  can and cannot see, and running your own board.
- **The family-member case is the test.** If pairing cannot be done by a non-technical person
  over the phone in two minutes, it is not finished.

## 11. Build order

**1. Sharing and pairing.** Peer model, inbound/outbound search, short-code pairing,
revocation, access log. No location at all. This is what unblocks the maintainer and their family, and
it is deliberately the smallest useful release.

**2. Location.** During setup, ask the discoverability question; geocode the postcode
to an outcode/ZIP centroid; store it. Nothing shared yet.

**3. The board + the map.** The maintainer's board service, signed pins from day one (§7),
opt-out that genuinely deletes (§5.2), the map, and connect requests (§8.4).

If the map is wanted sooner, 2 and 3 can move, but stage 1 should not wait behind them.

## 12. Open questions for the implementer

1. Exact quantity bucketing for peer search results ("have some" / "have a few") —
   deliberately fuzzed, never the precise internal `quantity_summary`.
2. Fan-out timeout and sequencing for peer search (2 peers vs 20 changes the answer).
3. Whether the pairing code should also be accepted as a pasteable
   `https://host/pair#CODE` link — much friendlier than typing a URL and a code on a
   phone.
4. How to show a **stale** pin (not refreshed in months) — probably not counted as
   "nearby" at all.
5. Key management for §7: one keypair per instance, stored where, and how a lost key
   is recovered (or explicitly not).
