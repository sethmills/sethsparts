"""The owner's own site settings, read safely from anywhere.

This is read from `AppConfig.ready()` (before migrations may have run), from
middleware on every request, and from the setup wizard that creates the row in the
first place. So every accessor here returns a sane default instead of raising —
none of those callers can do anything useful with an exception, and a brand-new
clone genuinely has no row yet.

The defaults matter as much as the values. Until someone names their own install
the app calls itself "My Parts", and until setup finishes it knows it is unfinished.
"""
from __future__ import annotations

from django.contrib import admin

DEFAULT_SITE_NAME = "My Parts"
DEFAULT_TIMEZONE = "UTC"
DEFAULT_UNIT_SYSTEM = "metric"


def get_site_settings():
    """The singleton row, or None if it doesn't exist or the table isn't there yet."""
    try:
        from .models import SiteSettings

        return SiteSettings.objects.first()
    except Exception:
        # No database yet (a fresh clone running its first migrate), or no table.
        # Every caller has a fallback, so this is not an error worth propagating.
        return None


def site_name() -> str:
    obj = get_site_settings()
    return (obj.site_name if obj and obj.site_name else DEFAULT_SITE_NAME)


def timezone_name() -> str:
    obj = get_site_settings()
    return (obj.timezone if obj and obj.timezone else DEFAULT_TIMEZONE)


def unit_system() -> str:
    obj = get_site_settings()
    return (obj.unit_system if obj and obj.unit_system else DEFAULT_UNIT_SYSTEM)


def country() -> str:
    obj = get_site_settings()
    return ((obj.country if obj else "") or "").upper()


def setup_is_complete() -> bool:
    """True once the setup wizard has finished.

    A missing row counts as NOT complete. That is what a brand-new install looks
    like, and it is precisely the state that should send someone to the wizard
    rather than to a login page for an account that does not exist yet.
    """
    obj = get_site_settings()
    return bool(obj and obj.setup_completed_at)


def apply_site_branding(obj=None) -> str:
    """Push the chosen name into the admin.

    Templates get the name from a context processor, but the admin reads plain
    attributes that Django assigns once at import — so they need setting again
    whenever the name changes, or the admin header would keep showing the previous
    name until the process restarted.

    `obj` lets a caller that has already read the SiteSettings row pass it in, so
    the per-request caller does not pay for a second query.

    Deliberately never called from `AppConfig.ready()`: that runs while the app
    registry is still loading, and Django warns about database access there. The
    middleware calls it on the first request instead, which is soon enough for
    something only a human reads.
    """
    if obj is None:
        obj = get_site_settings()
    name = (obj.site_name if obj and obj.site_name else DEFAULT_SITE_NAME)
    admin.site.site_header = name
    admin.site.site_title = name
    admin.site.index_title = f"{name} administration"
    return name
