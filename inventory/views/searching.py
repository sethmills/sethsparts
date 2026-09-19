"""Free-text part search and the Home Assistant voice endpoint.

Distinct from inventory/search.py (the pure query builders this calls) -- that
one holds build_search_query/expand_terms, this one holds the views."""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from ..search import build_search_query, expand_terms

from ..models import (
    Category,
    Container,
    IntakeNote,
    Part,
)



@login_required
def parts_search(request):
    query = (request.GET.get("q") or "").strip()
    category_id = request.GET.get("category") or ""
    manufacturer = request.GET.get("manufacturer") or ""
    has_docs = request.GET.get("has_docs") or ""

    parts = Part.objects.select_related("category")
    matched_extra_terms = []
    if query:
        matched_extra_terms = expand_terms(query)
        parts = parts.filter(build_search_query(query))
    if category_id:
        parts = parts.filter(category_id=category_id)
    if manufacturer:
        parts = parts.filter(manufacturer=manufacturer)
    if has_docs == "yes":
        parts = parts.filter(enrichment_status__in=[Part.ENRICHMENT_DONE, Part.ENRICHMENT_NEEDS_REVIEW])
    elif has_docs == "no":
        parts = parts.exclude(enrichment_status__in=[Part.ENRICHMENT_DONE, Part.ENRICHMENT_NEEDS_REVIEW])

    if not query and not category_id and not manufacturer and not has_docs:
        parts = Part.objects.none()

    manufacturers = (
        Part.objects.exclude(manufacturer="").order_by("manufacturer").values_list("manufacturer", flat=True).distinct()
    )

    parts = list(parts[:150])
    _attach_thumbnails(parts)

    return render(
        request,
        "inventory/parts_search.html",
        {
            "query": query,
            "parts": parts,
            "matched_extra_terms": matched_extra_terms,
            "categories": Category.objects.all(),
            "manufacturers": manufacturers,
            "selected_category": category_id,
            "selected_manufacturer": manufacturer,
            "selected_has_docs": has_docs,
        },
    )


def _attach_thumbnails(parts):
    """Give each part a `thumb` attribute pointing at its first image attachment, so
    search results can show the shape without a per-part query."""
    from ..models import Attachment

    part_ids = [p.pk for p in parts]
    if not part_ids:
        return
    thumbs = {}
    for a in Attachment.objects.filter(part_id__in=part_ids, doc_type=Attachment.IMAGE).order_by("part_id", "fetched_at"):
        thumbs.setdefault(a.part_id, a.file.url)
    for p in parts:
        p.thumb = thumbs.get(p.pk)


def api_locate_part(request):
    """Machine-to-machine search for Home Assistant Assist voice queries — not @login_required,
    since HA has no browser session; a shared secret (VOICE_SEARCH_API_KEY) stands in for auth."""
    provided_key = request.headers.get("X-Api-Key") or request.GET.get("key") or ""
    if not settings.VOICE_SEARCH_API_KEY or provided_key != settings.VOICE_SEARCH_API_KEY:
        return JsonResponse({"error": "unauthorized"}, status=403)

    query = (request.GET.get("q") or "").strip()
    if not query:
        return JsonResponse({"error": "missing q"}, status=400)

    parts = Part.objects.filter(build_search_query(query)).prefetch_related(
        "stock_items__container", "stock_items__drawer__container"
    )[:5]

    matches = []
    for part in parts:
        locations = sorted({str(si.drawer) if si.drawer else str(si.container) for si in part.stock_items.all()})
        matches.append(
            {
                "name": part.name,
                "manufacturer": part.manufacturer,
                "locations": locations,
                "quantity_summary": ", ".join(si.quantity_spoken for si in part.stock_items.all()),
            }
        )

    return JsonResponse({"query": query, "count": len(matches), "matches": matches})


def api_add_intake_note(request):
    """Machine-to-machine voice intake — same shared-secret auth as api_locate_part.

    A dictated line ("M3 bolts, two bags") becomes an IntakeNote for the owner to
    review in the intake queue, rather than being parsed into structured data on
    the spot. Accepts the same X-Api-Key header or a `key` param, on GET or POST."""
    provided_key = request.headers.get("X-Api-Key") or request.GET.get("key") or request.POST.get("key") or ""
    if not settings.VOICE_SEARCH_API_KEY or provided_key != settings.VOICE_SEARCH_API_KEY:
        return JsonResponse({"error": "unauthorized"}, status=403)

    text = (request.GET.get("text") or request.POST.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "missing text"}, status=400)

    raw_container = (request.GET.get("container") or request.POST.get("container") or "").strip()
    container = None
    if raw_container:
        try:
            container = Container.objects.filter(number=int(raw_container)).first()
        except ValueError:
            return JsonResponse({"error": f"container '{raw_container}' isn't a number"}, status=400)
        if container is None:
            return JsonResponse({"error": f"container {raw_container} not found"}, status=404)

    note = IntakeNote.objects.create(container=container, text=text, source=IntakeNote.VOICE)
    return JsonResponse({
        "ok": True,
        "id": note.pk,
        "text": note.text,
        "container": container.number if container else None,
    })
