"""Device-pairing auth for the workshop Pi's kiosk display."""
import secrets
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.shortcuts import redirect



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
