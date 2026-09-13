"""Moving-day capture: quick box creation, photos, and dictated notes."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..models import (
    Container,
    ContainerPhoto,
    IntakeNote,
    Location,
)



# --- Moving-day intake: quick container creation, photos, dictated notes ----

@login_required
def quick_add_container(request):
    """For packing up boxes during a move: assign the next container number, print
    its barcode immediately, and worry about contents later (photo + dictated note
    on the container's own page)."""
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
    all to a container now, or leaving them unassigned to sort out later from the
    queue. This is the entry point the intake queue itself was missing: previously the
    only way to add a note was from an already-chosen container's own page."""
    if request.method == "POST":
        container_id = request.POST.get("container") or None
        container = get_object_or_404(Container, pk=container_id) if container_id else None
        source = request.POST.get("source") or IntakeNote.TYPED
        if source not in dict(IntakeNote.SOURCE_CHOICES):
            source = IntakeNote.TYPED

        lines = [line.strip() for line in (request.POST.get("text") or "").splitlines()]
        lines = [line for line in lines if line]

        if not lines:
            messages.error(request, "No items received — one per line.")
        else:
            IntakeNote.objects.bulk_create(
                [IntakeNote(container=container, text=line, source=source) for line in lines]
            )
            messages.success(request, f"Queued {len(lines)} item{'s' if len(lines) != 1 else ''} for review.")
            return redirect("inventory:intake_queue")

    return render(
        request,
        "inventory/bulk_intake.html",
        {"containers": Container.objects.order_by("number")},
    )


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
