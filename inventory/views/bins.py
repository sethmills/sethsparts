"""The 16-bin subdivision of cabinets 1-3: seeding, the bulk barcode scan
flow, and per-bin detail."""
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import (
    Bin,
    Drawer,
    StockItem,
    SubBin,
)

from ._shared import _drawer_number



# --- Bin barcodes (bulk scan-to-link) ----------------------------------------
# Only cabinets 1-3 (containers #38/#39/#40, drawers 1-27) are subdivided into the
# 16-bin grid -- cabinet 4 (container #119, drawers 28-36) holds oversized/different
# items with no bin subdivisions, per Seth.
BIN_ELIGIBLE_CONTAINERS = [38, 39, 40]
BINS_PER_DRAWER = 16


def _bin_eligible_drawers():
    drawers = list(Drawer.objects.filter(container__number__in=BIN_ELIGIBLE_CONTAINERS).select_related("container"))
    drawers.sort(key=_drawer_number)
    return drawers


def _ensure_bins_seeded():
    """Create any missing Bin rows (1-16) for every bin-eligible drawer. Idempotent —
    safe to call on every page load."""
    drawers = _bin_eligible_drawers()
    existing = set(
        Bin.objects.filter(drawer__container__number__in=BIN_ELIGIBLE_CONTAINERS).values_list("drawer_id", "bin_number")
    )
    to_create = [
        Bin(drawer=drawer, bin_number=n)
        for drawer in drawers
        for n in range(1, BINS_PER_DRAWER + 1)
        if (drawer.id, n) not in existing
    ]
    if to_create:
        Bin.objects.bulk_create(to_create)
    return drawers


def _ensure_bins_for_drawer(drawer):
    """Same idea as _ensure_bins_seeded but scoped to one drawer — cheap enough to call
    from drawer_detail on every visit, instead of re-checking all 27 bin-eligible drawers."""
    if drawer.container.number not in BIN_ELIGIBLE_CONTAINERS:
        return False
    existing_numbers = set(drawer.bins.values_list("bin_number", flat=True))
    to_create = [Bin(drawer=drawer, bin_number=n) for n in range(1, BINS_PER_DRAWER + 1) if n not in existing_numbers]
    if to_create:
        Bin.objects.bulk_create(to_create)
    return True


@login_required
def bin_setup(request):
    drawers = _ensure_bins_seeded()
    bins_by_drawer = {}
    for b in Bin.objects.filter(drawer__in=drawers):
        bins_by_drawer.setdefault(b.drawer_id, []).append(b)

    rows = []
    total_done = 0
    for drawer in drawers:
        drawer_bins = sorted(bins_by_drawer.get(drawer.id, []), key=lambda b: b.bin_number)
        done = sum(1 for b in drawer_bins if b.barcode_id)
        total_done += done
        first_unscanned = next((b for b in drawer_bins if not b.barcode_id), None)
        rows.append({
            "drawer": drawer,
            "done": done,
            "total": len(drawer_bins),
            "start_bin": (first_unscanned or drawer_bins[0]) if drawer_bins else None,
        })

    return render(
        request,
        "inventory/bin_setup.html",
        {"rows": rows, "total_done": total_done, "total_bins": len(drawers) * BINS_PER_DRAWER},
    )


@login_required
def bin_scan(request):
    drawers = _ensure_bins_seeded()
    all_bins = Bin.objects.filter(drawer__in=drawers).select_related("drawer", "drawer__container")

    positions = [
        {
            "pk": b.pk,
            "label": f"#{b.drawer.container.number} / {b.drawer.label} — Bin {b.bin_number} (row {b.bin_row})",
            "has_code": bool(b.barcode_id),
            "code": b.barcode_id or "",
        }
        for b in all_bins
    ]

    start_pk = request.GET.get("start")
    start_index = 0
    if start_pk:
        for i, p in enumerate(positions):
            if str(p["pk"]) == str(start_pk):
                start_index = i
                break

    return render(
        request,
        "inventory/bin_scan.html",
        {"positions_json": positions, "start_index": start_index},
    )


@login_required
@require_POST
def api_scan_bin(request, pk):
    b = get_object_or_404(Bin, pk=pk)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    code = (payload.get("code") or "").strip()
    if not code:
        return JsonResponse({"ok": False, "error": "no code given"}, status=400)

    conflict = Bin.objects.filter(barcode_id=code).exclude(pk=b.pk).select_related("drawer").first()
    if conflict:
        return JsonResponse({"ok": False, "error": f"That barcode is already linked to {conflict}."}, status=409)

    b.barcode_id = code
    b.save(update_fields=["barcode_id"])
    return JsonResponse({"ok": True})


@login_required
def bin_detail(request, pk):
    b = get_object_or_404(Bin.objects.select_related("drawer", "drawer__container"), pk=pk)
    stock_items = StockItem.objects.filter(drawer=b.drawer, bin_number=b.bin_number).select_related("part")
    return render(
        request,
        "inventory/bin_detail.html",
        {
            "bin": b,
            "stock_items": stock_items,
            "sub_bins": b.sub_bins.all(),
            "can_add_sub_bin": b.sub_bins.count() < 4,
            "size_choices": SubBin.SIZE_CHOICES,
        },
    )


@login_required
def register_bin_barcode(request, pk):
    b = get_object_or_404(Bin, pk=pk)
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        if code:
            conflict = Bin.objects.filter(barcode_id=code).exclude(pk=b.pk).first()
            if conflict:
                messages.error(request, f"That barcode is already linked to {conflict}.")
            else:
                b.barcode_id = code
                b.save(update_fields=["barcode_id"])
                messages.success(request, f"Registered barcode {code} for {b}.")
    return redirect("inventory:bin_detail", pk=b.pk)


@login_required
def add_sub_bin(request, pk):
    b = get_object_or_404(Bin, pk=pk)
    if request.method == "POST":
        existing_positions = set(b.sub_bins.values_list("position", flat=True))
        if len(existing_positions) >= 4:
            messages.error(request, "This bin already has 4 sub-bins — that's the max.")
        else:
            size = request.POST.get("size") or SubBin.SMALL
            if size not in dict(SubBin.SIZE_CHOICES):
                size = SubBin.SMALL
            next_position = next(p for p in range(1, 5) if p not in existing_positions)
            SubBin.objects.create(bin=b, position=next_position, size=size)
            messages.success(request, f"Added sub-bin {next_position} to {b}.")
    return redirect("inventory:bin_detail", pk=b.pk)


@login_required
def register_sub_bin_barcode(request, pk):
    sub_bin = get_object_or_404(SubBin, pk=pk)
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        if code:
            conflict = SubBin.objects.filter(barcode_id=code).exclude(pk=sub_bin.pk).first()
            if conflict:
                messages.error(request, f"That barcode is already linked to {conflict}.")
            else:
                sub_bin.barcode_id = code
                sub_bin.save(update_fields=["barcode_id"])
                messages.success(request, f"Registered barcode {code} for {sub_bin}.")
    return redirect("inventory:bin_detail", pk=sub_bin.bin_id)


@login_required
def delete_sub_bin(request, pk):
    sub_bin = get_object_or_404(SubBin, pk=pk)
    bin_pk = sub_bin.bin_id
    if request.method == "POST":
        sub_bin.delete()
        messages.success(request, "Sub-bin removed.")
    return redirect("inventory:bin_detail", pk=bin_pk)
