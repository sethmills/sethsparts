"""Searching connected workshops' parts, in both directions.

Two halves, one contract: a peer may only ever see the *shareable* subset of an
owner's inventory, and never a precise count or a location — just enough to answer
"is it worth asking". The inbound half serves that subset to a connected workshop
that holds the `shares_parts` permission; the outbound half asks each such workshop
and gathers their answers.

The trust boundary is the same shared-secret model as the rest of the community
feature — the `X-Api-Key` header matched against `Peer.inbound_api_key` over TLS.
Unlike a gossiped map pin, a search result is point-to-point (never relayed through
a third workshop), so there is nothing to sign; the shared secret plus TLS is the
whole trust model, exactly like `community_api.claim` and the peer search it enables.

The quantity a peer sees is deliberately **fuzzed** into three buckets. A peer has no
business knowing exact stock levels or which drawer holds what, and "some / a few /
none" is already plenty for deciding whether to ask.
"""
from __future__ import annotations

import secrets

import requests

from .archiving import USER_AGENT
from .models import Part, Peer
from .search import build_search_query

# A search fans out to every connection allowed to search parts. A slow or dead
# workshop must not hang the whole search, so each request gets a short, per-peer
# timeout; the plan's open question about fan-out timeouts is answered by "enough
# peers to matter is still small, so sequential is fine, and a tight per-peer cap
# keeps one bad neighbour from stalling the page."
SEARCH_TIMEOUT = 5

# Per peer, a lead is not a full listing. Cap it so one neighbour with a huge
# shareable category cannot dominate the results.
MAX_RESULTS = 50


def fuzz_quantity(quantities) -> str:
    """One of ``"some"`` / ``"a few"`` / ``"none"``, never a precise count.

    ``quantities`` is the list of a part's per-location quantities (each an int or
    ``None`` for "present but uncounted"). The buckets are deliberately coarse so a
    stranger learns only "is it worth asking", not the owner's stock level or which
    drawer holds what.
    """
    counted = [q for q in quantities if q is not None]
    if not counted:
        # Nothing was ever counted. Rows that exist at all mean the part is present
        # but unquantified ("some"); no rows at all means no stock recorded ("none").
        return "some" if quantities else "none"
    total = sum(counted)
    if total <= 0:
        return "none"
    if total < 5:
        return "a few"
    return "some"


def shareable_results(query):
    """The subset of this instance's parts a peer may see.

    Two filters, both required: the part's category must be marked shareable, and
    the part must match the query the same way local search would. A part with no
    category is never shareable — the default is private, and opting in is per
    category, never implied by anything else.
    """
    return (
        Part.objects.filter(category__is_shareable=True)
        .filter(build_search_query(query))
        .select_related("category")
        .prefetch_related("stock_items")
    )


def match_payload(part) -> dict:
    """A deliberately thin result: name, manufacturer, category, and a fuzzed
    quantity bucket. No exact count, no drawer/bin, no barcode — the location and
    stock levels belong to the owner, and a stranger has no business with them."""
    return {
        "name": part.name,
        "manufacturer": part.manufacturer,
        "category": part.category.name if part.category else "",
        "quantity_summary": fuzz_quantity([si.quantity for si in part.stock_items.all()]),
    }


def peer_for_search(request):
    """The active peer allowed to search this instance's parts, or None.

    Same timing-safe compare as the pins endpoint's `peer_for_request`, but gated on
    `shares_parts` rather than `exchanges_pins`. The two capabilities are separate on
    purpose — a connection made for the map has no business searching inventory —
    and so the two checks are separate functions rather than one with a parameter.
    """
    supplied = request.headers.get("X-Api-Key", "")
    if not supplied:
        return None
    for peer in Peer.objects.filter(status=Peer.ACTIVE, shares_parts=True):
        if peer.inbound_api_key and secrets.compare_digest(supplied, peer.inbound_api_key):
            return peer
    return None


def search_peers(query):
    """Ask every connection allowed to search parts. Returns ``(results, notes)``.

    Each result is a dict with the peer, its name, its contact note, and the matches
    it answered with. A dead or misconfigured peer produces a note rather than
    failing the whole search — one workshop being offline must not hide what the
    others answered.
    """
    results = []
    notes = []
    peers = list(Peer.objects.filter(status=Peer.ACTIVE, shares_parts=True))
    for peer in peers:
        try:
            response = requests.get(
                f"{peer.base_url.rstrip('/')}/api/community/peer-search/",
                params={"q": query},
                headers={"X-Api-Key": peer.outbound_api_key, "User-Agent": USER_AGENT},
                timeout=SEARCH_TIMEOUT,
            )
        except requests.RequestException as exc:
            notes.append(f"{peer.name}: {exc}")
            continue
        if response.status_code >= 400:
            notes.append(f"{peer.name}: HTTP {response.status_code}")
            continue
        try:
            payload = response.json()
        except ValueError:
            notes.append(f"{peer.name}: answered with something that wasn't JSON")
            continue
        results.append(
            {
                "peer": peer,
                "name": peer.name,
                "contact_note": peer.contact_note,
                "matches": payload.get("matches") or [],
            }
        )
    return results, notes
