"""Template context available on every page.

The capability flags are what let one codebase serve an install with no lights and
no label printer: templates hide what isn't configured rather than showing a button
that fails when pressed. That is the difference between "this app works without the
hardware" and "this app claims to work without the hardware".
"""
from __future__ import annotations


def site_context(request):
    from django.conf import settings

    from .site_config import country, get_site_settings, site_name, unit_system

    obj = get_site_settings()
    return {
        "site_name": site_name(),
        "site_country": country(),
        "unit_system": unit_system(),
        "setup_complete": bool(obj and obj.setup_completed_at),
        # Configured-but-absent is a real case: the URL is set but the Pi is off.
        # These flags mean "the owner has this hardware", not "it is reachable".
        "has_leds": bool(getattr(settings, "LED_CONTROLLER_URL", "")),
        "has_printer": bool(getattr(settings, "LABEL_PRINTER_URL", "")),
    }
