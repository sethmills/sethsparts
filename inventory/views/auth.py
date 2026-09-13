"""Signing in and out, and device-pairing for the workshop Pi's kiosk display.

The app used to have no login page of its own: `LOGIN_URL` pointed at Django's
admin login, which was fine for one person who knows what the admin is, and wrong
for a project anyone can clone. A stranger landing on someone else's installation
was greeted by a Django admin page, and `/login/` -- the address a person actually
tries -- was a 404.

The views here fix that. The authentication underneath is untouched: these are
Django's own LoginView/LogoutView, so the credentials check, the session handling
and the `next`-URL safety are the same code as before. What changed is only that
the login belongs to this app and lives at a guessable address. The admin keeps its
own login at `/admin/login/` for the admin itself.
"""
import secrets
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect

from .. import site_config


class AppLoginView(LoginView):
    """The app's own login page, rendered in the app's own styling.

    `redirect_authenticated_user` is here for a real case rather than neatness: a
    device with a live session that follows a stale `/login/` link -- the Pi kiosk
    after a reboot is the likely one -- should land in the app, not be asked to sign
    in again with credentials nobody is there to type.
    """

    template_name = "inventory/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Django's LoginView puts `site_name` in the context itself, from
        # `get_current_site()`. Without `django.contrib.sites` that is a RequestSite,
        # whose `.name` is the bare host -- so the page would say "sethsparts.com"
        # where the owner's own name belongs, and it lands on top of the context
        # processor that provides the real one. Put the name the owner chose back.
        context["site_name"] = site_config.site_name()
        return context


class AppLogoutView(LogoutView):
    """Sign out and go back to the login page.

    POST-only, which is Django's own rule and worth keeping: a GET logout can be
    fired by any image tag or link prefetch on any page, which is a silly way to
    lose a session. So the navigation posts a small form instead of linking.
    """


def kiosk_autologin(request):
    """Lets the Pi kiosk's own launch script establish a real, properly-issued session
    on every boot — device-pairing via a long-lived secret token, never Seth's actual
    account password. Not @login_required (that's the whole point); the token itself
    is the credential, transmitted only over HTTPS and known only to this server's
    .env and the kiosk launch script on the Pi."""
    token = request.GET.get("token", "")
    if not settings.KIOSK_AUTOLOGIN_TOKEN or not secrets.compare_digest(token, settings.KIOSK_AUTOLOGIN_TOKEN):
        return redirect("inventory:browse")  # wrong/missing token -> just land on the normal (login-walled) site

    user = get_user_model().objects.filter(username=settings.KIOSK_AUTOLOGIN_USERNAME).first()
    if user:
        login(request, user)
    return redirect(request.GET.get("next") or "inventory:browse")
