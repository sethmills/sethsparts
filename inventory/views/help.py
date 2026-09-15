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

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


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


@login_required
def feedback(request):
    """In-app feedback: a bug report or feature request, sent to the maintainer.

    Three routes, in order of preference:
      1. `FEEDBACK_URL` (a relay endpoint the maintainer runs) — the zero-config path
         for beta installs: the maintainer sets the URL in .env, the user configures
         nothing, and the relay delivers the message.
      2. A local `feedback_email` via this instance's own SMTP.
      3. Copy-to-clipboard, so the message is never lost even with no route configured.
    """
    from ..notifications import send
    from ..site_config import get_site_settings, site_name
    from ..version import __version__

    site = get_site_settings()
    feedback_to = (site.feedback_email if site else "").strip()
    feedback_url = (settings.FEEDBACK_URL or "").strip()

    if request.method == "POST":
        kind = request.POST.get("kind") or "other"
        title = (request.POST.get("title") or "").strip()
        message = (request.POST.get("message") or "").strip()
        page = (request.POST.get("page") or "").strip()

        if not title and not message:
            messages.error(request, "Say what happened — a title or a description.")
            return redirect("inventory:feedback")

        body = (
            f"Type: {kind}\n"
            f"Title: {title or '(none)'}\n"
            f"Page: {page or '(not provided)'}\n"
            f"Instance: {site_name()} (v{__version__})\n"
            f"\n{message}"
        )

        if feedback_url:
            ok, error = _post_feedback(
                feedback_url,
                {
                    "kind": kind,
                    "title": title,
                    "message": message,
                    "page": page,
                    "instance": site_name(),
                    "version": __version__,
                    "key": (settings.FEEDBACK_KEY or ""),
                },
            )
            if ok:
                messages.success(request, "Thanks — your feedback has been sent.")
                return redirect("inventory:feedback")
            messages.error(request, f"Couldn't send it ({error}). Copy it below and send it another way.")
            return render(request, "inventory/feedback.html", {"fallback_text": body})

        subject = f"[{site_name()} feedback] {kind}: {title or 'no title'}"
        if feedback_to:
            sent, error = send(subject, body, to=feedback_to)
            if sent:
                messages.success(request, "Thanks — your feedback has been sent to the maintainer.")
                return redirect("inventory:feedback")
            messages.error(request, f"Couldn't send it ({error}). Copy it below and send it another way.")
        else:
            messages.error(request, "No feedback route is configured on this install. Copy it below and send it to the maintainer.")

        return render(request, "inventory/feedback.html", {"fallback_text": body})

    return render(request, "inventory/feedback.html")


def _post_feedback(url, payload):
    import requests

    try:
        resp = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as exc:
        return False, f"couldn't reach the relay: {exc}"
    if resp.status_code == 200:
        return True, ""
    return False, f"the relay answered HTTP {resp.status_code}"


@csrf_exempt
@require_POST
def api_feedback(request):
    """The relay endpoint a maintainer runs: accepts another instance's feedback and
    emails it to them (feedback_email, falling back to notify_email). Optionally keyed
    with FEEDBACK_KEY so a public endpoint isn't a spam pipe into the maintainer's inbox.

    Deliberately unauthenticated (it's called machine-to-machine from other installs)
    and CSRF-exempt for the same reason; the payload shape is the only contract."""
    import json

    from ..notifications import send
    from ..site_config import get_site_settings

    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    expected_key = (settings.FEEDBACK_KEY or "")
    if expected_key and payload.get("key") != expected_key:
        return JsonResponse({"ok": False, "error": "bad key"}, status=403)

    kind = payload.get("kind") or "other"
    title = (payload.get("title") or "").strip()
    message = (payload.get("message") or "").strip()
    page = (payload.get("page") or "").strip()
    instance = (payload.get("instance") or "").strip()
    version = (payload.get("version") or "").strip()

    if not title and not message:
        return JsonResponse({"ok": False, "error": "empty"}, status=400)

    site = get_site_settings()
    to = ((site.feedback_email or site.notify_email) if site else "").strip()
    if not to:
        return JsonResponse({"ok": False, "error": "no feedback address configured"}, status=502)

    body = (
        f"Type: {kind}\nTitle: {title or '(none)'}\nPage: {page or '(not provided)'}\n"
        f"From: {instance} v{version}\n\n{message}"
    )
    subject = f"[sethsparts feedback] {kind}: {title or 'no title'}"
    sent, error = send(subject, body, to=to)
    if not sent:
        return JsonResponse({"ok": False, "error": error}, status=502)
    return JsonResponse({"ok": True})
