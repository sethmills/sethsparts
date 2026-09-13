"""The setup wizard's pages.

Why these exist, and why they double as the settings pages, is explained in
`inventory/wizard.py`. The short version: a fresh install has no account to log in
with, and "change my workshop's name" should not require /admin/.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo, available_timezones

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from .. import archiving, geocoding, hardware_config, wizard
from ..models import CommunityProfile, Drawer, DrawerLedSegment, ReferenceDoc, SiteSettings
from ..site_config import get_site_settings


def _site() -> SiteSettings:
    return SiteSettings.load()


def _clean_url(value: str) -> str:
    """Add a scheme if someone typed a bare host, which is what everybody does.

    "192.168.1.50:8080" is how a person writes an address on their own network.
    Refusing it and demanding "http://" would be pedantic about something the app can
    trivially fix, and the field would then look broken.
    """
    url = (value or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "http://" + url
    return url


def _shell(request, current, **extra):
    context = {
        "current": current,
        # None for the overview page, which is not itself a step.
        "next_step": wizard.next_step_after(current.key) if current else None,
        "steps": wizard.visible_steps(),
        "site": _site(),
    }
    context.update(extra)
    return context


def _require_login_if_set_up(request):
    """Both wizard entry points use this.

    On a brand-new install the only person who could be here is the owner setting it
    up, and there is no account to authenticate against yet. Once an account exists,
    everything behind the wizard needs a login like any other page.
    """
    if wizard.account_exists() and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    return None


# --- Overview ----------------------------------------------------------------


def setup_hub(request):
    auth = _require_login_if_set_up(request)
    if auth:
        return auth
    if not wizard.account_exists():
        return redirect("inventory:setup_account")

    site = _site()
    return render(
        request,
        "inventory/setup/hub.html",
        _shell(request, None, outstanding=wizard.required_outstanding(), setup_complete=site.setup_complete),
    )


# --- Step 1: the first account ----------------------------------------------


def setup_account(request):
    """Create the first account. Unauthenticated, and only once.

    On a brand-new install there is nobody to log in as, so the first account has to
    be creatable without a session — the same problem WordPress and Nextcloud have,
    solved the same way. It closes as soon as an account exists: after that this URL
    raises 404 rather than offering a second unauthenticated account to anyone who
    finds it.
    """
    if wizard.account_exists():
        raise Http404("This install already has an account.")

    errors = {}
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        if not username:
            errors["username"] = "Pick a username."
        if not password1:
            errors["password1"] = "Choose a password."
        elif password1 != password2:
            errors["password2"] = "Those two passwords don't match."
        else:
            # The same validators the admin uses, so the wizard cannot set a weaker
            # password than any other route into the app.
            try:
                validate_password(password1, user=None)
            except ValidationError as exc:
                errors["password1"] = " ".join(exc.messages)

        if not errors:
            user = get_user_model().objects.create_superuser(username=username, password=password1)
            # Log them straight in. Making someone set up a password and then
            # immediately type it again on a login page is a pointless hurdle.
            login(request, user)
            messages.success(request, f"Welcome, {user.username}. Let's get this set up.")
            return redirect("inventory:setup_site")

    return render(request, "inventory/setup/account.html", _shell(request, wizard.ACCOUNT, errors=errors))


# --- Step 2: name, timezone, country, units ---------------------------------


@login_required
def setup_site(request):
    site = _site()
    if request.method == "POST":
        name = (request.POST.get("site_name") or "").strip()
        zone = (request.POST.get("timezone") or "").strip()
        country = (request.POST.get("country") or "").strip().upper()[:2]
        unit_system = request.POST.get("unit_system") or "metric"

        if not name:
            messages.error(request, "Give your workshop a name — it goes in the header of every page.")
        elif zone not in available_timezones():
            messages.error(request, f"“{zone}” isn't a timezone I recognise. Pick one from the list.")
        else:
            site.site_name = name
            site.timezone = zone
            site.country = country
            site.unit_system = unit_system if unit_system in ("metric", "imperial") else "metric"
            site.save()
            messages.success(request, "Saved.")
            return redirect(wizard.next_step_after(wizard.SITE.key).url_name)

    return render(
        request,
        "inventory/setup/site.html",
        _shell(request, wizard.SITE, timezones=sorted(available_timezones())),
    )


# --- Step 3: lights ---------------------------------------------------------


@login_required
def setup_lights(request):
    site = _site()
    if request.method == "POST":
        action = request.POST.get("action")
        site.led_controller_url = _clean_url(request.POST.get("led_controller_url"))
        site.led_controller_key = (request.POST.get("led_controller_key") or "").strip()
        site.save()

        if action == "test":
            ok, detail = _test_led_controller()
            (messages.success if ok else messages.error)(request, detail)
        elif action == "add_mapping":
            _add_led_mapping(request)
        elif action == "clear_mappings":
            count = DrawerLedSegment.objects.count()
            DrawerLedSegment.objects.all().delete()
            messages.success(request, f"Cleared {count} LED mapping{'s' if count != 1 else ''}.")
        elif action == "delete_mapping":
            DrawerLedSegment.objects.filter(pk=request.POST.get("mapping")).delete()
            messages.success(request, "Mapping removed.")
        else:
            messages.success(request, "Saved.")

        if action in ("save",):
            return redirect(wizard.next_step_after(wizard.LIGHTS.key).url_name)
        return redirect("inventory:setup_lights")

    return render(
        request,
        "inventory/setup/lights.html",
        _shell(
            request,
            wizard.LIGHTS,
            configured=hardware_config.has_leds(),
            source=hardware_config.led_source(),
            mappings=DrawerLedSegment.objects.select_related("drawer__container").order_by("led_strip", "led_start_index"),
            drawers=Drawer.objects.select_related("container").order_by("container__number", "label"),
        ),
    )


def _add_led_mapping(request):
    drawer_id = request.POST.get("drawer")
    strip = (request.POST.get("led_strip") or "").strip()
    start = (request.POST.get("led_start_index") or "").strip()
    count = (request.POST.get("led_count") or "1").strip()

    if not (drawer_id and strip and start.isdigit() and count.isdigit()):
        messages.error(request, "A mapping needs a drawer, a strip name, a start LED and a count.")
        return
    drawer = Drawer.objects.filter(pk=drawer_id).first()
    if drawer is None:
        messages.error(request, "That drawer doesn't exist.")
        return
    DrawerLedSegment.objects.create(
        drawer=drawer, led_strip=strip, led_start_index=int(start), led_count=max(1, int(count))
    )
    messages.success(request, f"Mapped {drawer} to {strip} from LED {start}.")


def _test_led_controller() -> tuple[bool, str]:
    """Ask the controller for its health. The only way to know it is reachable."""
    import requests

    url = hardware_config.led_url()
    if not url:
        return False, "No LED controller address set yet."
    key = hardware_config.led_key()
    headers = {"X-Api-Key": key} if key else {}
    try:
        response = requests.get(f"{url}/health", headers=headers, timeout=8)
    except requests.RequestException as exc:
        return False, f"Couldn't reach {url}: {exc}"
    if response.status_code >= 400:
        return False, f"{url} answered HTTP {response.status_code}."
    try:
        strips = response.json().get("strips_configured") or []
    except ValueError:
        return True, f"{url} answered, but not with the JSON the controller should send."
    if strips:
        return True, f"Controller is up. Strips it knows about: {', '.join(strips)}."
    return True, "Controller is up, but it has no strips configured yet — add them on the Pi."


# --- Step 4: printer --------------------------------------------------------


@login_required
def setup_printer(request):
    site = _site()
    if request.method == "POST":
        action = request.POST.get("action")
        site.label_printer_url = _clean_url(request.POST.get("label_printer_url"))
        site.label_printer_key = (request.POST.get("label_printer_key") or "").strip()
        driver = request.POST.get("label_driver") or "zpl"
        site.label_driver = driver if driver in ("zpl", "brother_ql", "dymo", "cups") else "zpl"
        site.save()

        if action == "test":
            ok, detail = _test_printer()
            (messages.success if ok else messages.error)(request, detail)
        else:
            messages.success(request, "Saved.")
            return redirect(wizard.next_step_after(wizard.PRINTER.key).url_name)
        return redirect("inventory:setup_printer")

    return render(
        request,
        "inventory/setup/printer.html",
        _shell(
            request,
            wizard.PRINTER,
            configured=hardware_config.has_printer(),
            source=hardware_config.printer_source(),
        ),
    )


def _test_printer() -> tuple[bool, str]:
    """Print one small label. A printer that answers a health check but prints nothing
    is the common failure, so this actually sends a label."""
    from ..label_printing import print_label

    if not hardware_config.has_printer():
        return False, "No label printer address set yet."
    ok, error = print_label("Setup test", "barcode")
    if ok:
        return True, "Sent a test label — check the printer."
    return False, f"Couldn't print: {error}"


# --- Step 5: reference library ----------------------------------------------


@login_required
def setup_reference(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "load":
            from django.core.management import call_command

            call_command("load_starter_reference", verbosity=0)
            messages.success(request, "Starter library loaded. Edit or delete anything you don't want.")
        elif action == "archive":
            archived, failed = _archive_a_few()
            messages.success(request, f"Archived {archived} document(s){f', {failed} failed' if failed else ''}.")
        return redirect("inventory:setup_reference")

    return render(
        request,
        "inventory/setup/reference.html",
        _shell(
            request,
            wizard.REFERENCE,
            already_loaded=bool(get_site_settings() and get_site_settings().starter_reference_loaded_at),
            doc_count=ReferenceDoc.objects.count(),
            missing=ReferenceDoc.objects.filter(external_url__gt="", file="").count(),
        ),
    )


def _archive_a_few(limit: int = 5) -> tuple[int, int]:
    """Archive a handful, not all of them.

    A setup page must not sit there fetching twenty-seven documents; the bulk command
    exists for that. This is enough to show the mechanism working, and the button can
    be pressed again.
    """
    archived = failed = 0
    pending = ReferenceDoc.objects.filter(external_url__gt="", file="")[:limit]
    for doc in pending:
        result = archiving.archive_reference_doc(doc)
        if result.ok:
            archived += 1
        else:
            failed += 1
    return archived, failed


# --- Step 6: community ------------------------------------------------------


@login_required
def setup_community(request):
    """Whether this workshop appears on other people's maps.

    Two models, on purpose. `CommunityProfile` holds the *public* facts — a rough
    location and an opt-in flag — while `SiteSettings` holds facts about the install,
    including which country it's in. Keeping the opt-in on its own model is what makes
    "turn the map off" a single reversible flag rather than something tangled up with
    the site's own name and timezone.
    """
    site = _site()
    profile = CommunityProfile.load()

    if request.method == "POST":
        action = request.POST.get("action")
        # The country is shared with the rest of the app and is what decides whether
        # postcodes or ZIP codes get expected, so it is saved whichever button was hit.
        site.country = (request.POST.get("country") or site.country or "").strip().upper()[:2]
        site.save()

        if action == "lookup":
            where = (request.POST.get("where") or "").strip()
            result = geocoding.lookup(where, site.country)
            if result.ok:
                profile.location_lat = result.lat
                profile.location_lon = result.lon
                profile.location_source = (
                    result.source if result.source in ("outcode", "zip", "nominatim") else "manual"
                )
                profile.save()
                messages.success(
                    request,
                    f"Found “{result.label}”. That's district level — a full postcode is "
                    "deliberately reduced to its district before anything is stored.",
                )
            else:
                # Deliberately does not clear an existing point: a typo should not
                # wipe a location that was working.
                messages.error(request, result.error)
        elif action == "save":
            profile.discoverable = bool(request.POST.get("discoverable"))
            profile.display_name = (request.POST.get("display_name") or "").strip()[:100]
            profile.save()
            messages.success(request, "Saved.")
            return redirect(wizard.next_step_after(wizard.COMMUNITY.key).url_name)

        return redirect("inventory:setup_community")

    return render(
        request,
        "inventory/setup/community.html",
        _shell(request, wizard.COMMUNITY, profile=profile, has_location=profile.has_location),
    )


# --- Step 7: reaching it from outside ---------------------------------------


@login_required
def setup_access(request):
    site = _site()
    if request.method == "POST":
        action = request.POST.get("action")
        site.public_url = _clean_url(request.POST.get("public_url"))
        site.save()

        if action == "check":
            ok, detail = _check_reachable(site.public_url)
            (messages.success if ok else messages.error)(request, detail)
            return redirect("inventory:setup_access")

        messages.success(request, "Saved.")
        return redirect("inventory:setup_finish")

    return render(
        request,
        "inventory/setup/access.html",
        _shell(
            request,
            wizard.ACCESS,
            # What the app thinks it is being reached at right now. Usually right
            # behind a tunnel, and useful to compare against what they pasted.
            current_host=request.get_host(),
            secure=request.is_secure(),
        ),
    )


def _check_reachable(url: str) -> tuple[bool, str]:
    """Fetch the owner's own public address, from here.

    Checks what a browser elsewhere would actually get rather than what the settings
    claim — which is the only useful definition of "reachable". This app makes an
    outbound request to a URL the owner typed, so it is bounded and reports plainly
    when it cannot get there.
    """
    import requests

    from urllib.parse import urlparse

    url = (url or "").strip().rstrip("/")
    if not url:
        return False, "Paste the address you reach this app at first."

    parsed = urlparse(url)
    # Checking the *host* rather than the prefix. `_clean_url` adds "http://" to
    # anything, so "not a url" arrives here looking like a plausible address; without
    # this check the app would happily try to fetch it.
    if not parsed.netloc or " " in parsed.netloc:
        return False, f"“{url}” doesn't look like a web address."

    try:
        response = requests.get(url, timeout=10, allow_redirects=True)
    except requests.RequestException as exc:
        return False, f"Couldn't reach {url}: {exc}"

    if response.status_code >= 500:
        return False, f"{url} answered HTTP {response.status_code} — something is wrong at the far end."
    # A redirect to the login page is the expected, healthy answer: the app is up and
    # asking who you are.
    if response.status_code in (200, 301, 302, 303, 307, 308):
        return True, f"{url} answered HTTP {response.status_code}. It's reachable from here."
    return False, f"{url} answered HTTP {response.status_code}."


# --- Finish -----------------------------------------------------------------


@login_required
def setup_finish(request):
    site = _site()
    if request.method == "POST":
        site.setup_completed_at = timezone.now()
        site.save()
        messages.success(request, "You're set up. Everything here stays editable under Settings.")
        return redirect("inventory:browse")

    outstanding = wizard.required_outstanding()
    return render(request, "inventory/setup/finish.html", _shell(request, wizard.FINISH, outstanding=outstanding))
