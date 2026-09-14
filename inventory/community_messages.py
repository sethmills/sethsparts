"""One-to-one messages between connected workshops, and blocking.

Messaging rides on the connection: any *active* peer may message you — connecting is
the consent, so there is no separate message permission to toggle. Delivery is
point-to-point over the same shared-secret key as everything else, and a blocked peer
is not active, so blocking cuts messaging, search, and pins at once.

The one difference between blocking and a plain disconnect is stickiness: a revoked
connection can reconnect with a fresh pairing code, but a *blocked* one is refused by
`community_api.claim` until explicitly unblocked. Without that, "block" would last only
until the next code reached the harasser.

Delivery is "attempt now, retry by hand". There is no queue: if the other workshop is
unreachable, the message is stored as unsent and the sender is told to retry. The
`remote_id` carried on each message makes a retry idempotent — the receiver answers
"already have it" rather than storing the same message twice.
"""
from __future__ import annotations

import secrets

import requests

from .archiving import USER_AGENT
from .models import Message, Peer

TIMEOUT = 15


def new_remote_id() -> str:
    return secrets.token_hex(16)


def peer_for_messages(request):
    """The active peer this message is from, or None.

    Unlike the pins and search endpoints there is no capability flag to check — any
    active connection may message. The filter on `status=ACTIVE` is what makes blocking
    (which sets `REVOKED`) cut messaging off at the same stroke as everything else.
    """
    supplied = request.headers.get("X-Api-Key", "")
    if not supplied:
        return None
    for peer in Peer.objects.filter(status=Peer.ACTIVE):
        if peer.inbound_api_key and secrets.compare_digest(supplied, peer.inbound_api_key):
            return peer
    return None


def receive(peer, remote_id, body) -> bool:
    """Store a message a peer sent us. Returns True only if it was new.

    The `remote_id` makes retries idempotent: a delivery that actually landed (but whose
    response was lost) is recognised and not stored a second time.
    """
    body = (body or "").strip()
    remote_id = (remote_id or "").strip()
    if not body:
        return False
    if remote_id and Message.objects.filter(
        peer=peer, direction=Message.INBOUND, remote_id=remote_id
    ).exists():
        return False
    Message.objects.create(
        peer=peer, direction=Message.INBOUND, body=body, remote_id=remote_id, read=False
    )
    return True


def send(peer, body) -> tuple[bool, str]:
    """Send a message to a peer now. Returns `(delivered, error)`.

    The message is stored as outbound *before* the push, so a failed delivery is still
    in the thread for the owner to see and retry — never silently dropped.
    """
    body = (body or "").strip()
    if not body:
        return False, "A message can't be empty."
    remote_id = new_remote_id()
    message = Message.objects.create(
        peer=peer, direction=Message.OUTBOUND, body=body, remote_id=remote_id, delivered=False
    )
    ok, error = _push(peer, remote_id, body)
    if ok:
        message.delivered = True
        message.save(update_fields=["delivered"])
    return ok, error


def retry(message) -> tuple[bool, str]:
    """Re-attempt an outbound message that never landed."""
    ok, error = _push(message.peer, message.remote_id, message.body)
    if ok:
        message.delivered = True
        message.save(update_fields=["delivered"])
    return ok, error


def _push(peer, remote_id, body) -> tuple[bool, str]:
    try:
        response = requests.post(
            f"{peer.base_url.rstrip('/')}/api/community/messages/",
            json={"remote_id": remote_id, "body": body},
            headers={"X-Api-Key": peer.outbound_api_key, "User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"Couldn't deliver to {peer.name}: {exc}"
    if response.status_code >= 400:
        return False, f"{peer.name} refused the message (HTTP {response.status_code})."
    return True, ""
