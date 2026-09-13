"""The community pages, and the one endpoint peers call.

`/api/community/claim/` is the only unauthenticated write in the whole app apart from
the setup wizard's account step, so it is guarded by three things rather than one: the
code must exist, it must be unspent and unexpired, and the endpoint is rate-limited
per caller. The code itself is the credential — see `PairingCode` for why 40 bits is
enough when it is single-use and lasts a day.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .. import community_api
from ..models import CommunityIdentity, CommunityProfile, PairingCode, Peer, PeerSearchLog
from ..site_config import country, site_name

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
