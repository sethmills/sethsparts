"""Browsing, scanning, and the container/drawer detail pages."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..models import (
    Bin,
    Container,
    Drawer,
    StockItem,
    SubBin,
)

from ._shared import _drawer_number
from .bins import _ensure_bins_for_drawer



@login_required
def browse(request):
    container_type = request.GET.get("type") or ""
    q = (request.GET.get("q") or "").strip()

    containers = (
        Container.objects.all()
        .prefetch_related("drawers")
        .annotate(item_count=Count("stock_items", distinct=True))
    )
    if container_type:
        containers = containers.filter(container_type=container_type)
    if q:
        containers = containers.filter(
            Q(number__icontains=q) | Q(name__icontains=q) | Q(container_type__icontains=q)
        )

    all_types = Container.objects.order_by("container_type").values_list("container_type", flat=True).distinct()

    # Drawers, front and center: day-to-day browsing is almost always "which drawer",
    # not "which cabinet" -- the cabinet/container grouping below is still there for
    # organization, but shouldn't be a click Seth has to make just to get to a drawer.
    all_drawers = list(
        Drawer.objects.select_related("container").annotate(item_count=Count("stock_items", distinct=True))
    )
    all_drawers.sort(key=_drawer_number)

    return render(
        request,
        "inventory/browse.html",
        {
            "containers": containers,
            "all_types": all_types,
            "selected_type": container_type,
            "q": q,
            "all_drawers": all_drawers,
        },
    )


@login_required
def scan(request):
    return render(request, "inventory/scan.html")


@login_required
def go(request):
    code = (request.GET.get("code") or "").strip()
    if not code:
        return redirect("inventory:scan")

    container = Container.objects.filter(barcode_id=code).first()
    if container:
        return redirect("inventory:container_detail", number=container.number)

    drawer = Drawer.objects.filter(barcode_id=code).first()
    if drawer:
        return redirect("inventory:drawer_detail", pk=drawer.pk)

    b = Bin.objects.filter(barcode_id=code).first()
    if b:
        return redirect("inventory:bin_detail", pk=b.pk)

    sub_bin = SubBin.objects.filter(barcode_id=code).first()
    if sub_bin:
        return redirect("inventory:bin_detail", pk=sub_bin.bin_id)

    return render(request, "inventory/not_found.html", {"code": code})


@login_required
def jump_to_container(request):
    number = request.GET.get("number")
    code = request.GET.get("code", "")
    container = Container.objects.filter(number=number).first()
    if not container:
        messages.error(request, f"No container #{number}.")
        return redirect("inventory:scan")
    url = reverse("inventory:container_detail", args=[container.number])
    if code:
        url += f"?code={code}"
    return redirect(url)


@login_required
def container_detail(request, number):
    container = get_object_or_404(Container, number=number)
    drawers = container.drawers.all()
    direct_stock = container.stock_items.filter(drawer__isnull=True).select_related("part")
    return render(
        request,
        "inventory/container_detail.html",
        {
            "container": container,
            "drawers": drawers,
            "stock_items": direct_stock,
            "photos": container.photos.all(),
            "intake_notes": container.intake_notes.all(),
        },
    )


@login_required
def delete_container(request, number):
    container = get_object_or_404(Container, number=number)
    if request.method == "POST":
        if request.POST.get("confirm_number") == str(container.number):
            name = str(container)
            container.delete()
            messages.success(request, f"Deleted {name} and everything in it.")
            return redirect("inventory:browse")
        messages.error(request, "Confirmation number didn't match — nothing was deleted.")
        return redirect("inventory:container_detail", number=container.number)

    drawer_item_count = StockItem.objects.filter(container=container, drawer__isnull=False).count()
    direct_item_count = StockItem.objects.filter(container=container, drawer__isnull=True).count()
    return render(
        request,
        "inventory/delete_container.html",
        {
            "container": container,
            "drawer_count": container.drawers.count(),
            "drawer_item_count": drawer_item_count,
            "direct_item_count": direct_item_count,
        },
    )


@login_required
def drawer_detail(request, pk):
    drawer = get_object_or_404(Drawer.objects.select_related("container"), pk=pk)
    stock_items = drawer.stock_items.select_related("part")
    has_bins = _ensure_bins_for_drawer(drawer)
    bins = drawer.bins.annotate(sub_bin_count=Count("sub_bins")) if has_bins else []
    return render(
        request,
        "inventory/drawer_detail.html",
        {"drawer": drawer, "stock_items": stock_items, "bins": bins},
    )


@login_required
def register_container_barcode(request, number):
    container = get_object_or_404(Container, number=number)
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        if code:
            container.barcode_id = code
            container.save(update_fields=["barcode_id"])
            messages.success(request, f"Registered barcode {code} for container #{container.number}.")
        return redirect("inventory:container_detail", number=container.number)
    return redirect("inventory:container_detail", number=container.number)


@login_required
def register_drawer_barcode(request, pk):
    drawer = get_object_or_404(Drawer, pk=pk)
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        if code:
            drawer.barcode_id = code
            drawer.save(update_fields=["barcode_id"])
            messages.success(request, f"Registered barcode {code} for {drawer}.")
        return redirect("inventory:drawer_detail", pk=drawer.pk)
    return redirect("inventory:drawer_detail", pk=drawer.pk)
