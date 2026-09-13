"""Where the LED controller and the label printer live.

Two sources, in priority order:

1. **SiteSettings**, written by the setup wizard. This is the normal case for
   someone who installed the app and configured it from a browser.
2. **Environment variables** (`LED_CONTROLLER_URL` and friends), which is how Seth's
   own deployment is configured and how a container is usually set up.

Database first, environment as fallback — not the other way round. If the environment
won this, a value typed into the wizard would appear to save and then silently do
nothing, which is the worst possible outcome for a setup screen. An install that has
never opened the wizard has empty database fields and behaves exactly as it did
before any of this existed.

Both sources mean "the owner has this hardware" — never "it is reachable". The only
way to learn reachability is to call it, which is what the wizard's test buttons and
the health check do.
"""
from __future__ import annotations

from django.conf import settings

from .site_config import get_site_settings


def _value(db_field: str, env_attr: str) -> str:
    obj = get_site_settings()
    from_db = (getattr(obj, db_field, "") if obj else "") or ""
    if from_db.strip():
        return from_db.strip()
    return (getattr(settings, env_attr, "") or "").strip()


def led_url() -> str:
    return _value("led_controller_url", "LED_CONTROLLER_URL")


def led_key() -> str:
    return _value("led_controller_key", "LED_CONTROLLER_KEY")


def printer_url() -> str:
    return _value("label_printer_url", "LABEL_PRINTER_URL")


def printer_key() -> str:
    return _value("label_printer_key", "LABEL_PRINTER_KEY")


def has_leds() -> bool:
    return bool(led_url())


def has_printer() -> bool:
    return bool(printer_url())


def led_source() -> str:
    """'settings', 'environment' or '' — so a setup screen can say where a value
    actually came from instead of implying the box it is showing is the whole story."""
    return _source("led_controller_url", "LED_CONTROLLER_URL")


def printer_source() -> str:
    return _source("label_printer_url", "LABEL_PRINTER_URL")


def _source(db_field: str, env_attr: str) -> str:
    obj = get_site_settings()
    if (getattr(obj, db_field, "") if obj else "").strip():
        return "settings"
    if (getattr(settings, env_attr, "") or "").strip():
        return "environment"
    return ""
