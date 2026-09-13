"""Part intake, part detail, and editing a part's stock rows."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..models import (
    Attachment,
    Category,
    Container,
    Drawer,
    Part,
    StockItem,
)

from ._shared import _location_choices



@login_required
def part_intake(request):
    container_number = request.GET.get("container") or request.POST.get("container")
    drawer_pk = request.GET.get("drawer") or request.POST.get("drawer")

    drawer = get_object_or_404(Drawer, pk=drawer_pk) if drawer_pk else None
    container = drawer.container if drawer else (
        get_object_or_404(Container, number=container_number) if container_number else None
    )

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Part name is required.")
        elif not container:
            messages.error(request, "No location selected — go back to a container or drawer page and use \"Add a part here\".")
        else:
            raw_min_qty = (request.POST.get("min_quantity") or "").strip()
            min_quantity = None
            min_qty_error = False
            if raw_min_qty:
                try:
                    min_quantity = max(0, int(raw_min_qty))
                except ValueError:
                    min_qty_error = True
                    messages.error(request, f"'{raw_min_qty}' isn't a whole number for reorder threshold.")

            if not min_qty_error:
                category_id = request.POST.get("category") or None
                part = Part.objects.create(
                    name=name,
                    category_id=category_id,
                    manufacturer=(request.POST.get("manufacturer") or "").strip(),
                    description=(request.POST.get("description") or "").strip(),
                    is_electronic=bool(request.POST.get("is_electronic")),
                    reorder_url=(request.POST.get("reorder_url") or "").strip(),
                    datasheet_url=(request.POST.get("datasheet_url") or "").strip(),
                    min_quantity=min_quantity,
                )

                raw_qty = (request.POST.get("quantity") or "").strip()
                quantity = None
                if raw_qty:
                    try:
                        quantity = max(0, int(raw_qty))
                    except ValueError:
                        quantity = None
                StockItem.objects.create(
                    part=part, container=container, drawer=drawer, quantity=quantity, quantity_raw=raw_qty
                )

                messages.success(request, f"Added {part.name} at {drawer or container}.")
                if drawer:
                    return redirect("inventory:drawer_detail", pk=drawer.pk)
                return redirect("inventory:container_detail", number=container.number)

    return render(
        request,
        "inventory/part_intake.html",
        {"container": container, "drawer": drawer, "categories": Category.objects.all()},
    )


@login_required
def part_detail(request, pk):
    part = get_object_or_404(Part, pk=pk)
    stock_items = part.stock_items.select_related("container", "drawer")
    attachments = part.attachments.all()
    return render(
        request,
        "inventory/part_detail.html",
        {
            "part": part,
            "stock_items": stock_items,
            "attachments": attachments,
            "location_choices": _location_choices(),
        },
    )


@login_required
def add_part_photo(request, pk):
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        photo = request.FILES.get("photo")
        if not photo:
            messages.error(request, "No photo received.")
        else:
            Attachment.objects.create(part=part, file=photo, doc_type=Attachment.IMAGE, title="Product photo")
            messages.success(request, "Photo added.")
    return redirect("inventory:part_detail", pk=part.pk)


@login_required
def update_stock_quantity(request, pk):
    stock_item = get_object_or_404(StockItem, pk=pk)
    if request.method == "POST":
        raw = (request.POST.get("quantity") or "").strip()
        try:
            new_qty = max(0, int(raw))
        except ValueError:
            messages.error(request, f"'{raw}' isn't a whole number.")
            return redirect("inventory:part_detail", pk=stock_item.part_id)
        stock_item.quantity = new_qty
        stock_item.quantity_raw = str(new_qty)
        stock_item.save(update_fields=["quantity", "quantity_raw"])
        messages.success(request, f"Updated quantity to {new_qty}.")
    return redirect("inventory:part_detail", pk=stock_item.part_id)


@login_required
def update_stock_bin(request, pk):
    stock_item = get_object_or_404(StockItem, pk=pk)
    if request.method == "POST":
        raw = (request.POST.get("bin_number") or "").strip()
        if not raw:
            stock_item.bin_number = None
            stock_item.save(update_fields=["bin_number"])
            messages.success(request, "Cleared bin number.")
            return redirect("inventory:part_detail", pk=stock_item.part_id)
        try:
            bin_number = int(raw)
            if not (1 <= bin_number <= 16):
                raise ValueError
        except ValueError:
            messages.error(request, "Bin number must be 1-16.")
            return redirect("inventory:part_detail", pk=stock_item.part_id)
        stock_item.bin_number = bin_number
        stock_item.save(update_fields=["bin_number"])
        messages.success(request, f"Set bin to {bin_number} (row {stock_item.bin_row}).")
    return redirect("inventory:part_detail", pk=stock_item.part_id)


@login_required
def delete_stock_item(request, pk):
    stock_item = get_object_or_404(StockItem, pk=pk)
    part_id = stock_item.part_id
    if request.method == "POST":
        where = stock_item.drawer or stock_item.container
        stock_item.delete()
        messages.success(request, f"Removed that entry (was at {where}).")
    return redirect("inventory:part_detail", pk=part_id)


@login_required
def add_stock_item(request, pk):
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        location = request.POST.get("location") or ""
        raw_qty = (request.POST.get("quantity") or "").strip()
        try:
            quantity = max(0, int(raw_qty))
        except ValueError:
            messages.error(request, f"'{raw_qty}' isn't a whole number.")
            return redirect("inventory:part_detail", pk=part.pk)

        container, drawer = None, None
        kind, _, value = location.partition(":")
        if kind == "container":
            container = Container.objects.filter(number=value).first()
        elif kind == "drawer":
            drawer = Drawer.objects.filter(pk=value).select_related("container").first()
            if drawer:
                container = drawer.container

        if not container:
            messages.error(request, "Pick a valid location.")
            return redirect("inventory:part_detail", pk=part.pk)

        StockItem.objects.create(
            part=part, container=container, drawer=drawer, quantity=quantity, quantity_raw=str(quantity)
        )
        messages.success(request, f"Added {quantity}x {part.name} at {drawer or container}.")
    return redirect("inventory:part_detail", pk=part.pk)
