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

from ..duplicate_detection import find_duplicate_parts
from ..enrichment_ai import is_configured, suggest_enrichment
from .. import audit


@login_required
def part_intake(request):
    container_number = request.GET.get("container") or request.POST.get("container")
    drawer_pk = request.GET.get("drawer") or request.POST.get("drawer")

    drawer = get_object_or_404(Drawer, pk=drawer_pk) if drawer_pk else None
    container = drawer.container if drawer else (
        get_object_or_404(Container, number=container_number) if container_number else None
    )

    # The name can arrive pre-filled from the intake queue ("turn this note into a part").
    name_hint = (request.POST.get("name") or request.GET.get("name") or "").strip()
    context = {"container": container, "drawer": drawer, "categories": Category.objects.all(), "name_hint": name_hint}

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()

        # "Use this existing part instead" — add stock to it, don't create a new part.
        existing_part_pk = request.POST.get("existing_part")
        if existing_part_pk:
            part = get_object_or_404(Part, pk=existing_part_pk)
            if not container:
                messages.error(request, "No location selected — go back to a container or drawer page and use \"Add a part here\".")
            else:
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
                messages.success(request, f"Added to existing part {part.name} at {drawer or container}.")
                if drawer:
                    return redirect("inventory:drawer_detail", pk=drawer.pk)
                return redirect("inventory:container_detail", number=container.number)

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
                # Surface duplicates first; skip the check once the owner has confirmed.
                if not request.POST.get("create_confirmed"):
                    context["candidates"] = find_duplicate_parts(name)
                    if context["candidates"]:
                        return render(request, "inventory/part_intake.html", context)

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

    # On a plain GET, surface duplicates immediately when a name was pre-filled.
    if name_hint and "candidates" not in context:
        context["candidates"] = find_duplicate_parts(name_hint)

    return render(request, "inventory/part_intake.html", context)


@login_required
def part_detail(request, pk):
    part = get_object_or_404(Part, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "suggest_enrichment":
            suggestion, error = suggest_enrichment(
                part.name,
                part.category.name if part.category else None,
                part.description,
                part.manufacturer,
            )
            if error:
                messages.error(request, error)
            else:
                request.session["enrichment_suggestion"] = suggestion
                request.session["enrichment_suggestion_part"] = part.pk
                messages.info(request, "Suggestion ready — review it below, then apply or discard.")
            return redirect("inventory:part_detail", pk=part.pk)

        if action in ("apply_enrichment", "discard_enrichment"):
            if action == "apply_enrichment" and request.session.get("enrichment_suggestion_part") == part.pk:
                _apply_enrichment_suggestion(part, request.session.get("enrichment_suggestion"))
                messages.success(request, "Enrichment applied.")
            request.session.pop("enrichment_suggestion", None)
            request.session.pop("enrichment_suggestion_part", None)
            return redirect("inventory:part_detail", pk=part.pk)

    stock_items = part.stock_items.select_related("container", "drawer")
    attachments = part.attachments.all()
    suggestion = None
    if request.session.get("enrichment_suggestion_part") == part.pk:
        suggestion = request.session.get("enrichment_suggestion")

    return render(
        request,
        "inventory/part_detail.html",
        {
            "part": part,
            "stock_items": stock_items,
            "attachments": attachments,
            "location_choices": _location_choices(),
            "enrichment_configured": is_configured(),
            "enrichment_suggestion": suggestion,
        },
    )


@login_required
def part_edit(request, pk):
    """Edit a part's descriptive fields and links after it has been created."""
    part = get_object_or_404(Part, pk=pk)

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Part name is required.")
            return redirect("inventory:part_edit", pk=part.pk)

        raw_min_qty = (request.POST.get("min_quantity") or "").strip()
        min_quantity = None
        if raw_min_qty:
            try:
                min_quantity = max(0, int(raw_min_qty))
            except ValueError:
                messages.error(request, f"'{raw_min_qty}' isn't a whole number for reorder threshold.")
                return redirect("inventory:part_edit", pk=part.pk)

        part.name = name
        part.category_id = request.POST.get("category") or None
        part.manufacturer = (request.POST.get("manufacturer") or "").strip()
        part.description = (request.POST.get("description") or "").strip()
        part.is_electronic = bool(request.POST.get("is_electronic"))
        part.reorder_url = (request.POST.get("reorder_url") or "").strip()
        part.datasheet_url = (request.POST.get("datasheet_url") or "").strip()
        part.price = (request.POST.get("price") or "").strip()
        part.min_quantity = min_quantity
        part.save()
        messages.success(request, f"Updated {part.name}.")
        return redirect("inventory:part_detail", pk=part.pk)

    return render(request, "inventory/part_edit.html", {"part": part, "categories": Category.objects.all()})


def _apply_enrichment_suggestion(part, suggestion):
    if not suggestion:
        return
    if suggestion.get("category"):
        category, _ = Category.objects.get_or_create(name=suggestion["category"])
        part.category = category
        if category.name.lower() == "electronics":
            part.is_electronic = True
    if suggestion.get("description"):
        part.description = suggestion["description"]
    if suggestion.get("manufacturer"):
        part.manufacturer = suggestion["manufacturer"]
    if part.enrichment_status in (
        Part.ENRICHMENT_NOT_NEEDED,
        Part.ENRICHMENT_PENDING,
        Part.ENRICHMENT_NEEDS_CLARIFICATION,
    ):
        part.enrichment_status = Part.ENRICHMENT_DONE
    part.save(update_fields=["category", "description", "manufacturer", "is_electronic", "enrichment_status"])


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
        old_qty = stock_item.quantity
        stock_item.quantity = new_qty
        stock_item.quantity_raw = str(new_qty)
        stock_item.save(update_fields=["quantity", "quantity_raw"])
        audit.log(
            "stock.adjust", part=stock_item.part, actor=request.user,
            before=old_qty, after=new_qty, container=stock_item.container_id, bin=stock_item.bin_number,
        )
        messages.success(request, f"Updated quantity to {new_qty}.")
    return redirect("inventory:part_detail", pk=stock_item.part_id)


@login_required
def update_stock_bin(request, pk):
    stock_item = get_object_or_404(StockItem, pk=pk)
    if request.method == "POST":
        raw = (request.POST.get("bin_number") or "").strip()
        if not raw:
            audit.log(
                "stock.move", part=stock_item.part, actor=request.user,
                before=stock_item.bin_number, after=None, container=stock_item.container_id,
            )
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
        audit.log(
            "stock.move", part=stock_item.part, actor=request.user,
            before=stock_item.bin_number, after=bin_number, container=stock_item.container_id,
        )
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
        audit.log(
            "stock.remove", part=stock_item.part, actor=request.user,
            container=stock_item.container_id, bin=stock_item.bin_number, quantity=stock_item.quantity,
        )
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
        audit.log(
            "stock.add", part=part, actor=request.user,
            quantity=quantity, container=container.id, drawer=drawer.pk if drawer else None,
        )
        messages.success(request, f"Added {quantity}x {part.name} at {drawer or container}.")
    return redirect("inventory:part_detail", pk=part.pk)
