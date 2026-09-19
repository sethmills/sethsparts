"""Moving-day capture: quick box creation, photos, and dictated notes."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..models import (
    Bin,
    Container,
    ContainerPhoto,
    Drawer,
    IntakeNote,
    Location,
)

from .bins import MAX_BINS



# --- Moving-day intake: quick container creation, photos, dictated notes ----

@login_required
def quick_add_container(request):
    """The moving-day flow in one screen: create the next tote/box, list its contents
    now (typed or dictated), and print its barcode — no separate "add a note later"
    detour required. A photo can still be added from the container's own page."""
    existing_types = (
        Container.objects.exclude(container_type="").values_list("container_type", flat=True).distinct().order_by("container_type")
    )
    if request.method == "POST":
        container_type = (request.POST.get("container_type") or "black tote").strip()
        location_id = request.POST.get("location") or None
        next_number = (Container.objects.aggregate(m=Max("number"))["m"] or 0) + 1
        container = Container.objects.create(
            number=next_number,
            container_type=container_type,
            location_id=location_id,
            barcode_id=f"C{next_number}",
        )

        lines = [line.strip() for line in (request.POST.get("text") or "").splitlines()]
        lines = [line for line in lines if line]
        source = request.POST.get("source") or IntakeNote.TYPED
        if source not in dict(IntakeNote.SOURCE_CHOICES):
            source = IntakeNote.TYPED
        if lines:
            IntakeNote.objects.bulk_create(
                [IntakeNote(container=container, text=line, source=source) for line in lines]
            )

        if lines:
            messages.success(
                request,
                f"Created container #{container.number} with {len(lines)} item{'s' if len(lines) != 1 else ''} listed — print its barcode below, then stick it on the box.",
            )
        else:
            messages.success(request, f"Created container #{container.number} — print its barcode below, then stick it on the box.")
        return redirect(f"{reverse('inventory:print_labels')}?ids=c{container.pk}")

    return render(
        request,
        "inventory/quick_add_container.html",
        {"existing_types": existing_types, "locations": Location.objects.all()},
    )


@login_required
def add_container_photo(request, number):
    container = get_object_or_404(Container, number=number)
    if request.method == "POST":
        photo = request.FILES.get("photo")
        if not photo:
            messages.error(request, "No photo received.")
        else:
            ContainerPhoto.objects.create(container=container, image=photo)
            messages.success(request, "Photo added.")
    return redirect("inventory:container_detail", number=container.number)


@login_required
def add_intake_note(request, number):
    container = get_object_or_404(Container, number=number)
    if request.method == "POST":
        text = (request.POST.get("text") or "").strip()
        source = request.POST.get("source") or IntakeNote.TYPED
        if source not in dict(IntakeNote.SOURCE_CHOICES):
            source = IntakeNote.TYPED
        if not text:
            messages.error(request, "No note text received.")
        else:
            IntakeNote.objects.create(container=container, text=text, source=source)
            messages.success(request, "Note queued for review.")
    return redirect("inventory:container_detail", number=container.number)


@login_required
def bulk_intake(request):
    """Add a batch of quick notes at once -- one per line -- optionally assigning them
    all to a location now, or leaving them unassigned to sort out later from the
    queue. A location is the finest granularity known: a bin, a drawer, or a box/tote.
    This is the entry point the intake queue itself was missing: previously the
    only way to add a note was from an already-chosen container's own page."""
    if request.method == "POST":
        container_id = request.POST.get("container") or None
        drawer_id = request.POST.get("location_drawer") or None
        bin_id = request.POST.get("location_bin") or None

        container = drawer = bin_obj = None
        if bin_id:
            bin_obj = get_object_or_404(Bin, pk=bin_id)
        elif drawer_id:
            drawer = get_object_or_404(Drawer, pk=drawer_id)
        elif container_id:
            container = get_object_or_404(Container, pk=container_id)

        source = request.POST.get("source") or IntakeNote.TYPED
        if source not in dict(IntakeNote.SOURCE_CHOICES):
            source = IntakeNote.TYPED

        lines = [line.strip() for line in (request.POST.get("text") or "").splitlines()]
        lines = [line for line in lines if line]

        if not lines:
            messages.error(request, "No items received — one per line.")
        else:
            IntakeNote.objects.bulk_create(
                [IntakeNote(container=container, drawer=drawer, bin=bin_obj, text=line, source=source) for line in lines]
            )
            messages.success(request, f"Queued {len(lines)} item{'s' if len(lines) != 1 else ''} for review.")
            return redirect("inventory:intake_queue")

    return render(
        request,
        "inventory/bulk_intake.html",
        {
            "containers": Container.objects.order_by("number"),
            "drawers": Drawer.objects.select_related("container").order_by("container__number", "label"),
            "bins": Bin.objects.select_related("drawer").order_by("drawer__container__number", "drawer__label", "bin_number"),
        },
    )


@login_required
def add_intake_location(request):
    """Create a location on the spot from the intake form.

    Seth's fork, exactly: "will this location have bins inside it?" — yes means a
    cabinet (a container whose drawers are added later); no means either a bin inside
    an existing drawer, or a tote. Every path ends with a barcode, either generated
    and sent to the printer or scanned from an existing physical label.
    """
    if request.method != "POST":
        return redirect("inventory:bulk_intake")

    if request.POST.get("has_bins"):
        next_number = (Container.objects.aggregate(m=Max("number"))["m"] or 0) + 1
        container = Container.objects.create(
            number=next_number, container_type="cabinets", barcode_id=f"C{next_number}"
        )
        messages.success(request, f"Created cabinet #{next_number} — print its barcode below, then stick it on the cabinet.")
        return redirect(f"{reverse('inventory:print_labels')}?ids=c{container.pk}")

    kind = request.POST.get("kind") or "bin"
    if kind == "bin":
        return _create_intake_bin(request)
    return _create_intake_tote(request)


def _create_intake_bin(request):
    drawer = get_object_or_404(Drawer, pk=request.POST.get("drawer"))
    try:
        bin_number = int(request.POST.get("bin_number") or 1)
    except ValueError:
        bin_number = 1
    bin_number = max(1, min(drawer.bin_count or 1, bin_number))

    bin_obj, created = Bin.objects.get_or_create(drawer=drawer, bin_number=bin_number)

    if (request.POST.get("barcode_action") or "generate") == "scan":
        code = (request.POST.get("code") or "").strip()
        if not code:
            messages.error(request, "No barcode scanned — generate one instead, or scan the label again.")
            return redirect("inventory:bulk_intake")
        conflict = Bin.objects.filter(barcode_id=code).exclude(pk=bin_obj.pk).first()
        if conflict:
            messages.error(request, f"That barcode is already linked to {conflict}.")
            return redirect("inventory:bulk_intake")
        bin_obj.barcode_id = code
        bin_obj.save(update_fields=["barcode_id"])
        messages.success(request, f"Linked barcode {code} to {bin_obj}.")
        return redirect("inventory:bulk_intake")

    if not bin_obj.barcode_id:
        bin_obj.barcode_id = f"B{drawer.container.number}D{drawer.pk}B{bin_number:02d}"
        bin_obj.save(update_fields=["barcode_id"])
    messages.success(request, f"{'Created' if created else 'Found'} {bin_obj} — print its barcode below.")
    return redirect(f"{reverse('inventory:print_labels')}?ids=b{bin_obj.pk}")


def _create_intake_tote(request):
    next_number = (Container.objects.aggregate(m=Max("number"))["m"] or 0) + 1
    tote_type = (request.POST.get("tote_type") or "tote").strip() or "tote"

    barcode_id = f"C{next_number}"
    if (request.POST.get("barcode_action") or "generate") == "scan":
        code = (request.POST.get("code") or "").strip()
        if code:
            conflict = Container.objects.filter(barcode_id=code).first()
            if conflict:
                messages.error(request, f"That barcode is already linked to {conflict}.")
                return redirect("inventory:bulk_intake")
            barcode_id = code

    container = Container.objects.create(number=next_number, container_type=tote_type, barcode_id=barcode_id)
    messages.success(request, f"Created {tote_type} #{next_number} — print its barcode below.")
    return redirect(f"{reverse('inventory:print_labels')}?ids=c{container.pk}")


@login_required
def intake_queue(request):
    notes = IntakeNote.objects.filter(reviewed=False).select_related("container")
    return render(
        request,
        "inventory/intake_queue.html",
        {"notes": notes, "containers": Container.objects.order_by("number")},
    )


@login_required
def assign_intake_note_container(request, pk):
    note = get_object_or_404(IntakeNote, pk=pk)
    if request.method == "POST":
        container_id = request.POST.get("container") or None
        note.container = get_object_or_404(Container, pk=container_id) if container_id else None
        note.save(update_fields=["container"])
        messages.success(request, f"Assigned to {note.container}." if note.container else "Cleared assignment.")
    return redirect("inventory:intake_queue")


@login_required
def mark_intake_note_reviewed(request, pk):
    note = get_object_or_404(IntakeNote, pk=pk)
    if request.method == "POST":
        note.reviewed = True
        note.save(update_fields=["reviewed"])
        messages.success(request, "Marked reviewed.")
    return redirect("inventory:intake_queue")
