"""Label generation, printing, and barcode SVGs."""
import base64
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse

from ..models import (
    Container,
    Drawer,
)

from ._shared import _slugify_drawer_code



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


@login_required
def custom_label(request):
    """A one-off/impromptu label designer -- type text, pick one of the 3 physical label
    sizes Seth owns, tweak font size/bold/italic, optionally add a barcode, preview it, and
    send it straight to the Zebra GK420T via the Pi's print-bridge. Deliberately stateless —
    nothing here is saved, this is for "I just need a quick label right now," not cataloged
    inventory labels (those are /labels/)."""
    from . import label_printing

    if request.method == "POST":
        values = {
            "text": request.POST.get("text", ""),
            "size": request.POST.get("size", "large"),
            "font_pt": request.POST.get("font_pt", "24"),
            "bold": bool(request.POST.get("bold")),
            "italic": bool(request.POST.get("italic")),
            "barcode_value": request.POST.get("barcode_value", ""),
        }
        action = request.POST.get("action", "preview")
    else:
        values = {"text": "", "size": "large", "font_pt": "24", "bold": False, "italic": False, "barcode_value": ""}
        action = None

    if values["size"] not in label_printing.LABEL_SIZES:
        values["size"] = "large"
    try:
        font_pt = max(6, min(120, int(values["font_pt"])))
    except (TypeError, ValueError):
        font_pt = 24

    preview_data_uri = None
    if values["text"].strip() or values["barcode_value"].strip():
        png_bytes = label_printing.render_label_png_bytes(
            values["text"], values["size"], font_pt, values["bold"], values["italic"], values["barcode_value"]
        )
        preview_data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    if action == "print":
        if not values["text"].strip() and not values["barcode_value"].strip():
            messages.error(request, "Nothing to print — add some text or a barcode value first.")
        else:
            ok, error = label_printing.print_label(
                values["text"], values["size"], font_pt, values["bold"], values["italic"], values["barcode_value"]
            )
            if ok:
                messages.success(request, "Sent to the printer.")
            else:
                messages.error(request, f"Couldn't print: {error}")

    return render(
        request,
        "inventory/custom_label.html",
        {
            "values": values,
            "font_pt": font_pt,
            "label_sizes": label_printing.LABEL_SIZES,
            "preview_data_uri": preview_data_uri,
        },
    )
