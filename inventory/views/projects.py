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
from .. import audit



# --- Phase 4: BOM / Projects -------------------------------------------------

@login_required
def project_list(request):
    projects = Project.objects.all()
    return render(request, "inventory/project_list.html", {"projects": projects})


@login_required
def create_project(request):
    """Create a project from the Projects page.

    Projects used to be creatable only through /admin/, which sent the owner on an
    unnecessary detour — the page that exists to browse projects should also be the
    page that makes them. BOM revisions are left in /admin/ for now: they are the
    fiddly half (parts, quantities, versioning) and deserve their own page rather
    than a cramped inline form.
    """
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Give the project a name.")
        else:
            status = request.POST.get("status") or Project.ACTIVE
            if status not in dict(Project.STATUS_CHOICES):
                status = Project.ACTIVE
            project = Project.objects.create(
                name=name,
                description=(request.POST.get("description") or "").strip(),
                status=status,
            )
            messages.success(request, f"Created project “{project.name}”.")
            return redirect("inventory:project_detail", pk=project.pk)
    return redirect("inventory:project_list")


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
        audit.log(
            "build.consume", part=line.part, actor=request.user,
            build=build.pk, requested=needed, consumed=consumed,
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
    from datetime import timedelta

    from django.db.models import Sum
    from django.utils import timezone

    category_id = request.GET.get("category")
    parts = Part.objects.filter(min_quantity__isnull=False).select_related("category")
    if category_id:
        parts = parts.filter(category_id=category_id)

    # How much of each part has actually been consumed in the last 30 days, from
    # build records. A part burning 50/month at a threshold of 10 is a different
    # problem from one using 3/month — velocity is what tells them apart.
    cutoff = timezone.now() - timedelta(days=30)
    velocity = {
        row["part"]: row["total"]
        for row in BuildConsumption.objects.filter(build__built_at__gte=cutoff)
        .values("part")
        .annotate(total=Sum("quantity_consumed"))
    }

    needs_reorder = []
    for part in parts:
        have = _current_stock(part)
        if have < part.min_quantity:
            needs_reorder.append({
                "part": part,
                "have": have,
                "min_quantity": part.min_quantity,
                "shortfall": max(1, part.min_quantity - have),
                "used_30d": velocity.get(part.pk, 0),
                "reorder_link": _reorder_link(part),
            })

    return render(
        request,
        "inventory/reorder.html",
        {"needs_reorder": needs_reorder, "categories": Category.objects.all(), "selected_category": category_id},
    )
