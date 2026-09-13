"""The tagging/review worklists for parts needing attention."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..models import (
    Category,
    Part,
    StockItem,
)



@login_required
def tagging_list(request):
    status = request.GET.get("status") or ""
    location = request.GET.get("location") or ""
    query = (request.GET.get("q") or "").strip()

    queue_statuses = [Part.ENRICHMENT_NEEDS_REVIEW, Part.ENRICHMENT_NEEDS_CLARIFICATION]
    base_qs = Part.objects.filter(enrichment_status__in=queue_statuses)

    parts = base_qs.select_related("category").prefetch_related("stock_items__container", "stock_items__drawer__container")
    if status in dict(Part.ENRICHMENT_CHOICES):
        parts = parts.filter(enrichment_status=status)
    if query:
        parts = parts.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if location:
        kind, _, value = location.partition(":")
        if kind == "container":
            parts = parts.filter(stock_items__container__number=value)
        elif kind == "drawer":
            parts = parts.filter(stock_items__drawer__pk=value)
        parts = parts.distinct()

    parts = list(parts.order_by("name"))
    for part in parts:
        locations = {str(si.drawer) if si.drawer else str(si.container) for si in part.stock_items.all()}
        part.location_summary = ", ".join(sorted(locations)) or "no location recorded"

    return render(
        request,
        "inventory/tagging.html",
        {
            "parts": parts,
            "categories": Category.objects.all(),
            "status_choices": Part.ENRICHMENT_CHOICES,
            "selected_status": status,
            "selected_location": location,
            "query": query,
            "location_options": _tagging_location_choices(base_qs),
        },
    )


@login_required
def tagging_update(request, pk):
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        part.manufacturer = (request.POST.get("manufacturer") or "").strip()
        part.description = (request.POST.get("description") or "").strip()
        part.reorder_url = (request.POST.get("reorder_url") or "").strip()
        category_id = request.POST.get("category") or None
        part.category_id = category_id
        status = request.POST.get("enrichment_status") or part.enrichment_status
        if status in dict(Part.ENRICHMENT_CHOICES):
            part.enrichment_status = status
        part.save()
        messages.success(request, f"Updated {part.name}.")

    next_url = request.POST.get("next") or ""
    if not next_url.startswith("/"):
        next_url = reverse("inventory:tagging_list")
    return redirect(next_url)


def _tagging_location_choices(queue_qs):
    """(value, label, count) for locations currently holding a part in the given queryset,
    value format matching `_location_choices`'s 'container:<number>' / 'drawer:<pk>' convention."""
    counts = {}
    labels = {}
    stock_items = StockItem.objects.filter(part__in=queue_qs).select_related("container", "drawer__container")
    for si in stock_items:
        if si.drawer:
            value = f"drawer:{si.drawer.pk}"
            labels[value] = str(si.drawer)
        else:
            value = f"container:{si.container.number}"
            labels[value] = str(si.container)
        counts[value] = counts.get(value, 0) + 1
    return sorted(((value, labels[value], count) for value, count in counts.items()), key=lambda t: t[1])
