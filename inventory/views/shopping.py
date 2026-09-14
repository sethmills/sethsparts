"""The shopping list — parts to buy, seeded from the reorder dashboard."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Part, ShoppingListItem


@login_required
def shopping_list(request):
    items = ShoppingListItem.objects.select_related("part").all()
    return render(request, "inventory/shopping_list.html", {"items": items})


@login_required
def shopping_list_add(request, pk):
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        raw_qty = (request.POST.get("quantity") or "").strip()
        try:
            quantity = max(1, int(raw_qty)) if raw_qty else 1
        except ValueError:
            quantity = 1
        item, created = ShoppingListItem.objects.get_or_create(
            part=part, defaults={"quantity": quantity}
        )
        if not created:
            item.quantity = max(item.quantity, quantity)
            item.bought = False
            item.save(update_fields=["quantity", "bought"])
        messages.success(request, f"Added {part.name} to the shopping list.")
    return redirect(request.POST.get("next") or "inventory:reorder")


@login_required
def shopping_list_toggle(request, pk):
    item = get_object_or_404(ShoppingListItem, pk=pk)
    if request.method == "POST":
        item.bought = not item.bought
        item.save(update_fields=["bought"])
    return redirect("inventory:shopping_list")


@login_required
def shopping_list_clear(request):
    if request.method == "POST":
        removed = ShoppingListItem.objects.filter(bought=True).delete()[0]
        if removed:
            messages.success(request, f"Cleared {removed} bought item{'s' if removed != 1 else ''}.")
    return redirect("inventory:shopping_list")


@login_required
def shopping_list_export(request):
    items = (
        ShoppingListItem.objects.filter(bought=False)
        .select_related("part")
        .order_by("part__manufacturer", "part__name")
    )
    lines = ["Shopping list", "=" * 13, ""]
    current_mfr = None
    for item in items:
        mfr = item.part.manufacturer or "Other"
        if mfr != current_mfr:
            if current_mfr is not None:
                lines.append("")
            lines.append(f"[{mfr}]")
            current_mfr = mfr
        line = f"- {item.part.name}"
        if item.quantity > 1:
            line += f"  x{item.quantity}"
        if item.part.reorder_url:
            line += f"  ({item.part.reorder_url})"
        lines.append(line)

    response = HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = "attachment; filename=shopping-list.txt"
    return response
