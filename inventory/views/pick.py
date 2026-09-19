"""Pick-list / walk mode: gather a project's BOM parts one at a time.

Each step shows one part, fires the drawer LED for it, and lets the owner mark it
pulled or missing — then moves on. The point is the physical act of walking the
workshop with a phone or the kiosk, not tabbing between the BOM page and drawer
lookups.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Project, ShoppingListItem, StockItem
from .lights import _locate_drawer

SESSION_KEY = "pick_session"


def _lines_for(project):
    revision = project.latest_revision
    if not revision:
        return []
    return [
        {"part_pk": line.part_id, "name": line.part.name, "quantity": line.quantity_required}
        for line in revision.lines.select_related("part")
    ]


def _start(project):
    return {
        "project_pk": project.pk,
        "project_name": project.name,
        "lines": _lines_for(project),
        "index": 0,
        "pulled": [],
        "missing": [],
    }


def _done(session):
    return session["index"] >= len(session["lines"])


def _locations_for(part_pk):
    stock = StockItem.objects.filter(part_id=part_pk).select_related("container", "drawer")
    return [
        {
            "container": si.container.number,
            "drawer": si.drawer.label if si.drawer else None,
            "bin": si.bin_number,
            "quantity": si.quantity,
        }
        for si in stock
    ]


def _fire_led(session, request):
    """Light the drawer holding the current part, best-effort. The LED is local
    hardware and this runs on a button press (start / pulled / missing), never on a
    page render, so a slow or absent controller only ever delays a click."""
    if _done(session):
        return
    line = session["lines"][session["index"]]
    stock = (
        StockItem.objects.filter(part_id=line["part_pk"], drawer__isnull=False)
        .select_related("drawer")
        .order_by("-quantity")
        .first()
    )
    if not stock:
        return
    row = col = None
    if stock.bin_number:
        row = (stock.bin_number - 1) // 4 + 1
        col = (stock.bin_number - 1) % 4 + 1
    lit, _errors, reason = _locate_drawer(stock.drawer, row=row, col=col)
    if lit:
        messages.info(request, f"Lit up {stock.drawer.label} for “{line['name']}”.")
    elif reason:
        messages.info(request, reason)


@login_required
def pick(request, pk):
    project = get_object_or_404(Project, pk=pk)
    session = request.session.get(SESSION_KEY)
    if not session or session.get("project_pk") != pk:
        session = _start(project)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "start":
            session = _start(project)
        elif not _done(session) and action in ("pulled", "missing"):
            line = session["lines"][session["index"]]
            (session["pulled"] if action == "pulled" else session["missing"]).append(line)
            session["index"] += 1
        elif _done(session) and action == "add_missing_to_list":
            for line in session["missing"]:
                item, created = ShoppingListItem.objects.get_or_create(
                    part_id=line["part_pk"], defaults={"quantity": line["quantity"]}
                )
                if not created:
                    item.quantity = max(item.quantity, line["quantity"])
                    item.bought = False
                    item.save(update_fields=["quantity", "bought"])
            messages.success(request, f"Added {len(session['missing'])} missing part(s) to the shopping list.")

        request.session[SESSION_KEY] = session
        request.session.modified = True
        if action in ("start", "pulled", "missing"):
            _fire_led(session, request)
        return redirect("inventory:pick", pk=pk)

    return render(request, "inventory/pick.html", _context(project, session))


def _context(project, session):
    done = _done(session)
    current = session["lines"][session["index"]] if not done else None
    return {
        "project": project,
        "done": done,
        "current": current,
        "locations": _locations_for(current["part_pk"]) if current else [],
        "index": (session["index"] + 1) if not done else len(session["lines"]),
        "total": len(session["lines"]),
        "pulled_count": len(session["pulled"]),
        "missing": session["missing"],
        "missing_count": len(session["missing"]),
    }
