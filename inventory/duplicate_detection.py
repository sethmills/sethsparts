"""Suggest existing parts that a new part name might duplicate.

Runs on the add-part path so the owner sees "you may already have this" before
accidentally creating a second entry for the same physical part. No runtime AI —
just normalized-name matching plus token overlap and fuzzy string similarity,
which catches "M3 bolt" vs "M3 bolts" and "10k resistor" vs "10K Resistor".
"""

import re
from difflib import get_close_matches

from .models import Part

# Below this similarity two whole names are treated as likely the same part.
FUZZY_CUTOFF = 0.87
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set:
    return set(_TOKEN_RE.findall(s.lower()))


def find_duplicate_parts(name, limit=6):
    """Return ``[(part_id, display_name), ...]`` that look like duplicates of
    ``name``, most likely first. Empty when nothing plausibly matches."""
    normalized = (name or "").strip().lower()
    if not normalized:
        return []

    # One scan of the whole inventory is fine for a self-hosted workshop (hundreds
    # to low thousands of parts) and keeps the matching logic easy to reason about.
    rows = list(Part.objects.order_by("name").values_list("id", "name", "normalized_name"))
    by_norm = {}
    for pid, display, norm in rows:
        norm = (norm or "").strip().lower()
        if norm:
            by_norm.setdefault(norm, (pid, display))

    # Exact match (the same normalization the model stores) wins outright.
    if normalized in by_norm:
        pid, display = by_norm[normalized]
        return [(pid, display)]

    new_tokens = _tokens(normalized)
    scored = []  # (pid, display, score)
    if new_tokens:
        for norm, (pid, display) in by_norm.items():
            ex_tokens = _tokens(norm)
            if not ex_tokens:
                continue
            # Token overlap: one name's words are all present in the other — e.g.
            # "m3 bolt 10mm" vs "m3 bolt", or "led" vs "led strip". Strong signal.
            if ex_tokens.issubset(new_tokens) or new_tokens.issubset(ex_tokens):
                scored.append((pid, display, 1.0))

    # Fuzzy: near-identical strings (plurals, spacing, word order, typos).
    if len(normalized) >= 4:
        for close in get_close_matches(normalized, list(by_norm.keys()), n=limit, cutoff=FUZZY_CUTOFF):
            scored.append((*by_norm[close], 0.9))

    scored.sort(key=lambda t: -t[2])
    result, seen = [], set()
    for pid, display, _ in scored:
        if pid in seen:
            continue
        seen.add(pid)
        result.append((pid, display))
        if len(result) >= limit:
            break
    return result
