"""A small helper for recording audit events without ceremony at each call site.

Call sites do ``audit.log("stock.adjust", part=part, actor=request.user, before=1, after=5)``
and move on — no import juggling, no model plumbing. The event lands in `AuditEvent`
with the keyword args as its JSON payload.
"""
from __future__ import annotations

from .models import AuditEvent


def log(verb: str, *, part=None, actor=None, **payload) -> AuditEvent:
    return AuditEvent.objects.create(verb=verb, part=part, actor=actor, payload=payload)
