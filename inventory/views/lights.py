"""Everything that talks to the Pi's LED controller -- "find the part"
locate animations, room light, and demo mode."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..models import (
    Bin,
    Drawer,
    StockItem,
)



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


def _locate_drawer(drawer, row=None, col=None):
    """POSTs /locate to the Pi controller once per configured LED segment for this drawer
    (a drawer can have more than one, e.g. a cabinet's left- and right-side strips both
    covering the same drawer range). row/col (1-4, optional) convey which bin within the
    drawer -- each strip shows only its own value (the "-left" strip lights `row` LEDs,
    the "-right" strip lights `col` LEDs), not both, per Seth's request: the two physical
    strips split the readout between them rather than each showing a combined row+column
    display on its own. Returns (lit_count, errors, error_reason) where error_reason is a
    short string set only when nothing was attempted at all (no segments configured, or no
    controller configured)."""
    segments = list(drawer.led_segments.all())
    if not segments:
        return 0, [], "This drawer has no LED mapping configured yet (set it in /admin/)."
    if not settings.LED_CONTROLLER_URL:
        return 0, [], "No LED controller configured yet (LED_CONTROLLER_URL is unset)."

    import requests

    headers = {"X-Api-Key": settings.LED_CONTROLLER_KEY} if settings.LED_CONTROLLER_KEY else {}
    lit, errors = 0, []
    for segment in segments:
        payload = {
            "strip": segment.led_strip,
            "start_index": segment.led_start_index,
            "count": segment.led_count,
        }
        if row and segment.led_strip.endswith("-left"):
            payload["row"] = row
        if col and segment.led_strip.endswith("-right"):
            payload["col"] = col
        try:
            resp = requests.post(f"{settings.LED_CONTROLLER_URL}/locate", json=payload, headers=headers, timeout=3)
            resp.raise_for_status()
            lit += 1
        except requests.RequestException as exc:
            errors.append(f"{segment.led_strip}: {exc}")
    return lit, errors, None


@login_required
def locate_drawer_led(request, pk):
    drawer = get_object_or_404(Drawer, pk=pk)
    if request.method == "POST":
        lit, errors, error_reason = _locate_drawer(drawer)
        if error_reason:
            messages.error(request, error_reason)
        if lit:
            messages.success(request, f"Lit up {lit} indicator{'s' if lit != 1 else ''} for {drawer}.")
        if errors:
            messages.error(request, "Couldn't reach the LED controller for: " + "; ".join(errors))
    return redirect("inventory:drawer_detail", pk=drawer.pk)


@login_required
def locate_stock_item(request, pk):
    """Like locate_drawer_led, but for one specific StockItem — if it has a bin_number
    set, includes which row/column (1-4 each) so the animation conveys bin-level detail,
    not just "somewhere in this drawer"."""
    stock_item = get_object_or_404(StockItem, pk=pk)
    if request.method == "POST":
        drawer = stock_item.drawer
        if not drawer:
            messages.error(request, "This item isn't in a drawer (container-level only) — nothing to light up.")
            return redirect("inventory:part_detail", pk=stock_item.part_id)

        lit, errors, error_reason = _locate_drawer(drawer, row=stock_item.bin_row, col=stock_item.bin_column)
        if error_reason:
            messages.error(request, error_reason)
        if lit:
            bin_note = f", bin {stock_item.bin_number} (row {stock_item.bin_row}, column {stock_item.bin_column})" if stock_item.bin_number else ""
            messages.success(request, f"Lit up {lit} indicator{'s' if lit != 1 else ''} for {drawer}{bin_note}.")
        if errors:
            messages.error(request, "Couldn't reach the LED controller for: " + "; ".join(errors))
    return redirect("inventory:part_detail", pk=stock_item.part_id)


@login_required
def locate_bin(request, pk):
    b = get_object_or_404(Bin.objects.select_related("drawer"), pk=pk)
    if request.method == "POST":
        lit, errors, error_reason = _locate_drawer(b.drawer, row=b.bin_row, col=b.bin_column)
        if error_reason:
            messages.error(request, error_reason)
        if lit:
            messages.success(request, f"Lit up {lit} indicator{'s' if lit != 1 else ''} for {b} (row {b.bin_row}, column {b.bin_column}).")
        if errors:
            messages.error(request, "Couldn't reach the LED controller for: " + "; ".join(errors))
    return redirect("inventory:bin_detail", pk=b.pk)


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
        on = request.POST.get("on") == "1"
        ok, error = _led_post("demo", {"on": on})
        if ok:
            messages.success(request, "Demo running — enjoy the show!" if on else "Demo stopped.")
        else:
            messages.error(request, f"Couldn't reach the LED controller: {error}")
    return redirect("inventory:light_controls")
