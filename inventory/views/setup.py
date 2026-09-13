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

from .. import archiving, geocoding, hardware_config, label_printing, updates, wizard
from ..label_drivers import DRIVERS, driver_keys, get_driver
from ..models import CommunityProfile, Drawer, DrawerLedSegment, LedStrip, ReferenceDoc, SiteSettings
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

    if request.method == "POST" and request.POST.get("action") == "check_updates":
        info = updates.check_for_update()
        (messages.success if info.ok else messages.error)(request, updates.describe(info))
        return redirect("inventory:setup_hub")

    site = _site()
    return render(
        request,
        "inventory/setup/hub.html",
        _shell(
            request,
            None,
            outstanding=wizard.required_outstanding(),
            setup_complete=site.setup_complete,
            # Read from the cache only — see updates.cached_info. The page never makes
            # an outbound request just because someone opened it.
            update_info=updates.cached_info(),
            update_check_enabled=updates.enabled(),
        ),
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
        elif action == "save_channels":
            _save_strip_channels(request)
        elif action == "push_strips":
            ok, detail = _push_strip_map()
            (messages.success if ok else messages.error)(request, detail)
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
            strips=_strip_rows(),
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


def _strip_rows():
    """Every strip the app knows about, with its channel if it has one recorded.

    Two sources on purpose. A strip only exists in `LedStrip` once somebody has said
    which channel it is wired to, but the name first appears in a drawer's LED
    mappings — so the union is what the owner actually needs to see: every strip the
    app expects to exist, and which of them are still unaccounted for.
    """
    recorded = {strip.name: strip for strip in LedStrip.objects.all()}
    named = set(DrawerLedSegment.objects.values_list("led_strip", flat=True).distinct())
    rows = []
    for name in sorted(named | set(recorded)):
        strip = recorded.get(name)
        rows.append({"name": name, "channel": strip.channel if strip else None, "recorded": strip is not None})
    return rows


def _save_strip_channels(request):
    """Record the channel each strip is plugged into.

    Blank clears the channel rather than saving a zero, because channel 0 is a real
    output and "I haven't wired this one yet" is a different thing from "this is on
    channel 0". Getting those confused would light up the wrong strip.
    """
    saved = cleared = 0
    for name in request.POST.getlist("strip_name"):
        raw = (request.POST.get(f"channel_{name}") or "").strip()
        if not raw:
            LedStrip.objects.filter(name=name).delete()
            cleared += 1
            continue
        if not raw.isdigit() or not (0 <= int(raw) <= 7):
            messages.error(request, f"Channel for “{name}” must be a number from 0 to 7.")
            continue
        LedStrip.objects.update_or_create(name=name, defaults={"channel": int(raw)})
        saved += 1
    if saved or cleared:
        messages.success(request, f"Recorded {saved} strip channel{'s' if saved != 1 else ''}.")


def _push_strip_map() -> tuple[bool, str]:
    """Send the recorded channels to the Pi, which is where they have to live.

    The app cannot apply this itself: /locate runs on the Pi and reads strip_map.json
    there. So the wizard writes the file by asking the controller to.
    """
    import requests

    url = hardware_config.led_url()
    if not url:
        return False, "No LED controller address set yet."

    # Only strips that are actually wired. Sending a strip with no channel would push a
    # null, which the Pi rejects -- correctly, since it has no way to light nothing.
    mapping = {
        strip.name: strip.channel
        for strip in LedStrip.objects.filter(channel__isnull=False)
    }
    if not mapping:
        return False, "No strip channels recorded yet — fill them in below first."

    key = hardware_config.led_key()
    headers = {"X-Api-Key": key} if key else {}
    try:
        response = requests.post(f"{url}/strips", json={"strips": mapping}, headers=headers, timeout=10)
    except requests.RequestException as exc:
        return False, f"Couldn't reach {url}: {exc}"

    if response.status_code == 404:
        return False, (
            "The controller answered 404. It's running an older version that has no /strips "
            "endpoint — update the code in led-controller/pi/ on the Pi and restart it."
        )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error")
        except ValueError:
            detail = None
        return False, detail or f"The controller refused it (HTTP {response.status_code})."

    return True, f"Sent {len(mapping)} strip channel{'s' if len(mapping) != 1 else ''} to the Pi."


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


def _clean_driver(value) -> str:
    """The submitted printer type, or ZPL.

    Validated against the driver registry rather than a second hard-coded list, so
    adding a driver means adding it in one place. Nonsense falls back to ZPL for the
    same reason the registry does: it is the one that has been tested, and the
    alternative is storing a key nothing can print with.
    """
    return value if value in DRIVERS else "zpl"


def _clean_dpi(value) -> tuple[str, str]:
    """(dots per inch, error). Blank means "use the printer's own resolution".

    Rejected loudly rather than stored and then ignored. A settings box that appears to
    save a number the renderer will silently discard is worse than one that refuses it,
    because the owner cannot tell which of the two happened.
    """
    raw = (value or "").strip()
    if not raw:
        return "", ""
    if not raw.isdigit() or not (50 <= int(raw) <= 2400):
        return "", (
            "Dots per inch has to be a whole number between 50 and 2400 — or leave it "
            "blank to use the resolution that goes with the printer type."
        )
    return raw, ""


def _stock_rows() -> list[dict]:
    """Each label size at the resolution actually in use, and whether it fits.

    The width is what decides it: a print head is a fixed width, so a 4" label simply
    does not fit a Dymo's 448 dots and would be clipped without saying so. Showing the
    number and the verdict here means nobody finds out by printing a damaged label.
    """
    dpi = label_printing.configured_dpi()
    driver = get_driver(hardware_config.printer_driver())
    rows = []
    for key, spec in label_printing.LABEL_SIZES.items():
        width_px = round(spec["width_in"] * dpi)
        height_px = round(spec["height_in"] * dpi)
        rows.append(
            {
                "key": key,
                "display": spec["display"],
                "width_px": width_px,
                "height_px": height_px,
                "fits": not driver.max_width_dots or width_px <= driver.max_width_dots,
            }
        )
    return rows


@login_required
def setup_printer(request):
    site = _site()
    if request.method == "POST":
        action = request.POST.get("action")
        site.label_printer_url = _clean_url(request.POST.get("label_printer_url"))
        site.label_printer_key = (request.POST.get("label_printer_key") or "").strip()
        site.label_driver = _clean_driver(request.POST.get("label_driver"))
        dpi, dpi_error = _clean_dpi(request.POST.get("label_dpi"))
        if dpi_error:
            messages.error(request, dpi_error)
        else:
            site.label_dpi = dpi
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
            drivers=[DRIVERS[key] for key in driver_keys()],
            driver=get_driver(hardware_config.printer_driver()),
            effective_dpi=label_printing.configured_dpi(),
            stock=_stock_rows(),
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
