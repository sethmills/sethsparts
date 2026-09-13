"""The map's data: this instance's own pin, and the pins it has heard from others.

Pins travel the way `docs/PLAN_community_sharing.md` §6 describes: you ask the workshops
you are connected to what they know, they answer with signed entries, and you pass on what
you know to anyone who asks. There is no central service, and the network *is* the
connections — which is why one connection is enough to start seeing a map, and why
connecting to any other workshop keeps it working if one goes away.

Three rules do all the work:

* **Newest valid signed entry per key wins.** A pin is signed by the instance that
  published it, so a relay can verify what it forwards without being able to alter it. An
  older entry arriving late — because someone's copy is stale, or because it was replayed
  on purpose — is simply not newer, and is ignored.
* **A removal is a newer signed entry, not a missing one.** Opting out publishes an
  "I'm gone" entry that every holder acts on by deleting the location. Deleting the row
  outright would have been simpler and wrong: the next stale copy to arrive would
  resurrect a workshop that had asked to be forgotten.
* **Nothing here runs during a page render.** Pins arrive when the owner presses the
  button or a scheduled command runs, the same discipline as the update check. A page
  that quietly makes outbound requests to other people's servers is a surprise, and it
  makes the page depend on several strangers being up.

Coordinates are coarse by construction — postcode-area level only, never the owner's full
postcode — because that is what the geocoder stores (`CommunityProfile`). Nothing in this
module rounds or fuzzes anything; being able to say "we never held the precise location" is
stronger than "we held it and then obscured it".
"""
from __future__ import annotations

import secrets
from datetime import timedelta, timezone as datetime_timezone

import requests
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .archiving import USER_AGENT
from .community import make_pin, verify_pin
from .models import CommunityIdentity, CommunityProfile, KnownPin, Peer
from .site_config import country

TIMEOUT = 15

# How far a pin may travel. Gossip with no limit is an unbounded broadcast, and "a
# workshop three connections away" is already further than the feature promises — the
# map is for finding someone near enough to visit, not for covering a country.
MAX_HOPS = 3

# How long an entry stays useful. An abandoned instance should not sit on the map for
# ever, and this bounds what a node stores. Tombstones expire on the same clock, which is
# a deliberate limitation: a six-month-old removal could in principle be followed by a
# replay of the pin it revoked. Everything a node holds from that workshop has expired by
# then too, so the replay would need a relay that ignored its own expiry — and letting
# removals accumulate for ever is the thing this feature cannot afford.
PIN_MAX_AGE_DAYS = 180

# Outcomes of taking in a pin, named rather than boolean so callers and tests can tell
# "ignored because it is old" from "ignored because it was forged".
INVALID = "invalid"
STALE = "stale"
STORED = "stored"
REMOVED = "removed"
OWN = "own"


def own_pin() -> dict | None:
    """This instance's signed pin, or None when it is not discoverable.

    Published **anonymous**, with an empty name, even when the owner set a display name.
    A pin is gossiped to the whole network, so a name inside it would leak to strangers —
    whereas the name a *connection* sees comes from the peer row, which only ever went to
    the person the owner told. Same reasoning as the permission split: what the network
    sees and what a connection sees are different things.
    """
    profile = CommunityProfile.load()
    if not profile.can_publish:
        return None
    identity = CommunityIdentity.load()
    return make_pin(
        identity.private_key,
        lat=profile.location_lat,
        lon=profile.location_lon,
        country=country(),
        name="",
    )


def own_gone_pin() -> dict | None:
    """This instance's signed "I'm gone" entry, or None if there was never a pin.

    Requires coordinates for the same reason `own_pin` does: without them no pin was ever
    published, so there is nothing to revoke. The coordinates stay in the signed payload —
    that is what makes the removal a newer statement *about the same entry* rather than a
    different shape of message — and the receiving node deletes them on arrival.
    """
    profile = CommunityProfile.load()
    if not profile.has_location:
        return None
    identity = CommunityIdentity.load()
    return make_pin(
        identity.private_key,
        lat=profile.location_lat,
        lon=profile.location_lon,
        country=country(),
        name="",
        gone=True,
    )


def current_statement() -> dict | None:
    """What this instance currently tells the network about itself."""
    if CommunityProfile.load().discoverable:
        return own_pin()
    return own_gone_pin()


def remember(pin, *, hops: int = 0) -> str:
    """Take in one pin from a peer. Returns one of the outcome constants above.

    Verification comes first and is the only thing standing between the network and a
    forged pin, so it is not optional or "best effort": an entry that does not verify is
    dropped without ever reaching the database.
    """
    if not isinstance(pin, dict) or not verify_pin(pin):
        return INVALID

    key = pin.get("public_key", "")
    if key == CommunityIdentity.load().public_key:
        # Our own pin, relayed back to us. The map draws this instance's pin from its own
        # profile, so storing a second copy would double it up on the map.
        return OWN

    signed_at = parse_datetime(pin.get("updated_at", "") or "")
    if signed_at is None:
        return INVALID
    if timezone.is_naive(signed_at):
        # A peer sending a naive timestamp is not attacking anything; it is just wrong
        # about the format. Reading it as UTC is the kind interpretation of a
        # well-formed-but-unqualified time.
        signed_at = timezone.make_aware(signed_at, datetime_timezone.utc)

    gone = bool(pin.get("gone", False))

    with transaction.atomic():
        existing = KnownPin.objects.select_for_update().filter(public_key=key).first()
        if existing is not None and signed_at <= existing.signed_at:
            # The heart of "newest wins". This is also the check that makes a removal
            # stick: the tombstone is newer than the pin, so the pin cannot come back.
            return STALE

        KnownPin.objects.update_or_create(
            public_key=key,
            defaults={
                # A removal keeps the row and loses the data. Storing coordinates with a
                # "hidden" flag would leave the thing the owner asked us to delete sitting
                # on disk.
                "lat": None if gone else float(pin["lat"]),
                "lon": None if gone else float(pin["lon"]),
                "country": "" if gone else (pin.get("country") or "").upper(),
                "name": "" if gone else (pin.get("name") or ""),
                "gone": gone,
                "signed_at": signed_at,
                "signature": pin.get("signature", ""),
                "pin_version": int(pin.get("v")),
                "hops": max(0, min(int(hops or 0), MAX_HOPS)),
            },
        )
    return REMOVED if gone else STORED


def known_pins():
    """Every entry this node holds, removed ones included — they are not shown, but they
    are what stops an old pin coming back."""
    return KnownPin.objects.all()


def map_pins():
    """The pins worth drawing: ones with a surviving location, newest first."""
    return KnownPin.objects.filter(gone=False, lat__isnull=False, lon__isnull=False)


def pins_for_sharing() -> list[dict]:
    """Everything this instance knows, in a shape a peer can verify.

    Tombstones go out too, and that *is* the mechanism: a removal only reaches workshops
    that did not hear it directly by being passed along like any other entry.

    Entries already at the hop limit are dropped rather than forwarded, which is what
    turns an unbounded broadcast into a bounded one. The limit is applied here, on the
    way out, so a node that learns a pin can still serve it to its own neighbours.

    The version travels with the entry because it is inside the signed bytes: re-serving
    a pin under a different version number would invalidate its own signature.
    """
    shared = []
    for row in KnownPin.objects.filter(hops__lt=MAX_HOPS):
        entry = {
            "v": row.pin_version,
            "public_key": row.public_key,
            "gone": row.gone,
            "updated_at": _stamp(row.signed_at),
            "signature": row.signature,
            "hops": row.hops,
        }
        if not row.gone:
            entry.update(
                {
                    "lat": f"{row.lat:.6f}",
                    "lon": f"{row.lon:.6f}",
                    "country": row.country,
                    "name": row.name,
                }
            )
        shared.append(entry)
    return shared


def _stamp(value) -> str:
    """A datetime back into the exact string form the signature was made over.

    The signature covers `updated_at` as a UTC ISO string ending in Z, so re-serving a
    stored pin means producing that same string. Getting it slightly different — a
    "+00:00" instead of "Z", or a different number of fractional digits — would invalidate
    a perfectly good signature at the far end.
    """
    return value.astimezone(datetime_timezone.utc).isoformat().replace("+00:00", "Z")


def peer_for_request(request):
    """The active peer this request is from, or None.

    `secrets.compare_digest` rather than `==`: an equality test that returns early leaks
    its answer through timing, which is a free oracle for guessing a credential. The
    filter is deliberately narrow — active *and* allowed to exchange pins — so that
    revoking a connection stops it reaching this endpoint too, and a connection made for
    inventory reasons has no business reading the map.
    """
    supplied = request.headers.get("X-Api-Key", "")
    if not supplied:
        return None
    for peer in Peer.objects.filter(status=Peer.ACTIVE, exchanges_pins=True):
        if peer.inbound_api_key and secrets.compare_digest(supplied, peer.inbound_api_key):
            return peer
    return None


def sync_from_peers() -> tuple[int, list[str]]:
    """Ask every connection that exchanges pins what it knows. Returns (new entries, notes).

    Only connections with `exchanges_pins` are asked. The two capabilities are separate on
    purpose, and a connection made so two people can search each other's parts must not
    start gossiping their location.
    """
    learned = 0
    notes = []
    peers = list(Peer.objects.filter(status=Peer.ACTIVE, exchanges_pins=True))

    for peer in peers:
        try:
            response = requests.get(
                f"{peer.base_url.rstrip('/')}/api/community/pins/",
                headers={"X-Api-Key": peer.outbound_api_key, "User-Agent": USER_AGENT},
                timeout=TIMEOUT,
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

        for pin in payload.get("pins") or []:
            incoming = dict(pin) if isinstance(pin, dict) else {}
            # One more hop than it had where it came from. Done here rather than trusted
            # from the payload: a relay's own count is transport metadata, and a node that
            # under-reported it would defeat the limit.
            verdict = remember(incoming, hops=int(incoming.get("hops", 0) or 0) + 1)
            if verdict in (STORED, REMOVED):
                learned += 1

    return learned, notes


def publish_own_state() -> tuple[bool, str]:
    """Push this instance's current statement to every pin-exchanging connection.

    Called when the owner changes discoverability, so an opt-out actually reaches the
    nodes holding the pin rather than waiting for them to ask. Best effort on purpose: one
    peer being offline must not stop the owner switching their own pin off, and every
    change re-sends the whole statement anyway.
    """
    statement = current_statement()
    if statement is None:
        return False, "Nothing to publish yet — set a location first."

    peers = list(Peer.objects.filter(status=Peer.ACTIVE, exchanges_pins=True))
    if not peers:
        return False, "No connections exchange pins yet, so there is nobody to tell."

    delivered = 0
    for peer in peers:
        try:
            response = requests.post(
                f"{peer.base_url.rstrip('/')}/api/community/pins/",
                json=statement,
                headers={"X-Api-Key": peer.outbound_api_key, "User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue
        if response.status_code < 400:
            delivered += 1

    verb = "removal" if statement.get("gone") else "pin"
    return True, f"Sent your {verb} to {delivered} of {len(peers)} connection(s)."


def prune_stale_pins() -> int:
    """Drop entries nobody has refreshed for `PIN_MAX_AGE_DAYS`."""
    cutoff = timezone.now() - timedelta(days=PIN_MAX_AGE_DAYS)
    deleted, _ = KnownPin.objects.filter(signed_at__lt=cutoff).delete()
    return deleted
