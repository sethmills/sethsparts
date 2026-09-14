# Plan: cross-instance community part search

> **Superseded — see `docs/PLAN_community_sharing.md`.**
>
> This doc scoped the *search* half of the feature and is still correct on most of it
> (peer model, inbound endpoint, category-level sharing, fuzzed quantities). It did
> not cover location, the map, discovery of unconnected workshops, short-code pairing,
> or the consequences of releasing this publicly — all of which the owner raised afterwards.
> The newer doc carries this material forward, corrected, and replaces it as the
> source of truth. Kept for reference; do not build from this one alone.

**Status: planning only, not built.** This is a self-contained spec for
implementing the feature — written so a different AI assistant (or the owner
themselves) can pick it up without needing any other context. If you're the
assistant implementing this: read this whole file, then `README.md` and the
"Current live state" section of `docs/HANDOFF.md` for how the rest of the app
is put together, then come back here before writing code.

When you're done with a first pass, leave a dated write-up in
`docs/HANDOFF.md` (same pattern every other feature in this repo follows) —
what you built, what you decided among the open questions below and why, and
how you verified it.

## The idea

Search for a part; if the owner doesn't have it, search the inventories of
other nearby community members who do, then request to purchase it and pick
it up directly — no payments handled by the app, just the ability to search
other users' inventory with their permission.

Refined in discussion to: a **friends list**, not a public directory. An
owner adds specific people they know (starting with the people they actually
share a workshop with), individually, by exchanging some kind of connection
code, and can then search across whichever friends they've added. Explicitly
**not** an open network anyone can join or discover instances through.

## Hard constraints (don't relitigate these, they're settled)

1. **No payments, no in-app purchase flow.** "Request to purchase" means
   surfacing a way to contact the other person (e.g. an email link) — that's
   the entire scope of "purchase" here. They coordinate payment/pickup
   entirely outside this app.
2. **No public discovery.** Adding a peer is a deliberate, manual, mutual
   action between two people who already know each other and exchange
   something (a URL + a code) directly — not a search-the-internet-for-peers
   directory. This avoids spam/abuse/trust problems that a public model would
   create immediately.
3. **Opt-in, and scoped.** A peer should only ever be able to search the
   subset of an owner's inventory they've chosen to expose — not the entire
   database by default. The inverse concern is just as important: don't let
   the owner's own search results get cluttered by low-value guesses from
   peers either.
4. **Two separate search experiences, not one merged pool.** An owner's own
   default `/search/` must keep returning only their own inventory, exactly
   as it does today. Network results live on their own page the user opts
   into per search, never blended into local results by default.

## Proposed shape (recommendation, open to the implementer's judgment)

### Data model

Two new models in `inventory/models.py`:

```python
class Peer(models.Model):
    """A friend's separate Seth's-Parts instance, added by mutual agreement."""
    name = models.CharField(max_length=200)          # "Dad's workshop", freeform
    base_url = models.URLField()                       # e.g. https://ericsparts.example.com
    outbound_api_key = models.CharField(max_length=100)  # the key THEY gave us, to query them
    inbound_api_key = models.CharField(max_length=100, unique=True)  # the key we gave THEM, to query us
    contact_note = models.CharField(max_length=300, blank=True)  # e.g. an email, for search results
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

Sharing scope — start coarse (category-level), not per-part, to keep the
opt-in decision low-friction (a real workshop has hundreds of parts; nobody's
toggling that many
individually):

```python
# On Category (inventory/models.py):
is_shareable = models.BooleanField(
    default=False,
    help_text="Visible to peers via network search. Off by default -- opt in per category.",
)
```

A part is network-searchable if `part.category.is_shareable` is true (parts
with no category are never shareable — safe default). If per-part exceptions
turn out to matter later, add `Part.share_override` (nullable bool: None =
inherit from category, True/False = explicit override) rather than redesigning
this from scratch.

### Inbound: the endpoint peers call into *your* instance

`GET /api/peer-search/?q=<query>` (machine-to-machine, not a session-login
route — same pattern as the existing `/api/locate/` voice-search endpoint in
`inventory/views/searching.py` (the `api_locate_part` view), which is a good
template to copy from directly).

- Auth: `X-Peer-Key` header, matched against `Peer.inbound_api_key`. No match
  → 403. This is a shared-secret model exactly like `LED_CONTROLLER_KEY` /
  `LABEL_PRINTER_KEY` elsewhere in this app — proportionate for the actual
  stakes here (no payment data, no PII beyond a contact note the owner chose
  to expose).
- Query: reuse `build_search_query` from `inventory/search.py`, but filter to
  `category__is_shareable=True` before anything else.
- Response: deliberately thin — enough to be useful, not enough to leak the
  whole inventory structure:
  ```json
  {
    "query": "raspberry pi zero",
    "matches": [
      {"name": "Raspberry Pi Zero W", "manufacturer": "Raspberry Pi Foundation",
       "quantity_summary": "have some", "category": "Electronics"}
    ]
  }
  ```
  Note **no exact quantity, no drawer/bin location, no barcode** — "have
  some" / "have a few" / "have none" (bucketed, not a precise count) is
  plenty for "is it worth asking," and doesn't hand a stranger your exact
  stock levels or your home's storage layout. Decide the exact bucketing;
  don't just dump `quantity_summary` from the existing internal helper
  as-is, since that one *is* precise.

### Outbound: searching your friends from your own instance

New page, **not** part of `/search/`: `/network-search/` (or similar name —
pick something that reads as clearly separate, e.g. "Search friends" in nav,
not grouped with "Search"). Deliberately a second, explicit step: type a
query, hit "Search friends," see aggregated results grouped by which peer
they came from, each with that peer's `contact_note`. Every result should
show a "not what you're looking for? contact them anyway" affordance too —
this is a lead, not an inventory listing, so don't over-index on precision.

Fan-out logic: loop over `Peer.objects.filter(active=True)`, `requests.get`
each one's `/api/peer-search/` with a short timeout (a slow/dead peer
shouldn't hang the whole search — use a small per-request timeout, e.g. 3-5s,
and don't let one failure block the others' results from showing).

### Managing peers

A plain admin-registered `Peer` model is enough for v1 (Django admin already
gives full CRUD) — don't build a custom UI for this unless the owner asks; the
volume here is "a handful of friends," not hundreds of rows.

The exchange flow when adding a friend (document this, don't build
tooling for it unless it turns out to be annoying in practice):
1. Both people generate an `inbound_api_key` for each other on their own
   instance (a Peer row with that key, `active=False` until confirmed).
2. They exchange, out of band (text message, email, in person), their
   instance's `base_url` and the `inbound_api_key` they just generated.
3. Each side flips their own `Peer.active = True` for the other once they've
   entered the other's URL + key as their own `outbound_api_key`.

## Explicitly out of scope for v1 (don't build these without the owner asking)

- Any in-app messaging between peers.
- Any notion of "request to purchase" beyond showing a contact method.
- Automatic/scheduled cross-instance sync or caching of peer inventories —
  always a live query at search time.
- Rate limiting / abuse detection on the inbound endpoint — fine for a
  handful of trusted peers; revisit if this ever needs to scale past the people
  an owner actually knows.
- Per-part sharing overrides — start category-level; only add finer control
  if category-level actually proves too coarse in practice.
- Anything resembling public peer discovery.

## Open questions for the implementer to decide (or ask the owner)

1. What exactly goes in `contact_note`? An email works simply but exposes it
   to whoever searches (only ever the owner's own added friends, so low risk —
   but confirm they're fine with that vs. something more indirect).
2. Exact wording/buckets for the fuzzy quantity ("have some" / "have a few" /
   etc.) — get this right so it's actually useful without being precise.
3. Should a dead/unreachable peer show an error inline in results, or just
   silently produce zero results from that peer? (Recommendation: a small,
   unobtrusive "couldn't reach <name>" note — silent failure makes debugging
   a friend's misconfigured instance much harder for both sides.)
4. Timeout tuning for the fan-out (how many peers is an owner actually likely to
   have — 2? 20? — affects whether sequential or concurrent requests matter).
5. Should `Category.is_shareable` changes need confirmation/a warning
   ("this exposes N parts to M active peers")? Given the low stakes here,
   probably not necessary, but worth a second thought before building.
