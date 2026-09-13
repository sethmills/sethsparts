"""The community pages, and the one endpoint peers call.

`/api/community/claim/` is the only unauthenticated write in the whole app apart from
the setup wizard's account step, so it is guarded by three things rather than one: the
code must exist, it must be unspent and unexpired, and the endpoint is rate-limited
per caller. The code itself is the credential — see `PairingCode` for why 40 bits is
enough when it is single-use and lasts a day.
"""
from __future__ import annotations

import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .. import community_api, community_pins
from ..models import CommunityIdentity, CommunityProfile, PairingCode, Peer, PeerSearchLog
from ..site_config import country, site_name

# Where the map's tiles and styling come from. OpenFreeMap needs no key, no account and
# no cookies, and its production setup is open source so an operator can self-host it --
# which is why it is the default rather than a service tied to a billing account. It is a
# setting so an operator can point at their own without waiting for a software update.
MAP_STYLE_URL = "https://tiles.openfreemap.org/styles/dark"

# Enough attempts to survive a person mistyping a code; not enough to make guessing
# worthwhile. The real protection is single use plus expiry.
CLAIM_ATTEMPTS = 20
CLAIM_WINDOW_SECONDS = 600


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _claim_rate_limited(request) -> bool:
    key = f"community:claim:{_client_ip(request)}"
    attempts = cache.get(key, 0)
    if attempts >= CLAIM_ATTEMPTS:
        return True
    cache.set(key, attempts + 1, CLAIM_WINDOW_SECONDS)
    return False


# --- The endpoint peers call -------------------------------------------------


@csrf_exempt
def api_community_pins(request):
    """Exchange pins with a connected workshop.

    GET hands over what this instance knows — its own pin, and the entries it holds to
    pass on. POST is how a peer gives us its current entry, which is what makes an opt-out
    travel *outwards* immediately instead of waiting for its neighbours to ask again.

    Authenticated by the per-peer key this instance issued, which is why this is not a
    login-walled page: the caller is another server. `csrf_exempt` for the same reason as
    the claim endpoint — CSRF protects browsers, and there is no browser here.
    """
    peer = community_pins.peer_for_request(request)
    if peer is None:
        return JsonResponse(
            {"error": "Not a connected workshop, or pins aren't exchanged with you."}, status=403
        )

    if request.method == "GET":
        Peer.objects.filter(pk=peer.pk).update(last_seen_at=timezone.now())
        pins = community_pins.pins_for_sharing()
        own = community_pins.own_pin()
        if own is not None:
            # hops 0: we are the origin of this one. The receiver adds 1 as it stores it,
            # which is what keeps the limit meaning something.
            pins.insert(0, {**own, "hops": 0})
        return JsonResponse({"pins": pins})

    if request.method == "POST":
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"error": "That wasn't JSON."}, status=400)

        verdict = community_pins.remember(payload, hops=int(payload.get("hops", 0) or 0) + 1)
        if verdict == community_pins.INVALID:
            return JsonResponse({"error": "That pin doesn't verify."}, status=400)
        return JsonResponse({"ok": True, "verdict": verdict})

    return JsonResponse({"error": "Unsupported method."}, status=405)


@csrf_exempt
@require_POST
def api_community_claim(request):
    """Accept a connection request from another workshop.

    Unauthenticated by design: there is nothing to authenticate with yet, which is
    exactly what the pairing code is for. `csrf_exempt` because the caller is another
    server with no session and no cookie — CSRF protects browsers, and there is no
    browser here.
    """
    import json

    if _claim_rate_limited(request):
        return JsonResponse({"error": "Too many attempts. Try again shortly."}, status=429)

    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "That wasn't JSON."}, status=400)

    peer, error = community_api.claim(
        payload.get("code", ""),
        name=payload.get("name", ""),
        base_url=payload.get("base_url", ""),
        public_key=payload.get("public_key", ""),
        callback_key=payload.get("callback_key", ""),
    )
    if peer is None:
        return JsonResponse({"error": error}, status=400)

    identity = CommunityIdentity.load()
    return JsonResponse(
        {
            "name": site_name(),
            "public_key": identity.public_key,
            # The credential we issue to them, so they can call us back. It is not a
            # secret being leaked — it is the point of this exchange.
            "callback_key": peer.inbound_api_key,
        }
    )


# --- Pages -------------------------------------------------------------------


@login_required
def community_map(request):
    """The map: your own pin, and the pins your connections have told you about.

    Deliberately makes **no outbound requests**. Pins arrive when someone presses the
    refresh button or when the scheduled command runs, so this page is instant, works
    offline, and does not announce this instance to every peer it knows merely because
    somebody opened it. Same rule as the update check, for the same reasons.
    """
    profile = CommunityProfile.load()
    names_by_key = {p.public_key: p.name for p in Peer.objects.filter(status=Peer.ACTIVE)}

    pins = []
    for row in community_pins.map_pins():
        known = row.public_key in names_by_key
        if known:
            # The only name that can appear on a pin is one the owner already has, from
            # their own list of connections. It is escaped because that name arrived over
            # the network from another instance.
            popup = f"<strong>{escape(names_by_key[row.public_key])}</strong><br>A connected workshop."
        else:
            popup = (
                "A workshop near here.<br>"
                "Nothing else is shared until you both agree to connect."
            )
        pins.append(
            {"lat": row.lat, "lon": row.lon, "kind": "friend" if known else "other", "popup": popup}
        )

    own = None
    if profile.can_publish:
        own = {
            "lat": profile.location_lat,
            "lon": profile.location_lon,
            "kind": "you",
            "popup": "Your pin.<br>Anonymous: no name, no parts, no address.",
        }
        pins.append(own)

    # Centre on your own pin when there is one; otherwise on a pin you have learned about.
    # With no pins at all the template shows an explanation instead of an empty map frame.
    centre = own or (pins[0] if pins else None)

    return render(
        request,
        "inventory/community/map.html",
        {
            "pins_json": json.dumps(
                {
                    "pins": pins,
                    "own": bool(own),
                    "center": {
                        "lat": (centre or {}).get("lat", 0.0),
                        "lon": (centre or {}).get("lon", 0.0),
                        "zoom": 11 if own else 6,
                    },
                }
            ),
            "map_style_url": getattr(settings, "COMMUNITY_MAP_STYLE", MAP_STYLE_URL),
            "own_pin": own,
            "discoverable": profile.discoverable,
            "pin_count": len(pins),
            "pins_from_others": len(pins) - (1 if own else 0),
            "has_pin_neighbours": bool(names_by_key),
        },
    )


@login_required
@require_POST
def community_sync_pins(request):
    """Ask each pin-exchanging connection what it knows, and take in what is new.

    A button rather than something the map does on load: the page must not depend on
    other people's servers being up, and opening a page should not reach out to anyone.
    """
    if not Peer.objects.filter(status=Peer.ACTIVE, exchanges_pins=True).exists():
        messages.error(request, "No connections exchange pins yet — connect to a workshop first.")
        return redirect("inventory:community_map")

    learned, notes = community_pins.sync_from_peers()
    if learned:
        messages.success(request, f"Learned {learned} new pin entr{'y' if learned == 1 else 'ies'}.")
    else:
        messages.success(request, "Nothing new — you already know what your connections know.")
    for note in notes:
        messages.error(request, note)
    return redirect("inventory:community_map")


@login_required
def community_connections(request):
    site = CommunityProfile.load()
    return render(
        request,
        "inventory/community/connections.html",
        {
            "profile": site,
            "peers": Peer.objects.all().order_by("name"),
            "recent_searches": PeerSearchLog.objects.select_related("peer")[:20],
            "my_url": community_api.my_callback_url(request),
            "has_location": site.has_location,
        },
    )


@login_required
@require_POST
def community_issue_code(request):
    """Mint a one-time code to read out to someone.

    Any code still outstanding is discarded first. Leaving several live would mean the
    owner reading out a code they issued ten minutes ago and wondering why it fails,
    and there is no reason to need more than one at a time.
    """
    PairingCode.objects.filter(claimed_at__isnull=True).delete()
    code = PairingCode.issue()
    messages.success(request, f"Read this out: {code.display} — it works once, for 24 hours.")
    return redirect("inventory:community_connections")


@login_required
@require_POST
def community_join(request):
    """Connect to another workshop using their code and address."""
    from ..models import new_api_key

    identity = CommunityIdentity.load()
    # Minted directly rather than by creating a throwaway Peer to borrow its default —
    # that would leave a junk row behind every time somebody mistyped a code.
    callback_key = new_api_key()

    peer, error = community_api.join(
        request.POST.get("host_url", ""),
        request.POST.get("code", ""),
        my_name=site_name(),
        my_url=community_api.my_callback_url(request),
        my_public_key=identity.public_key,
        my_callback_key=callback_key,
    )
    if peer is None:
        messages.error(request, error)
    else:
        messages.success(request, f"Connected to {peer.name}.")
    return redirect("inventory:community_connections")


@login_required
@require_POST
def community_update_peer(request, pk):
    """Change what a connected workshop may do, or what it is called.

    The two capabilities are edited separately and deliberately: `exchanges_pins` is
    about the map, `shares_parts` is about inventory, and ticking one must never
    imply the other.
    """
    peer = get_object_or_404(Peer, pk=pk)
    peer.exchanges_pins = bool(request.POST.get("exchanges_pins"))
    peer.shares_parts = bool(request.POST.get("shares_parts"))
    name = (request.POST.get("name") or "").strip()
    if name:
        peer.name = name[:community_api.PEER_NAME_MAX]
    peer.save(update_fields=["exchanges_pins", "shares_parts", "name"])
    messages.success(request, f"Updated {peer.name}.")
    return redirect("inventory:community_connections")


@login_required
@require_POST
def community_revoke(request, pk):
    """Disconnect. Kept rather than deleted so the search log keeps its subject.

    A revoked peer is never contacted and its key is never honoured again, which is
    what revoking has to mean — the row surviving is for the audit trail, not for
    access.
    """
    peer = get_object_or_404(Peer, pk=pk)
    peer.status = Peer.REVOKED
    peer.shares_parts = False
    peer.exchanges_pins = False
    peer.save(update_fields=["status", "shares_parts", "exchanges_pins"])
    messages.success(request, f"Disconnected from {peer.name}. They can no longer reach you or search your parts.")
    return redirect("inventory:community_connections")


@login_required
@require_POST
def community_forget(request, pk):
    """Remove a revoked connection entirely, including its search log."""
    peer = get_object_or_404(Peer, pk=pk)
    name = peer.name
    peer.delete()
    messages.success(request, f"Removed {name} and everything recorded about them.")
    return redirect("inventory:community_connections")
