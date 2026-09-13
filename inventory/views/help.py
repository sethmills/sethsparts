"""In-app help.

Written for someone who has never seen this app before, and organised around what
they are trying to do rather than around how the code is arranged.

The page on laying out a workshop is the one that earns its place. The app will
happily let you put every part in one drawer, and then finding anything is miserable —
that's a real trap, and nothing in the interface warns you about it. Advice about
organisation is therefore a feature, not an appendix.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    summary: str


TOPICS = [
    Topic(
        "organising",
        "Organising a workshop",
        "How to lay out drawers, bins and categories so you can actually find things — "
        "including the things this app won't stop you doing wrong.",
    ),
    Topic(
        "parts-and-stock",
        "Parts, stock and units",
        "The difference between a part, a stock row and a location, and what to do when "
        "a spreadsheet said “10 aprox”.",
    ),
    Topic(
        "labels-and-scanning",
        "Labels and scanning",
        "Printing labels, barcoding bins, and why scanning beats searching.",
    ),
    Topic(
        "reference-and-archiving",
        "Reference docs, and keeping them",
        "Why the app archives its own copies, and how to organise your own library.",
    ),
    Topic(
        "community-and-privacy",
        "Community and privacy",
        "What is shared, what never is, and how to turn the whole thing off.",
    ),
    Topic(
        "lights-and-printer",
        "Lights and the label printer",
        "The optional hardware, what it needs, and what the app does without it.",
    ),
]

_TOPIC_BY_SLUG = {topic.slug: topic for topic in TOPICS}


@login_required
def help_index(request):
    return render(request, "inventory/help/index.html", {"topics": TOPICS})


@login_required
def help_topic(request, slug):
    topic = _TOPIC_BY_SLUG.get(slug)
    if topic is None:
        # A 404 rather than a silent redirect to the index: a stale bookmark should be
        # visibly stale, not quietly take you somewhere else.
        raise Http404(f"No help page called “{slug}”.")
    return render(request, f"inventory/help/{slug}.html", {"topic": topic, "topics": TOPICS})
