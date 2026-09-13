"""Request-level behaviour that depends on the owner's own settings.

Two jobs, both of which need the SiteSettings row and both of which are per-request
rather than per-process:

1. **The owner's timezone.** Django stores UTC (`USE_TZ = True`) and renders in the
   *active* zone. Without activating the configured one, an install in the US would
   display every timestamp in whatever the container's TZ happened to be — which is
   the bug that made this a middleware rather than a line in settings.py.

2. **Sending a browser to setup.** A fresh clone has no account, so its root URL
   previously led to a login page with nothing to log in with. While setup is
   outstanding, browsers are pointed at the wizard instead.
"""
from __future__ import annotations

from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone


class SiteTimezoneMiddleware:
    """Renders every timestamp in the owner's configured zone.

    Also applies the site's name to the admin header, reusing the row it has already
    read. Doing it here rather than in `AppConfig.ready()` keeps database access out
    of app startup, which Django explicitly discourages.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .site_config import DEFAULT_TIMEZONE, apply_site_branding, get_site_settings

        obj = get_site_settings()
        apply_site_branding(obj)

        zone = (obj.timezone if obj and obj.timezone else DEFAULT_TIMEZONE)
        activated = False
        if zone:
            try:
                timezone.activate(zone)
                activated = True
            except Exception:
                # An unknown zone name (hand-edited, or a typo from the wizard) must
                # not take the site down — it just renders in UTC. The wizard
                # validates the name before saving, so this is a backstop.
                activated = False
        try:
            return self.get_response(request)
        finally:
            if activated:
                # Django activates timezones per-thread and workers are reused, so
                # leaving one active would leak this site's zone into the next
                # request on the same thread.
                timezone.deactivate()


class SetupRedirectMiddleware:
    """Sends a browser to the setup wizard while the install is genuinely virgin.

    The condition is deliberately narrow: **no user account exists at all**. That is
    the only state where the app truly cannot be used — there is nothing to log in
    with — and it is exactly what a fresh clone looks like.

    Everything else is a nudge rather than a redirect. Once an account exists, the
    wizard stays reachable from Settings and a banner points at it while setup is
    outstanding, but nothing is blocked. Keying a hard redirect on "setup not
    finished" instead would mean a user who closed the tab halfway through the
    printer step could reach no page in the app at all — and worse, an install whose
    SiteSettings row was missing for any reason would be walled off from a database
    full of perfectly good parts.
    """

    EXEMPT_PREFIXES = (
        "/setup/",
        "/static/",
        "/media/",
        # Machine-to-machine endpoints. Home Assistant calls /api/locate/ directly
        # with a shared secret and no browser session; a human onboarding redirect is
        # meaningless there, and redirecting would break voice search on every fresh
        # install rather than fixing anything.
        "/api/",
        "/admin/login/",
        "/admin/logout/",
        "/admin/jsi18n/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_exempt(request.path) or not self._is_virgin_install():
            return self.get_response(request)
        try:
            target = reverse("inventory:setup")
        except NoReverseMatch:  # pragma: no cover - the URL always exists in practice
            target = "/setup/"
        return redirect(target)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        return path.startswith(SetupRedirectMiddleware.EXEMPT_PREFIXES)

    @staticmethod
    def _is_virgin_install() -> bool:
        """True only when there is no account to log in with.

        Fails closed (returns False, i.e. no redirect) if the auth table isn't
        readable yet — during a fresh clone's first migrate, for instance. Being
        wrong in that direction means the app shows a login page, which is a far
        better failure than an unreachable site.
        """
        try:
            from django.contrib.auth import get_user_model

            return not get_user_model().objects.exists()
        except Exception:
            return False
