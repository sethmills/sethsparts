"""Template context available on every page.

The capability flags are what let one codebase serve an install with no lights and
no label printer: templates hide what isn't configured rather than showing a button
that fails when pressed. That is the difference between "this app works without the
hardware" and "this app claims to work without the hardware".
"""
from __future__ import annotations


def site_context(request):
    from .hardware_config import has_leds, has_printer
    from .site_config import country, get_site_settings, site_name, unit_system

    obj = get_site_settings()
    unread = 0
    shopping = 0
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        try:
            from .models import Message, ShoppingListItem

            unread = Message.objects.filter(direction=Message.INBOUND, read=False).count()
            shopping = ShoppingListItem.objects.filter(bought=False).count()
        except Exception:
            # Before migrations have created the table there is nothing to count.
            unread = 0
            shopping = 0
    return {
        "site_name": site_name(),
        "site_country": country(),
        "unit_system": unit_system(),
        "setup_complete": bool(obj and obj.setup_completed_at),
        "theme": obj.theme if obj and obj.theme else "precision",
        "unread_messages": unread,
        "shopping_list_count": shopping,
        "email_configured": bool(obj and obj.email_enabled and obj.smtp_host and obj.smtp_user and obj.smtp_password),
        # "Configured", not "reachable" — the URL may be set while the Pi is off, and
        # templates should still offer the button so the failure message can explain
        # itself. These come from hardware_config, which prefers the address saved by
        # the setup wizard and falls back to the environment.
        "has_leds": has_leds(),
        "has_printer": has_printer(),
    }
