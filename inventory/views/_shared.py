"""Small helpers shared across the view modules. Kept here rather than in any
one topic module so nothing has to import another topic module just for a sum."""
import re
from urllib.parse import quote
from django.db.models import Sum

from ..models import (
    Container,
    Drawer,
    StockItem,
)



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


def _slugify_drawer_code(container_number, label):
    # "drawer b2" -> "B2"
    suffix = label.strip().upper().replace("DRAWER", "").strip()
    return f"D{container_number}{suffix}"


def _location_choices():
    """Combined container/drawer choices for the "add stock" dropdown, value format
    'container:<number>' or 'drawer:<pk>'."""
    choices = []
    for c in Container.objects.order_by("number"):
        choices.append((f"container:{c.number}", f"#{c.number} ({c.container_type})"))
    for d in Drawer.objects.select_related("container").order_by("container__number", "label"):
        choices.append((f"drawer:{d.pk}", f"#{d.container.number} / {d.label}"))
    return choices


def _drawer_number(drawer):
    match = re.search(r"\d+", drawer.label)
    return int(match.group()) if match else 0
