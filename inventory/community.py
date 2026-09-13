"""Community sharing primitives: instance identity, pin signing, canonical encoding.

**Why signing at all.** A map pin gets relayed from instance to instance, so it
must be verifiable by workshops that have never met the one that published it. A
shared secret cannot do that — every verifier would need the publisher's secret,
which means every relay could forge pins. An Ed25519 signature means any instance
can *check* a pin it forwards without being able to *invent* one.

**Why not a blockchain.** Signatures plus timestamps give authentication and
freshness, which is all this needs. A chain adds consensus (expensive, and it
requires nodes to run chain software) and, decisively, immutability — an
append-only ledger cannot honour the erasure the rest of this feature promises,
because a "removed" pin would still exist on every node forever. See
`docs/PLAN_community_sharing.md` §7.

This module is deliberately free of Django models and database access, so every
rule below can be tested as a plain function.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# Bump only for an incompatible change to the canonical payload. It is inside the
# signed bytes, so a v1 instance will not silently accept a v2 pin.
PIN_VERSION = 1

# Versions this build knows how to read. A pin declaring anything else is rejected
# outright rather than guessed at.
SUPPORTED_PIN_VERSIONS = frozenset({PIN_VERSION})

# Coordinates are encoded as fixed-precision STRINGS, never JSON numbers. Floats
# can round-trip differently between platforms and Python versions, and the
# signature is over these exact bytes — a number that serialises differently on
# the verifier's machine would fail verification for no real reason.
COORD_DECIMALS = 6


def generate_keypair() -> tuple[str, str]:
    """A fresh instance identity. Returns ``(private_hex, public_hex)``, 64 chars each."""
    private = Ed25519PrivateKey.generate()
    return private.private_bytes_raw().hex(), private.public_key().public_bytes_raw().hex()


def public_from_private(private_hex: str) -> str:
    """Recover the public half from a stored private key."""
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex)).public_key().public_bytes_raw().hex()


def sign(private_hex: str, payload: bytes) -> str:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex)).sign(payload).hex()


def verify(public_hex: str, payload: bytes, signature_hex: str) -> bool:
    """True only for a well-formed signature over exactly these bytes.

    Returns False rather than raising: a malformed key or signature from a remote
    instance is expected input, not an error condition.
    """
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(
            bytes.fromhex(signature_hex), payload
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _coord(value) -> str:
    """Fixed-precision string form of a coordinate, so the signed bytes are stable."""
    return f"{float(value):.{COORD_DECIMALS}f}"


def canonical_pin(
    *,
    public_key: str,
    lat,
    lon,
    country: str = "",
    name: str = "",
    updated_at: str,
    v: int = PIN_VERSION,
) -> bytes:
    """The exact bytes a pin's signature covers.

    Deterministic by construction: sorted keys, no insignificant whitespace, ASCII
    preserved, coordinates as fixed-precision strings. The signature is over this,
    so any change to how a field is encoded is a breaking change to the format —
    which is what ``PIN_VERSION`` is for.

    ``v`` is a parameter rather than the module constant on purpose. If this always
    signed the *current* version, the ``v`` field in the pin would be unauthenticated
    — a relay could rewrite it in transit and the signature would still check out.
    The verifier passes the version the pin claims, so changing it breaks the
    signature; and ``verify_pin`` separately refuses versions it does not know.

    ``name`` is included because it is part of what the owner chose to publish, and
    an unsigned name could be swapped in transit. It is empty unless the owner set
    one; the map shows anonymous pins by default.
    """
    payload = {
        "v": v,
        "public_key": public_key,
        "lat": _coord(lat),
        "lon": _coord(lon),
        "country": (country or "").upper(),
        "name": name or "",
        "updated_at": updated_at,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def make_pin(private_hex: str, *, lat, lon, country="", name="", updated_at=None) -> dict:
    """Build a signed pin for this instance.

    ``updated_at`` defaults to now in UTC. It is the owner's clock, so a peer must
    not trust it blindly for *freshness* — but it must be inside the signed bytes,
    or an old pin could be replayed as new.
    """
    public_hex = public_from_private(private_hex)
    if updated_at is None:
        updated_at = datetime.now(timezone.utc)
    stamp = updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    body = canonical_pin(
        public_key=public_hex, lat=lat, lon=lon, country=country, name=name, updated_at=stamp
    )
    return {
        "v": PIN_VERSION,
        "public_key": public_hex,
        "lat": _coord(lat),
        "lon": _coord(lon),
        "country": (country or "").upper(),
        "name": name or "",
        "updated_at": stamp,
        "signature": sign(private_hex, body),
    }


def verify_pin(pin: dict) -> bool:
    """Check a pin someone handed us, including one relayed from a third party.

    Everything needed is in the pin itself, which is the point: a relay can verify
    what it forwards without holding anyone's secret, and cannot alter a field
    without invalidating the signature.

    Two checks, deliberately separate: the claimed version must be one this build
    understands, *and* the signature must cover that claimed version. Doing only the
    second would let a relay relabel a pin; doing only the first would accept any
    bytes with a valid-looking signature.
    """
    version = pin.get("v")
    if version not in SUPPORTED_PIN_VERSIONS:
        return False
    try:
        body = canonical_pin(
            public_key=pin["public_key"],
            lat=pin["lat"],
            lon=pin["lon"],
            country=pin.get("country", ""),
            name=pin.get("name", ""),
            updated_at=pin["updated_at"],
            v=version,
        )
    except (KeyError, TypeError, ValueError):
        return False
    return verify(pin["public_key"], body, pin.get("signature", ""))
