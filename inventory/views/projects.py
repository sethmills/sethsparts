"""Projects, BOM revisions, builds, and the reorder dashboard."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..models import (
    Build,
    BuildConsumption,
    Category,
    Part,
    Project,
)

from ._shared import _consume_stock, _current_stock, _reorder_link



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
            needs_reorder.append({
                "part": part,
                "have": have,
                "min_quantity": part.min_quantity,
                "shortfall": max(1, part.min_quantity - have),
                "reorder_link": _reorder_link(part),
            })

    return render(
        request,
        "inventory/reorder.html",
        {"needs_reorder": needs_reorder, "categories": Category.objects.all(), "selected_category": category_id},
    )
