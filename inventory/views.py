from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import (
    BOMRevision,
    Build,
    BuildConsumption,
    Category,
    Container,
    Drawer,
    Part,
    Project,
    ReferenceDoc,
    StockItem,
)
from .search import build_search_query, expand_terms


def _slugify_drawer_code(container_number, label):
    # "drawer b2" -> "B2"
    suffix = label.strip().upper().replace("DRAWER", "").strip()
    return f"D{container_number}{suffix}"


def _current_stock(part):
    """Sum of known (parseable) quantities across all StockItems for this part."""
    return StockItem.objects.filter(part=part).aggregate(total=Sum("quantity"))["total"] or 0


def _reorder_link(part):
    if part.reorder_url:
        return part.reorder_url
    return f"https://www.google.com/search?q={quote(part.name)}"


def _consume_stock(part, quantity_needed):
    """FIFO-consume quantity_needed of `part` across its StockItems. Returns quantity actually consumed
    (may be less than requested if stock — or its recorded quantity — runs short; free-text-only
    quantities like '10 aprox' have quantity=None and can't be reliably decremented)."""
    consumed = 0
    for stock_item in StockItem.objects.filter(part=part, quantity__gt=0).order_by("id"):
        if consumed >= quantity_needed:
            break
        take = min(stock_item.quantity, quantity_needed - consumed)
        stock_item.quantity -= take
        stock_item.save(update_fields=["quantity"])
        consumed += take
    return consumed


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

    return render(
        request,
        "inventory/browse.html",
        {"containers": containers, "all_types": all_types, "selected_type": container_type, "q": q},
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
        {"container": container, "drawers": drawers, "stock_items": direct_stock},
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
    drawer = get_object_or_404(Drawer, pk=pk)
    stock_items = drawer.stock_items.select_related("part")
    return render(
        request,
        "inventory/drawer_detail.html",
        {"drawer": drawer, "stock_items": stock_items},
    )


def _location_choices():
    """Combined container/drawer choices for the "add stock" dropdown, value format
    'container:<number>' or 'drawer:<pk>'."""
    choices = []
    for c in Container.objects.order_by("number"):
        choices.append((f"container:{c.number}", f"#{c.number} ({c.container_type})"))
    for d in Drawer.objects.select_related("container").order_by("container__number", "label"):
        choices.append((f"drawer:{d.pk}", f"#{d.container.number} / {d.label}"))
    return choices


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


@login_required
def labels(request):
    unlabeled_containers = Container.objects.filter(Q(barcode_id__isnull=True) | Q(barcode_id=""))
    unlabeled_drawers = Drawer.objects.filter(Q(barcode_id__isnull=True) | Q(barcode_id=""))
    return render(
        request,
        "inventory/labels.html",
        {"unlabeled_containers": unlabeled_containers, "unlabeled_drawers": unlabeled_drawers},
    )


@login_required
def generate_and_print_labels(request):
    if request.method != "POST":
        return redirect("inventory:labels")

    container_ids = request.POST.getlist("container_ids")
    drawer_ids = request.POST.getlist("drawer_ids")

    unlabeled = Q(barcode_id__isnull=True) | Q(barcode_id="")
    containers = Container.objects.filter(unlabeled, pk__in=container_ids)
    for container in containers:
        container.barcode_id = f"C{container.number}"
        container.save(update_fields=["barcode_id"])

    drawers = Drawer.objects.filter(unlabeled, pk__in=drawer_ids)
    for drawer in drawers:
        drawer.barcode_id = _slugify_drawer_code(drawer.container.number, drawer.label)
        drawer.save(update_fields=["barcode_id"])

    ids_param = ",".join([f"c{i}" for i in container_ids] + [f"d{i}" for i in drawer_ids])
    return redirect(f"{reverse('inventory:print_labels')}?ids={ids_param}")


@login_required
def print_labels(request):
    ids_param = request.GET.get("ids", "")
    container_ids, drawer_ids = [], []
    for token in ids_param.split(","):
        if token.startswith("c"):
            container_ids.append(token[1:])
        elif token.startswith("d"):
            drawer_ids.append(token[1:])

    containers = Container.objects.filter(pk__in=container_ids)
    drawers = Drawer.objects.filter(pk__in=drawer_ids).select_related("container")

    labels_data = []
    for c in containers:
        labels_data.append({"title": f"Container #{c.number}", "subtitle": c.container_type, "code": c.barcode_id})
    for d in drawers:
        labels_data.append({"title": str(d), "subtitle": "", "code": d.barcode_id})

    return render(request, "inventory/print_labels.html", {"labels_data": labels_data})


def barcode_svg(request, code):
    """Renders a Code128 SVG for the given code value — used as an <img> src on label pages."""
    import io

    import barcode
    from barcode.writer import SVGWriter
    from django.http import HttpResponse

    writer = SVGWriter()
    writer.set_options({"write_text": False, "module_height": 12, "quiet_zone": 1})
    code128 = barcode.get("code128", code, writer=writer)
    buffer = io.BytesIO()
    code128.write(buffer)
    return HttpResponse(buffer.getvalue(), content_type="image/svg+xml")


# --- Phase 4: BOM / Projects -------------------------------------------------

@login_required
def project_list(request):
    projects = Project.objects.all()
    return render(request, "inventory/project_list.html", {"projects": projects})


@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    revision = project.latest_revision
    coverage = []
    if revision:
        for line in revision.lines.select_related("part"):
            have = _current_stock(line.part)
            coverage.append(
                {
                    "line": line,
                    "have": have,
                    "need": line.quantity_required,
                    "shortfall": max(0, line.quantity_required - have),
                    "reorder_link": _reorder_link(line.part) if line.quantity_required > have else None,
                }
            )
    builds = project.builds.select_related("revision").prefetch_related("consumptions__part")
    return render(
        request,
        "inventory/project_detail.html",
        {"project": project, "revision": revision, "coverage": coverage, "builds": builds},
    )


@login_required
def build_project(request, pk):
    project = get_object_or_404(Project, pk=pk)
    revision = project.latest_revision
    if request.method != "POST" or not revision:
        return redirect("inventory:project_detail", pk=project.pk)

    try:
        quantity_built = max(1, int(request.POST.get("quantity_built", 1)))
    except (TypeError, ValueError):
        quantity_built = 1

    build = Build.objects.create(project=project, revision=revision, quantity_built=quantity_built)
    any_short = False
    for line in revision.lines.select_related("part"):
        needed = line.quantity_required * quantity_built
        consumed = _consume_stock(line.part, needed)
        BuildConsumption.objects.create(
            build=build, part=line.part, quantity_requested=needed, quantity_consumed=consumed
        )
        if consumed < needed:
            any_short = True

    if any_short:
        messages.error(request, "Build recorded, but stock ran short on one or more parts — see details below.")
    else:
        messages.success(request, f"Built {quantity_built}x {project.name} and deducted stock.")
    return redirect("inventory:project_detail", pk=project.pk)


# --- Phase 5: Reorder dashboard ----------------------------------------------

@login_required
def reorder(request):
    category_id = request.GET.get("category")
    parts = Part.objects.filter(min_quantity__isnull=False).select_related("category")
    if category_id:
        parts = parts.filter(category_id=category_id)

    needs_reorder = []
    for part in parts:
        have = _current_stock(part)
        if have < part.min_quantity:
            needs_reorder.append({"part": part, "have": have, "min_quantity": part.min_quantity, "reorder_link": _reorder_link(part)})

    return render(
        request,
        "inventory/reorder.html",
        {"needs_reorder": needs_reorder, "categories": Category.objects.all(), "selected_category": category_id},
    )


# --- Phase 6: Export ----------------------------------------------------------

@login_required
def export_inventory(request):
    import io
    import zipfile
    from datetime import datetime
    from pathlib import Path

    from django.conf import settings
    from django.http import FileResponse

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = settings.DATABASES["default"]["NAME"]
        if Path(db_path).exists():
            zf.write(db_path, arcname="db.sqlite3")

        media_root = Path(settings.MEDIA_ROOT)
        if media_root.exists():
            for file_path in media_root.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, arcname=str(Path("media") / file_path.relative_to(media_root)))

        readme = (
            "Seth's Parts export\n"
            "=====================\n"
            "To restore: drop db.sqlite3 into a fresh checkout of the tor-inventory project\n"
            "(replacing its empty one) and copy media/ alongside it, then run migrate as normal.\n"
            "This only works for the SQLite dev setup — a Postgres deployment needs its own\n"
            "restore path (pg_restore from a pg_dump), not this file.\n"
        )
        zf.writestr("README.txt", readme)

    buffer.seek(0)
    filename = f"tor-inventory-export-{datetime.now():%Y%m%d-%H%M%S}.zip"
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type="application/zip")


# --- Reference section --------------------------------------------------------

@login_required
def reference_list(request):
    category = request.GET.get("category") or ""
    docs = ReferenceDoc.objects.all()
    if category:
        docs = docs.filter(category=category)

    grouped = {}
    for doc in docs:
        grouped.setdefault(doc.category, []).append(doc)

    category_order = [c[0] for c in ReferenceDoc.CATEGORY_CHOICES]
    sections = [
        (dict(ReferenceDoc.CATEGORY_CHOICES)[key], grouped[key])
        for key in category_order
        if key in grouped
    ]

    return render(
        request,
        "inventory/reference_list.html",
        {"sections": sections, "categories": ReferenceDoc.CATEGORY_CHOICES, "selected_category": category},
    )


@login_required
def resistor_calculator(request):
    return render(request, "inventory/resistor_calculator.html")
