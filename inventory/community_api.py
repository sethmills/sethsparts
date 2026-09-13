"""Connecting two workshops, and what happens once they are connected.

The whole feature rests on one idea: **connections are the network**. There is no
central service. Your instance asks the workshops it is connected to whether they know
anyone nearby, and they pass on what they know. One connection is enough to start
seeing a map, and connecting to any other workshop keeps it working if one goes away.

Pairing happens in two directions, and the asymmetry matters:

* **The joiner starts it.** They have someone's short code and their address, so they
  call the host. Nothing has to be discovered or looked up.
* **The host answers with the key the joiner needs to call back.** Both sides end up
  holding exactly two credentials — one they issued, one they were issued — and
  neither side can act as the other.

The short code is the only unauthenticated write this feature accepts, so its
protection is single use and a 24-hour expiry rather than length. See `PairingCode`
for why that is enough.
"""
from __future__ import annotations

import requests
from django.db import transaction
from django.utils import timezone

from .archiving import USER_AGENT
from .models import Peer, PairingCode

TIMEOUT = 15

# A short code is read aloud or typed from a screen, so the failures worth naming are
# the ones a person can act on: wrong code, expired code, already used.
CODE_INVALID = "That code isn't valid. Codes are single-use and expire after 24 hours — ask for a fresh one."
CODE_MISSING = "No pairing code was given."
PEER_NAME_MAX = 200


def claim(code_text: str, *, name: str, base_url: str, public_key: str, callback_key: str) -> tuple[Peer | None, str]:
    """Host side: accept a joiner's connection request.

    Returns `(peer, error)`. The peer is created active — the joiner already proved
    they hold the code, which is the only thing the host needed to establish.

    Side by side with `join`, this is where the two credentials land: the joiner sends
    the key *they* issued to us, which becomes our `outbound_api_key`, and we issue one
    for them, which becomes their `outbound_api_key`. Neither side can sign as the
    other, and revoking is a matter of changing one row.
    """
    parsed = PairingCode.parse_display(code_text)
    if not parsed:
        return None, CODE_MISSING

    if not base_url or not public_key:
        return None, "That request didn't say where to reach it or who it is."

    with transaction.atomic():
        # Locked while we look, so the same code cannot be spent twice by two requests
        # arriving together — a single-use code that can be used twice is not single use.
        pairing = PairingCode.objects.select_for_update().filter(code=parsed).first()
        if pairing is None or not pairing.is_usable():
            return None, CODE_INVALID

        peer, created = Peer.objects.get_or_create(
            public_key=public_key,
            defaults={
                "name": (name or "").strip()[:PEER_NAME_MAX] or "A workshop",
                "base_url": base_url.strip(),
                "status": Peer.ACTIVE,
                # Pins only. Inventory access is a separate, per-person decision the
                # host makes deliberately, and it defaults off.
                "exchanges_pins": True,
                "shares_parts": False,
                "outbound_api_key": callback_key or "",
            },
        )
        if not created:
            # Reconnecting with a fresh code: update what we know, keep the permissions.
            peer.name = (name or "").strip()[:PEER_NAME_MAX] or peer.name
            peer.base_url = base_url.strip()
            peer.outbound_api_key = callback_key or peer.outbound_api_key
            peer.status = Peer.ACTIVE
            peer.save(update_fields=["name", "base_url", "outbound_api_key", "status"])

        pairing.claimed_at = timezone.now()
        pairing.claimed_by = peer
        pairing.save(update_fields=["claimed_at", "claimed_by"])

    return peer, ""


def join(host_url: str, code_text: str, *, my_name: str, my_url: str, my_public_key: str,
         my_callback_key: str) -> tuple[Peer | None, str]:
    """Joiner side: ask a host to connect to us.

    Creates the peer row only after the host has answered, so a failed attempt leaves
    no half-connected state to clean up.
    """
    host_url = (host_url or "").strip().rstrip("/")
    if not host_url:
        return None, "Give the address of the workshop you want to connect to."
    if "://" not in host_url:
        host_url = "http://" + host_url

    parsed = PairingCode.parse_display(code_text)
    if not parsed:
        return None, CODE_MISSING

    try:
        response = requests.post(
            f"{host_url}/api/community/claim/",
            json={
                "code": parsed,
                "name": my_name,
                "base_url": my_url,
                "public_key": my_public_key,
                # The key they should use to call us. Not a secret we are giving away —
                # it is the credential we issue *to them*.
                "callback_key": my_callback_key,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return None, f"Couldn't reach {host_url}: {exc}"

    if response.status_code == 404:
        return None, f"{host_url} doesn't look like this app."
    if response.status_code >= 400:
        try:
            detail = response.json().get("error")
        except ValueError:
            detail = None
        return None, detail or f"{host_url} refused the connection (HTTP {response.status_code})."

    try:
        payload = response.json()
    except ValueError:
        return None, f"{host_url} answered with something that wasn't JSON."

    peer = Peer.objects.create(
        name=(payload.get("name") or "").strip()[:PEER_NAME_MAX] or "A workshop",
        base_url=host_url,
        public_key=(payload.get("public_key") or "").strip(),
        inbound_api_key=my_callback_key,
        # The key *they* issued to us, which is what we send when calling them.
        outbound_api_key=(payload.get("callback_key") or "").strip(),
        status=Peer.ACTIVE,
        exchanges_pins=True,
        shares_parts=False,
    )
    return peer, ""


def my_callback_url(request) -> str:
    """Where peers should reach this instance.

    Prefers the address the owner saved during setup, because behind a tunnel the host
    header is whatever the proxy forwarded and may not be the public name. Falls back
    to the request's own host, which is right for a LAN-only install.
    """
    from .site_config import get_site_settings

    site = get_site_settings()
    saved = (site.public_url if site else "") or ""
    if saved:
        return saved.rstrip("/")
    scheme = "https" if request.is_secure() else "http"
    return f"{scheme}://{request.get_host()}"
