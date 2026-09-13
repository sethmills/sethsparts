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
    return {
        "site_name": site_name(),
        "site_country": country(),
        "unit_system": unit_system(),
        "setup_complete": bool(obj and obj.setup_completed_at),
        # "Configured", not "reachable" — the URL may be set while the Pi is off, and
        # templates should still offer the button so the failure message can explain
        # itself. These come from hardware_config, which prefers the address saved by
        # the setup wizard and falls back to the environment.
        "has_leds": has_leds(),
        "has_printer": has_printer(),
    }
