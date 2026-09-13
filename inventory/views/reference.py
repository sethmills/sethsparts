"""The reference library: viewing it, and owning it.

The viewing half is the original feature — cheat sheets and pinouts, cached locally
so they survive their source page disappearing.

The editing half is the point of this module. The library previously shipped with four
categories baked into the code and no way to change them, so an owner could add a
document but never the shelf it belonged on. Everything here treats the library as the
owner's: categories are theirs to rename, reorder, add and remove, documents are
theirs to edit and delete, and the starter set is just a starting point that can be
emptied entirely if they want a blank library.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render

from .. import archiving
from ..models import ReferenceCategory, ReferenceDoc

# --- Viewing -----------------------------------------------------------------


@login_required
def reference_list(request):
    """The library, grouped by the owner's own categories.

    Categories come from the database now, not a constant. Empty categories are shown
    when explicitly selected so an owner can see a shelf they have just created and
    nothing has been filed on yet; otherwise they are skipped, because a wall of empty
    headings is noise while browsing.
    """
    key = request.GET.get("category") or ""
    categories = list(ReferenceCategory.objects.all())

    sections = []
    for category in categories:
        if key and category.key != key:
            continue
        docs = list(category.docs.all())
        if docs or key:
            sections.append((category, docs))

    return render(
        request,
        "inventory/reference_list.html",
        {
            "sections": sections,
            "categories": categories,
            "selected_category": key,
        },
    )


# --- Owning it ---------------------------------------------------------------


@login_required
def reference_manage(request):
    """Everything in the library, with the controls to change it."""
    categories = list(ReferenceCategory.objects.all())
    uncategorised_count = ReferenceDoc.objects.filter(category__isnull=True).count()
    return render(
        request,
        "inventory/reference_manage.html",
        {
            "categories": categories,
            "total_docs": ReferenceDoc.objects.count(),
            "uncategorised_count": uncategorised_count,
        },
    )


@login_required
def reference_add(request):
    categories = ReferenceCategory.objects.all()
    if request.method == "POST":
        doc = _save_doc(request, None)
        if doc is not None:
            messages.success(request, f"Added “{doc.title}”.")
            return redirect("inventory:reference_manage")
    return render(
        request,
        "inventory/reference_edit.html",
        {"categories": categories, "doc": None, "preselected_category": request.GET.get("category", "")},
    )


@login_required
def reference_edit(request, pk):
    doc = get_object_or_404(ReferenceDoc, pk=pk)
    categories = ReferenceCategory.objects.all()
    if request.method == "POST":
        changed = _save_doc(request, doc)
        if changed is not None:
            messages.success(request, f"Updated “{changed.title}”.")
            return redirect("inventory:reference_manage")
    return render(
        request,
        "inventory/reference_edit.html",
        {"categories": categories, "doc": doc, "preselected_category": doc.category_id},
    )


@login_required
def reference_delete(request, pk):
    """POST only, and named in the confirmation so a mis-click is visible.

    Nothing is cached or referenced by another record, so a straight delete is honest
    here — unlike a category, which is protected while documents still point at it.
    """
    doc = get_object_or_404(ReferenceDoc, pk=pk)
    if request.method == "POST":
        title = doc.title
        doc.delete()
        messages.success(request, f"Removed “{title}”.")
        return redirect("inventory:reference_manage")
    return render(request, "inventory/reference_delete.html", {"doc": doc})


@login_required
def reference_move(request, pk):
    """Move a document up or down within its category by swapping order values.

    A swap rather than a renumbering pass: it cannot fail halfway and leave the list
    in a state nobody meant, and two documents sharing an order value stay stable
    because the sort falls back to title.
    """
    doc = get_object_or_404(ReferenceDoc, pk=pk)
    if request.method == "POST":
        direction = request.POST.get("direction")
        siblings = list(ReferenceDoc.objects.filter(category=doc.category).order_by("order", "title"))
        index = next((i for i, d in enumerate(siblings) if d.pk == doc.pk), None)
        if index is not None:
            target = index - 1 if direction == "up" else index + 1
            if 0 <= target < len(siblings):
                siblings[index], siblings[target] = siblings[target], siblings[index]
                # Renumber the whole category in tens rather than swapping two values.
                # A swap looks tidier but collapses the moment several documents share
                # an order value — which they do, because the starter set ships every
                # one of them at 100. Swapping equal values is a no-op that looks like
                # a broken button.
                for position, sibling in enumerate(siblings, start=1):
                    new_order = position * 10
                    if sibling.order != new_order:
                        sibling.order = new_order
                        sibling.save(update_fields=["order"])
    return redirect("inventory:reference_manage")


# --- Categories --------------------------------------------------------------


@login_required
def reference_category_add(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "A category needs a name.")
        else:
            order_raw = (request.POST.get("order") or "").strip()
            category = ReferenceCategory.objects.create(
                name=name,
                key=_unique_key(name),
                order=int(order_raw) if order_raw.isdigit() else 100,
            )
            messages.success(request, f"Added category “{category.name}”.")
        return redirect("inventory:reference_manage")
    return redirect("inventory:reference_manage")


@login_required
def reference_category_edit(request, pk):
    category = get_object_or_404(ReferenceCategory, pk=pk)
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            category.name = name
        order_raw = (request.POST.get("order") or "").strip()
        if order_raw.isdigit():
            category.order = int(order_raw)
        # The key is deliberately not editable here. It is what links point at, so
        # renaming a category must not break every saved URL to it.
        category.save()
        messages.success(request, f"Updated “{category.name}”.")
    return redirect("inventory:reference_manage")


@login_required
def reference_category_delete(request, pk):
    """Refuses while documents are still filed under it.

    Deleting a shelf must not silently shred what was on it, so this reports what is
    in the way and lets the owner move those documents first.
    """
    category = get_object_or_404(ReferenceCategory, pk=pk)
    if request.method == "POST":
        name = category.name
        try:
            category.delete()
            messages.success(request, f"Deleted category “{name}”.")
        except ProtectedError:
            count = category.docs.count()
            messages.error(
                request,
                f"“{name}” still has {count} reference{'s' if count != 1 else ''} on it. "
                "Move or delete those first.",
            )
    return redirect("inventory:reference_manage")


# --- Helpers -----------------------------------------------------------------


def _save_doc(request, doc):
    """Create or update a document from a POST. Returns the doc, or None if invalid."""
    from django.core.files.uploadedfile import UploadedFile

    previous_url = doc.external_url if doc is not None else ""

    title = (request.POST.get("title") or "").strip()
    if not title:
        messages.error(request, "A reference needs a title.")
        return None

    category_id = request.POST.get("category") or None
    if not category_id:
        messages.error(request, "Pick a category — create one first if the list is empty.")
        return None

    order_raw = (request.POST.get("order") or "").strip()
    fields = {
        "title": title,
        "category_id": category_id,
        "description": (request.POST.get("description") or "").strip(),
        "external_url": (request.POST.get("external_url") or "").strip(),
        "order": int(order_raw) if order_raw.isdigit() else 100,
    }

    if doc is None:
        doc = ReferenceDoc(**fields)
    else:
        for key, value in fields.items():
            setattr(doc, key, value)

    upload = request.FILES.get("file")
    if isinstance(upload, UploadedFile):
        doc.file = upload
    elif request.POST.get("remove_file"):
        doc.file = None

    doc.save()

    # Archive the source document automatically. The whole point of the feature is
    # that the local copy is what you end up relying on, and a link nobody archived
    # is a link that will eventually 404. Bounded by ARCHIVE_TIMEOUT, and a failure is
    # recorded on the row rather than raised: a dead source link must not stop someone
    # filing a reference — it just has to be visible that the copy didn't happen.
    if archiving.archive_on_save_enabled() and doc.external_url:
        if not doc.file or previous_url != doc.external_url:
            archiving.archive_reference_doc(doc)

    return doc


def _unique_key(name):
    """A slug that is stable and does not collide with an existing category."""
    from django.utils.text import slugify

    base = slugify(name)[:40] or "category"
    key = base
    suffix = 2
    while ReferenceCategory.objects.filter(key=key).exists():
        key = f"{base[:36]}-{suffix}"
        suffix += 1
    return key


@login_required
def reference_archive(request, pk):
    """(Re)fetch the local copy for one document.

    Needed because the automatic attempt is bounded and expected to fail sometimes —
    a site that was down, a link that moved. Re-running it is a deliberate, visible
    action rather than something the owner has to guess at.
    """
    doc = get_object_or_404(ReferenceDoc, pk=pk)
    if request.method == "POST":
        result = archiving.archive_reference_doc(doc)
        if result.ok:
            messages.success(request, f"Archived “{doc.title}” ({result.content_type or 'file'}).")
        else:
            messages.error(request, f"Couldn't archive “{doc.title}”: {result.error}")
    return redirect(_safe_next(request) or "inventory:reference_manage")


def _safe_next(request):
    """Only accept a same-site path, so this cannot be turned into an open redirect.

    `?next=` values that arrive from a query string are attacker-controlled, and an
    unvalidated redirect would let a link to this app bounce someone to another site
    carrying this app's apparent authority.
    """
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return ""
