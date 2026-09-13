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

    return render(
        request,
        "inventory/parts_search.html",
        {
            "query": query,
            "parts": parts[:150],
            "matched_extra_terms": matched_extra_terms,
            "categories": Category.objects.all(),
            "manufacturers": manufacturers,
            "selected_category": category_id,
            "selected_manufacturer": manufacturer,
            "selected_has_docs": has_docs,
        },
    )


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
                "quantity_summary": ", ".join(
                    si.quantity_raw or (str(si.quantity) if si.quantity is not None else "unknown qty")
                    for si in part.stock_items.all()
                ),
            }
        )

    return JsonResponse({"query": query, "count": len(matches), "matches": matches})
