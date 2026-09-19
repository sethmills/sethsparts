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

from ._shared import _drawer_number, _slugify_drawer_code



# --- Bin barcodes (bulk scan-to-link) ----------------------------------------
# A drawer's bin_count decides whether it has bins and how many: 0 means none,
# 16 is the default 4x4 cabinet, and larger cabinets (up to 100) are a per-drawer
# choice. The old hardcoded "cabinets 38/39/40 only" rule is gone.
BINS_PER_DRAWER = 16
MAX_BINS = 100


def _bin_eligible_drawers():
    drawers = list(Drawer.objects.filter(bin_count__gt=0).select_related("container"))
    drawers.sort(key=_drawer_number)
    return drawers


def _ensure_bins_seeded():
    """Create any missing Bin rows for every drawer that has bins. Idempotent — safe
    to call on every page load."""
    drawers = _bin_eligible_drawers()
    existing = set(Bin.objects.values_list("drawer_id", "bin_number"))
    to_create = [
        Bin(drawer=drawer, bin_number=n)
        for drawer in drawers
        for n in range(1, drawer.bin_count + 1)
        if (drawer.id, n) not in existing
    ]
    if to_create:
        Bin.objects.bulk_create(to_create)
    return drawers


def _ensure_bins_for_drawer(drawer):
    """Same idea as _ensure_bins_seeded but scoped to one drawer — cheap enough to call
    from drawer_detail on every visit, instead of re-checking every drawer."""
    if drawer.bin_count <= 0:
        return False
    existing_numbers = set(drawer.bins.values_list("bin_number", flat=True))
    to_create = [Bin(drawer=drawer, bin_number=n) for n in range(1, drawer.bin_count + 1) if n not in existing_numbers]
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
        {"rows": rows, "total_done": total_done, "total_bins": sum(d.bin_count for d in drawers)},
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


@login_required
def print_bin_grid(request, pk):
    """Print every bin barcode for a drawer, laid out in the drawer's own grid
    (bin_count bins across bin_columns columns) to match the physical layout. Any bin
    without a barcode gets a deterministic one assigned first, so the sheet links
    straight back to the bins."""
    drawer = get_object_or_404(Drawer, pk=pk)
    if not _ensure_bins_for_drawer(drawer):
        messages.error(request, "This drawer has no bins to label.")
        return redirect("inventory:drawer_detail", pk=drawer.pk)

    drawer_code = _slugify_drawer_code(drawer.container.number, drawer.label)
    bins = list(drawer.bins.filter(bin_number__lte=drawer.bin_count).order_by("bin_number"))
    for b in bins:
        if not b.barcode_id:
            b.barcode_id = f"{drawer_code}-{b.bin_number:02d}"
            b.save(update_fields=["barcode_id"])

    cols = max(1, drawer.bin_columns)
    rows = [bins[i : i + cols] for i in range(0, len(bins), cols)]
    return render(request, "inventory/bin_grid_print.html", {"drawer": drawer, "rows": rows})


@login_required
def update_drawer_bins(request, pk):
    """Change how many bins a drawer has (and how the printed sheet is laid out)."""
    drawer = get_object_or_404(Drawer, pk=pk)
    if request.method == "POST":
        try:
            count = max(0, min(MAX_BINS, int(request.POST.get("bin_count") or "0")))
            cols = max(1, min(MAX_BINS, int(request.POST.get("bin_columns") or "4")))
        except ValueError:
            messages.error(request, "Bin count and columns must be whole numbers.")
            return redirect("inventory:drawer_detail", pk=drawer.pk)
        drawer.bin_count = count
        drawer.bin_columns = cols
        drawer.save(update_fields=["bin_count", "bin_columns"])
        _ensure_bins_for_drawer(drawer)
        messages.success(request, f"Drawer {drawer.label} now has {count} bins across {cols} columns.")
    return redirect("inventory:drawer_detail", pk=drawer.pk)
