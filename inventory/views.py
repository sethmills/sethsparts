import secrets
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import (
    Attachment,
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


def kiosk_autologin(request):
    """Lets the Pi kiosk's own launch script establish a real, properly-issued session
    on every boot — device-pairing via a long-lived secret token, never Seth's actual
    account password. Not @login_required (that's the whole point); the token itself
    is the credential, transmitted only over HTTPS and known only to this server's
    .env and the kiosk launch script on the Pi."""
    token = request.GET.get("token", "")
    if not settings.KIOSK_AUTOLOGIN_TOKEN or not secrets.compare_digest(token, settings.KIOSK_AUTOLOGIN_TOKEN):
        return redirect("inventory:browse")  # wrong/missing token -> just land on the normal (login-walled) site

    user = get_user_model().objects.filter(username=settings.KIOSK_AUTOLOGIN_USERNAME).first()
    if user:
        login(request, user)
    return redirect(request.GET.get("next") or "inventory:browse")


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
def locate_stock_item(request, pk):
    """Like locate_drawer_led, but for one specific StockItem — if it has a bin_number
    set, includes which row (1-4) to flash so the animation conveys bin-level detail,
    not just "somewhere in this drawer"."""
    stock_item = get_object_or_404(StockItem, pk=pk)
    if request.method == "POST":
        drawer = stock_item.drawer
        if not drawer:
            messages.error(request, "This item isn't in a drawer (container-level only) — nothing to light up.")
            return redirect("inventory:part_detail", pk=stock_item.part_id)
        segments = list(drawer.led_segments.all())
        if not segments:
            messages.error(request, "This drawer has no LED mapping configured yet (set it in /admin/).")
        elif not settings.LED_CONTROLLER_URL:
            messages.error(request, "No LED controller configured yet (LED_CONTROLLER_URL is unset).")
        else:
            import requests

            headers = {"X-Api-Key": settings.LED_CONTROLLER_KEY} if settings.LED_CONTROLLER_KEY else {}
            lit, errors = 0, []
            for segment in segments:
                payload = {
                    "strip": segment.led_strip,
                    "start_index": segment.led_start_index,
                    "count": segment.led_count,
                }
                if stock_item.bin_row:
                    payload["row"] = stock_item.bin_row
                try:
                    resp = requests.post(f"{settings.LED_CONTROLLER_URL}/locate", json=payload, headers=headers, timeout=3)
                    resp.raise_for_status()
                    lit += 1
                except requests.RequestException as exc:
                    errors.append(f"{segment.led_strip}: {exc}")

            if lit:
                bin_note = f", bin {stock_item.bin_number} (flashing row {stock_item.bin_row})" if stock_item.bin_number else ""
                messages.success(request, f"Lit up {lit} indicator{'s' if lit != 1 else ''} for {drawer}{bin_note}.")
            if errors:
                messages.error(request, "Couldn't reach the LED controller for: " + "; ".join(errors))
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


@login_required
def locate_drawer_led(request, pk):
    """Fires the "find the part" LED indicator for one drawer — POSTs to the Pi controller
    once per configured segment (a drawer can have more than one, e.g. a cabinet's left- and
    right-side strips both covering the same drawer range, both should light up together)."""
    drawer = get_object_or_404(Drawer, pk=pk)
    if request.method == "POST":
        segments = list(drawer.led_segments.all())
        if not segments:
            messages.error(request, "This drawer has no LED mapping configured yet (set it in /admin/).")
        elif not settings.LED_CONTROLLER_URL:
            messages.error(request, "No LED controller configured yet (LED_CONTROLLER_URL is unset).")
        else:
            import requests

            headers = {"X-Api-Key": settings.LED_CONTROLLER_KEY} if settings.LED_CONTROLLER_KEY else {}
            lit, errors = 0, []
            for segment in segments:
                payload = {
                    "strip": segment.led_strip,
                    "start_index": segment.led_start_index,
                    "count": segment.led_count,
                }
                try:
                    resp = requests.post(f"{settings.LED_CONTROLLER_URL}/locate", json=payload, headers=headers, timeout=3)
                    resp.raise_for_status()
                    lit += 1
                except requests.RequestException as exc:
                    errors.append(f"{segment.led_strip}: {exc}")

            if lit:
                messages.success(request, f"Lit up {lit} indicator{'s' if lit != 1 else ''} for {drawer}.")
            if errors:
                messages.error(request, "Couldn't reach the LED controller for: " + "; ".join(errors))
    return redirect("inventory:drawer_detail", pk=drawer.pk)


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


# --- Light controls -----------------------------------------------------------

def _led_post(endpoint, payload):
    """POST one command to the Pi's LED controller. Returns (ok, error_message)."""
    if not settings.LED_CONTROLLER_URL:
        return False, "No LED controller configured yet (LED_CONTROLLER_URL is unset)."
    import requests

    headers = {"X-Api-Key": settings.LED_CONTROLLER_KEY} if settings.LED_CONTROLLER_KEY else {}
    try:
        resp = requests.post(f"{settings.LED_CONTROLLER_URL}/{endpoint}", json=payload, headers=headers, timeout=5)
        resp.raise_for_status()
        return True, None
    except requests.RequestException as exc:
        return False, str(exc)


@login_required
def light_controls(request):
    return render(request, "inventory/light_controls.html")


@login_required
def led_set_defaults(request):
    if request.method == "POST":
        payload = {}
        brightness = request.POST.get("brightness")
        if brightness:
            try:
                payload["brightness"] = max(0.0, min(1.0, float(brightness) / 100))
            except ValueError:
                pass
        color = request.POST.get("color")  # "#rrggbb" from an <input type=color>
        if color and color.startswith("#") and len(color) == 7:
            payload["color"] = [int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)]
        ok, error = _led_post("set_defaults", payload)
        if ok:
            messages.success(request, "Updated light defaults.")
        else:
            messages.error(request, f"Couldn't reach the LED controller: {error}")
    return redirect("inventory:light_controls")


@login_required
def led_room_light(request):
    if request.method == "POST":
        on = request.POST.get("on") == "1"
        payload = {"on": on}
        color = request.POST.get("color")
        if on and color and color.startswith("#") and len(color) == 7:
            payload["color"] = [int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)]
        ok, error = _led_post("room_light", payload)
        if ok:
            messages.success(request, "Room light on." if on else "Room light off.")
        else:
            messages.error(request, f"Couldn't reach the LED controller: {error}")
    return redirect("inventory:light_controls")


@login_required
def led_demo(request):
    if request.method == "POST":
        ok, error = _led_post("demo", {})
        if ok:
            messages.success(request, "Demo running — enjoy the show!")
        else:
            messages.error(request, f"Couldn't reach the LED controller: {error}")
    return redirect("inventory:light_controls")
