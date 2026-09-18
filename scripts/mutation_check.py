"""Mutation check: deliberately break real logic, confirm the suite notices.

A test suite that passes is worthless on its own -- what matters is whether it
FAILS when the behaviour it claims to protect is broken. Each mutation below
inverts a real decision the app makes. Anything that stays green is a blind spot.

The view logic was split out of a single views.py into inventory/views/<topic>.py,
so the anchors below point at the module that now owns each behaviour. If a
mutation reports "anchor not found", the logic has moved and this list needs
updating -- which is itself useful signal that a refactor happened.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "inventory" / "views"
MODELS = ROOT / "inventory" / "models.py"
COMMUNITY = ROOT / "inventory" / "community.py"
PY = str(ROOT / "venv" / "bin" / "python")

MUTATIONS = [
    (
        "LED row/column split reversed (row->right, col->left)",
        PKG / "lights.py",
        'if row and segment.led_strip.endswith("-left"):',
        'if row and segment.led_strip.endswith("-right"):',
        "inventory.tests.test_led",
    ),
    (
        "FIFO stock consumption reversed to LIFO",
        PKG / "_shared.py",
        '.filter(part=part, quantity__gt=0).order_by("id")',
        '.filter(part=part, quantity__gt=0).order_by("-id")',
        "inventory.tests.test_stock_and_builds",
    ),
    (
        "Bin row/column arithmetic swapped",
        MODELS,
        "return ((self.bin_number - 1) // 4) + 1",
        "return ((self.bin_number - 1) % 4) + 1",
        "inventory.tests.test_models",
    ),
    (
        "Bins per drawer cut from 16 to 8",
        PKG / "bins.py",
        "BINS_PER_DRAWER = 16",
        "BINS_PER_DRAWER = 8",
        "inventory.tests.test_bins",
    ),
    (
        "Empty kiosk token now matches any supplied token",
        PKG / "auth.py",
        "if not settings.KIOSK_AUTOLOGIN_TOKEN or not secrets.compare_digest(token, settings.KIOSK_AUTOLOGIN_TOKEN):",
        "if not secrets.compare_digest(token, settings.KIOSK_AUTOLOGIN_TOKEN):",
        "inventory.tests.test_kiosk_auth",
    ),
    (
        "Voice API accepts a missing key when none is configured",
        PKG / "searching.py",
        "if not settings.VOICE_SEARCH_API_KEY or provided_key != settings.VOICE_SEARCH_API_KEY:",
        "if provided_key != settings.VOICE_SEARCH_API_KEY:",
        "inventory.tests.test_voice_api",
    ),
    (
        "Bin scan conflict check removed (silent overwrite)",
        PKG / "bins.py",
        'conflict = Bin.objects.filter(barcode_id=code).exclude(pk=b.pk).select_related("drawer").first()',
        "conflict = None",
        "inventory.tests.test_bins",
    ),
    (
        "Search synonym expansion disabled",
        ROOT / "inventory" / "search.py",
        "    for key, synonyms in KEYWORD_SYNONYMS.items():",
        "    for key, synonyms in []:",
        "inventory.tests.test_search",
    ),
    (
        "ZPL row stride off by one byte",
        ROOT / "inventory" / "label_drivers.py",
        "bytes_per_row = (width_px + 7) // 8",
        "bytes_per_row = (width_px + 8) // 8",
        "inventory.tests.test_labels",
    ),
    (
        "Intake blank-line filtering removed",
        PKG / "intake.py",
        "lines = [line for line in lines if line]",
        "lines = lines",
        "inventory.tests.test_intake",
    ),
    # --- community sharing: the privacy defaults -----------------------------
    # These three are the promises the feature makes. If any of them flips, an
    # install shares something its owner never agreed to, so each one must have a
    # test that fails loudly.
    (
        "Peers can search inventory by default (sharing without consent)",
        MODELS,
        "    shares_parts = models.BooleanField(\n        default=False,",
        "    shares_parts = models.BooleanField(\n        default=True,",
        "inventory.tests.test_community_models",
    ),
    (
        "Categories are shareable by default (everything exposed)",
        MODELS,
        '    is_shareable = models.BooleanField(\n        default=False,',
        '    is_shareable = models.BooleanField(\n        default=True,',
        "inventory.tests.test_community_models",
    ),
    (
        "Instances are discoverable by default (on the map without asking)",
        MODELS,
        "    discoverable = models.BooleanField(\n        default=False,",
        "    discoverable = models.BooleanField(\n        default=True,",
        "inventory.tests.test_community_models",
    ),
    (
        "can_publish drops the location requirement",
        MODELS,
        "return self.discoverable and self.has_location",
        "return self.discoverable",
        "inventory.tests.test_community_models",
    ),
    (
        "A pending peer is treated as active (unconfirmed keys honoured)",
        MODELS,
        "return self.status == self.ACTIVE",
        "return True",
        "inventory.tests.test_community_models",
    ),
    (
        "Pairing codes never expire",
        MODELS,
        "return self.claimed_at is None and now < self.expires_at",
        "return self.claimed_at is None",
        "inventory.tests.test_community_models",
    ),
    (
        "Pairing codes can be claimed more than once",
        MODELS,
        "return self.claimed_at is None and now < self.expires_at",
        "return now < self.expires_at",
        "inventory.tests.test_community_models",
    ),
    (
        "Pairing code lookalike folding removed (typed codes stop matching)",
        MODELS,
        'return cleaned.replace("O", "0").replace("I", "1").replace("L", "1")',
        "return cleaned",
        "inventory.tests.test_community_models",
    ),
    # --- community sharing: pin signing --------------------------------------
    (
        "Pin version guard removed (unknown formats interpreted)",
        COMMUNITY,
        "    if version not in SUPPORTED_PIN_VERSIONS:\n        return False",
        "    if False:\n        return False",
        "inventory.tests.test_community_crypto",
    ),
    (
        "Pin version not covered by the signature (relabelable in transit)",
        COMMUNITY,
        '        "v": v,',
        '        "v": 0,',
        "inventory.tests.test_community_crypto",
    ),
    (
        "Pin name not covered by the signature (renameable in transit)",
        COMMUNITY,
        '        "name": name or "",',
        '        "name": "",',
        "inventory.tests.test_community_crypto",
    ),
    (
        "Coordinate precision reduced (signed bytes become platform-dependent)",
        COMMUNITY,
        "COORD_DECIMALS = 6",
        "COORD_DECIMALS = 4",
        "inventory.tests.test_community_crypto",
    ),
    (
        "Public key no longer derived from the private key",
        COMMUNITY,
        "Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex)).public_key().public_bytes_raw().hex()",
        "        private_hex",
        "inventory.tests.test_community_crypto",
    ),
    (
        "Signature verification always succeeds (forged pins accepted)",
        COMMUNITY,
        "    except (InvalidSignature, ValueError, TypeError):\n        return False",
        "    except (InvalidSignature, ValueError, TypeError):\n        return True",
        "inventory.tests.test_community_crypto",
    ),
    # --- portability: the guard has to catch the thing it guards -------------
    (
        "Windows font dropped from the label chain",
        ROOT / "inventory" / "label_printing.py",
        '        "C:/Windows/Fonts/arial.ttf",  # Windows',
        "        # Windows font removed",
        "inventory.tests.test_portability",
    ),
    (
        "Font fallback ignores the requested size (tiny labels)",
        ROOT / "inventory" / "label_printing.py",
        "    return ImageFont.load_default(size=size_px)",
        "    return ImageFont.load_default()",
        "inventory.tests.test_portability",
    ),
    (
        "Explicit UTF-8 dropped from a file write (breaks on Windows)",
        ROOT / "inventory" / "management" / "commands" / "classify_enrichment_queue.py",
        'with open(output_path, "w", encoding="utf-8") as f:',
        'with open(output_path, "w") as f:',
        "inventory.tests.test_portability",
    ),
    (
        "Explicit UTF-8 dropped from an ingest command (breaks on Windows)",
        ROOT / "inventory" / "management" / "commands" / "ingest_enrichment.py",
        'with open(path, encoding="utf-8") as f:',
        "with open(path) as f:",
        "inventory.tests.test_portability",
    ),
    # --- site settings, branding and the setup gate --------------------------
    (
        "Unit inheritance ignored (existing plain counts start claiming metres)",
        MODELS,
        '        return self.unit or (self.part.default_unit if self.part_id else "") or DEFAULT_UNIT',
        '        return self.unit or "m"',
        "inventory.tests.test_units",
    ),
    (
        "Setup gate widened to every install (walls off a working workshop)",
        ROOT / "inventory" / "middleware.py",
        "            return not get_user_model().objects.exists()",
        "            return True",
        "inventory.tests.test_site_settings",
    ),
    (
        "Machine endpoints no longer exempt (voice search breaks on a fresh install)",
        ROOT / "inventory" / "middleware.py",
        '        "/api/",',
        '        # "/api/",',
        "inventory.tests.test_site_settings",
    ),
    (
        "Site name ignores the configured value (every clone shows the default)",
        ROOT / "inventory" / "site_config.py",
        "    return (obj.site_name if obj and obj.site_name else DEFAULT_SITE_NAME)",
        "    return DEFAULT_SITE_NAME",
        "inventory.tests.test_site_settings",
    ),
    (
        "Timezone middleware stops activating the owner's zone",
        ROOT / "inventory" / "middleware.py",
        "                timezone.activate(zone)",
        "                pass",
        "inventory.tests.test_site_settings",
    ),
    # --- the reference library and archiving ---------------------------------
    (
        "Deleting a category cascades instead of refusing (shreds documents)",
        MODELS,
        "        on_delete=models.PROTECT,\n        related_name=\"docs\",",
        "        on_delete=models.CASCADE,\n        related_name=\"docs\",",
        "inventory.tests.test_reference",
    ),
    (
        "Retry redirect accepts any URL (open redirect)",
        ROOT / "inventory" / "views" / "reference.py",
        '    if candidate.startswith("/") and not candidate.startswith("//"):\n        return candidate\n    return ""',
        '    return candidate or ""',
        "inventory.tests.test_reference",
    ),
    (
        "Starter loader resurrects deleted documents",
        ROOT / "inventory" / "management" / "commands" / "load_starter_reference.py",
        "        if site.starter_reference_loaded_at and not options['force']:",
        "        if False:",
        "inventory.tests.test_reference",
    ),
    (
        "Archive size cap removed (one URL can fill the disk)",
        ROOT / "inventory" / "archiving.py",
        "            if total > max_bytes:",
        "            if False:",
        "inventory.tests.test_archiving",
    ),
    (
        "Archive scheme allowlist removed (file:// and friends accepted)",
        ROOT / "inventory" / "archiving.py",
        "    if parsed.scheme not in ALLOWED_SCHEMES:",
        "    if False:",
        "inventory.tests.test_archiving",
    ),
    # --- the setup wizard ----------------------------------------------------
    (
        "Account step reopens after setup (anyone can create an admin)",
        ROOT / "inventory" / "views" / "setup.py",
        '    if wizard.account_exists():\n        raise Http404("This install already has an account.")',
        '    if False:\n        raise Http404("This install already has an account.")',
        "inventory.tests.test_setup_wizard",
    ),
    (
        "Account step skips password validation (weak admin password)",
        ROOT / "inventory" / "views" / "setup.py",
        "                validate_password(password1, user=None)",
        "                pass",
        "inventory.tests.test_setup_wizard",
    ),
    (
        "Reachability check accepts anything with a scheme (fetches junk)",
        ROOT / "inventory" / "views" / "setup.py",
        '    if not parsed.netloc or " " in parsed.netloc:',
        "    if False:",
        "inventory.tests.test_setup_wizard",
    ),
    (
        "LED mapping count not clamped (a mapping that lights nothing)",
        ROOT / "inventory" / "views" / "setup.py",
        "        drawer=drawer, led_strip=strip, led_start_index=int(start), led_count=max(1, int(count))",
        "        drawer=drawer, led_strip=strip, led_start_index=int(start), led_count=int(count)",
        "inventory.tests.test_setup_wizard",
    ),
    # --- pushing LED config to the Pi ----------------------------------------
    (
        "A blank channel box saves 0 (lights a strip that isn't wired yet)",
        ROOT / "inventory" / "views" / "setup.py",
        "        if not raw:\n            LedStrip.objects.filter(name=name).delete()",
        "        if raw is None:\n            LedStrip.objects.filter(name=name).delete()",
        "inventory.tests.test_led_push",
    ),
    (
        "Channel range not checked when saving (channel 40 accepted)",
        ROOT / "inventory" / "views" / "setup.py",
        "        if not raw.isdigit() or not (0 <= int(raw) <= 7):",
        "        if False:",
        "inventory.tests.test_led_push",
    ),
    (
        "Strips with no channel pushed as null (whole push fails on an unwired strip)",
        ROOT / "inventory" / "views" / "setup.py",
        "        for strip in LedStrip.objects.filter(channel__isnull=False)",
        "        for strip in LedStrip.objects.all()",
        "inventory.tests.test_led_push",
    ),
    (
        "A 404 from the Pi not explained (owner never learns to update the Pi)",
        ROOT / "inventory" / "views" / "setup.py",
        "    if response.status_code == 404:",
        "    if False:",
        "inventory.tests.test_led_push",
    ),
    (
        "Pi accepts a channel outside the Scorpio's range",
        ROOT / "led-controller" / "pi" / "server.py",
        "        if not (0 <= channel <= MAX_CHANNEL):",
        "        if False:",
        "inventory.tests.test_led_push",
    ),
    (
        "Pi accepts a boolean channel (True sails through as channel 1)",
        ROOT / "led-controller" / "pi" / "server.py",
        "        if isinstance(channel, bool) or not isinstance(channel, int):",
        "        if not isinstance(channel, int):",
        "inventory.tests.test_led_push",
    ),
    # --- community pairing ---------------------------------------------------
    (
        "Pairing code never spent (one invite, unlimited workshops)",
        ROOT / "inventory" / "community_api.py",
        '        pairing.claimed_at = timezone.now()\n        pairing.claimed_by = peer\n        pairing.save(update_fields=["claimed_at", "claimed_by"])',
        "        pass",
        "inventory.tests.test_community_pairing",
    ),
    (
        "Pairing code expiry no longer checked",
        ROOT / "inventory" / "community_api.py",
        "        if pairing is None or not pairing.is_usable():",
        "        if pairing is None:",
        "inventory.tests.test_community_pairing",
    ),
    (
        "A new connection can search parts by default (inventory handed over)",
        ROOT / "inventory" / "community_api.py",
        '                "shares_parts": False,\n                "outbound_api_key": callback_key or "",',
        '                "shares_parts": True,\n                "outbound_api_key": callback_key or "",',
        "inventory.tests.test_community_pairing",
    ),
    (
        "Revoking leaves the permissions in place (disconnect does nothing)",
        ROOT / "inventory" / "views" / "community.py",
        '    peer.status = Peer.REVOKED\n    peer.shares_parts = False\n    peer.exchanges_pins = False\n    peer.save(update_fields=["status", "shares_parts", "exchanges_pins"])',
        '    peer.status = Peer.REVOKED\n    peer.save(update_fields=["status"])',
        "inventory.tests.test_community_pairing",
    ),
    (
        "Claim endpoint no longer rate-limited (free brute force on a short code)",
        ROOT / "inventory" / "views" / "community.py",
        "    if _claim_rate_limited(request):",
        "    if False:",
        "inventory.tests.test_community_pairing",
    ),
    # --- the login page ------------------------------------------------------
    # The app's own login replaced Django's admin login as the front door. These are
    # the decisions that make that true rather than cosmetic.
    (
        "Login wall back to the Django admin's login page (/login/ a 404 again)",
        ROOT / "config" / "settings.py",
        "LOGIN_URL = '/login/'",
        "LOGIN_URL = '/admin/login/'",
        "inventory.tests.test_login",
    ),
    (
        "Login page falls back to the admin's own template",
        ROOT / "inventory" / "views" / "auth.py",
        'template_name = "inventory/login.html"',
        'template_name = "admin/login.html"',
        "inventory.tests.test_login",
    ),
    (
        "A signed-in visitor is shown the login form again",
        ROOT / "inventory" / "views" / "auth.py",
        "redirect_authenticated_user = True",
        "redirect_authenticated_user = False",
        "inventory.tests.test_login",
    ),
    (
        "Logout lands on the admin login rather than the app's",
        ROOT / "config" / "settings.py",
        "LOGOUT_REDIRECT_URL = '/login/'",
        "LOGOUT_REDIRECT_URL = '/admin/login/'",
        "inventory.tests.test_login",
    ),
    (
        "Fresh install shows a dead login form instead of the setup wizard",
        ROOT / "inventory" / "middleware.py",
        '        "/api/",',
        '        "/api/",\n        "/login/",',
        "inventory.tests.test_login",
    ),
    # --- the printer driver layer ---------------------------------------------
    # Silent failures, every one of them: a clipped label, a wrong-sized label and a
    # mirrored label all look like a broken printer rather than a broken app.
    (
        "Rendering ignores the saved dots-per-inch (right shape, wrong size)",
        ROOT / "inventory" / "label_printing.py",
        "    return hardware_config.printer_dpi() or get_driver(hardware_config.printer_driver()).default_dpi",
        "    return get_driver(hardware_config.printer_driver()).default_dpi",
        "inventory.tests.test_label_drivers",
    ),
    (
        "A label too wide for the print head is sent anyway (prints clipped)",
        ROOT / "inventory" / "label_printing.py",
        "    if driver.max_width_dots and width_px > driver.max_width_dots:",
        "    if False:",
        "inventory.tests.test_label_drivers",
    ),
    (
        "An unknown printer type crashes instead of falling back to ZPL",
        ROOT / "inventory" / "label_drivers.py",
        '    return DRIVERS.get(key or "", DRIVERS["zpl"])',
        "    return DRIVERS[key]",
        "inventory.tests.test_label_drivers",
    ),
    (
        "Raster bits mirrored (leftmost dot in the low bit instead of the high one)",
        ROOT / "inventory" / "label_drivers.py",
        "                row[x // 8] |= 0x80 >> (x % 8)",
        "                row[x // 8] |= 0x01 << (x % 8)",
        "inventory.tests.test_label_drivers",
    ),
    (
        "Brother raster line shortened to the label width (stale dots in the head)",
        ROOT / "inventory" / "label_drivers.py",
        "_BROTHER_HEAD_BYTES = 90",
        "_BROTHER_HEAD_BYTES = 88",
        "inventory.tests.test_label_drivers",
    ),
    (
        "Bridge writes an image to the raw device instead of spooling it to CUPS",
        ROOT / "label-printer" / "pi" / "server.py",
        '    if ctype == CUPS_CONTENT_TYPE:\n        return "cups"',
        '    if ctype == CUPS_CONTENT_TYPE:\n        return "raw"',
        "inventory.tests.test_label_drivers",
    ),
    (
        "Dots-per-inch range check removed (nonsense stored, then ignored)",
        ROOT / "inventory" / "views" / "setup.py",
        "    if not raw.isdigit() or not (50 <= int(raw) <= 2400):",
        "    if False:",
        "inventory.tests.test_setup_wizard",
    ),
    # --- community pins and the map -------------------------------------------
    # The opt-out is the promise this feature makes, so several of these break it in
    # ways that would be invisible: a removed pin that still holds its coordinates, a
    # stale copy that brings a workshop back, a removal that never gets sent.
    (
        "A forged pin is stored anyway (signature check skipped)",
        ROOT / "inventory" / "community_pins.py",
        "    if not isinstance(pin, dict) or not verify_pin(pin):",
        "    if not isinstance(pin, dict):",
        "inventory.tests.test_community_pins",
    ),
    (
        "Newest-wins removed (an old pin overwrites a newer one)",
        ROOT / "inventory" / "community_pins.py",
        "        if existing is not None and signed_at <= existing.signed_at:",
        "        if False:",
        "inventory.tests.test_community_pins",
    ),
    (
        "A removal is stored as a live pin (opt-out hides instead of deleting)",
        ROOT / "inventory" / "community_pins.py",
        '                "gone": gone,',
        '                "gone": False,',
        "inventory.tests.test_community_pins",
    ),
    (
        "Hop limit ignored on the way out (unbounded gossip)",
        ROOT / "inventory" / "community_pins.py",
        "    for row in KnownPin.objects.filter(hops__lt=MAX_HOPS):",
        "    for row in KnownPin.objects.all():",
        "inventory.tests.test_community_pins",
    ),
    (
        "A connection without pin permissions can read the map",
        ROOT / "inventory" / "community_pins.py",
        "    for peer in Peer.objects.filter(status=Peer.ACTIVE, exchanges_pins=True):",
        "    for peer in Peer.objects.filter(status=Peer.ACTIVE):",
        "inventory.tests.test_community_pins",
    ),
    (
        "A revoked connection's old key still works",
        ROOT / "inventory" / "community_pins.py",
        "    for peer in Peer.objects.filter(status=Peer.ACTIVE, exchanges_pins=True):",
        "    for peer in Peer.objects.filter(exchanges_pins=True):",
        "inventory.tests.test_community_pins",
    ),
    (
        "The owner's name published to the whole network with the pin",
        ROOT / "inventory" / "community_pins.py",
        '        name="",',
        "        name=profile.display_name,",
        "inventory.tests.test_community_pins",
    ),
    (
        "Opting out publishes the pin instead of the removal",
        ROOT / "inventory" / "community_pins.py",
        "    if CommunityProfile.load().discoverable:\n        return own_pin()",
        "    if True:\n        return own_pin()",
        "inventory.tests.test_community_pins",
    ),
    (
        "Changing discoverability tells nobody (the removal never goes out)",
        ROOT / "inventory" / "views" / "setup.py",
        "            if profile.discoverable != was_discoverable:",
        "            if False:",
        "inventory.tests.test_community_pins",
    ),
    # --- templates ------------------------------------------------------------
    # A multi-line `{# #}` comment is not a comment: the template engine sees text, so the
    # note renders on the page. That shipped once, in the More menu.
    (
        "A template comment spans lines again (the note renders on the page)",
        ROOT / "inventory" / "templates" / "inventory" / "base.html",
        "          {% comment %}",
        "          {# a note that never closes on this line",
        "inventory.tests.test_templates",
    ),
    (
        "A failed update check is reported as up to date (silently never checks again)",
        ROOT / "inventory" / "updates.py",
        '                ok=False,\n                error=(\n                    f"GitHub won\'t show {repo()} to an unsigned-in request (HTTP 404). "',
        '                ok=True,\n                error=(\n                    f"GitHub won\'t show {repo()} to an unsigned-in request (HTTP 404). "',
        "inventory.tests.test_updates",
    ),
    # --- flashing the LED controller's board ---------------------------------
    (
        "The board check claims success when the board never answered",
        ROOT / "inventory" / "views" / "setup.py",
        "    if response.status_code == 502:\n        return False, (",
        "    if response.status_code == 502:\n        return True, (",
        "inventory.tests.test_setup_wizard",
    ),
    (
        "The board check's demo is left running instead of switched off",
        ROOT / "inventory" / "views" / "setup.py",
        'requests.post(f"{url}/demo", json={"on": False}, headers=headers, timeout=10)',
        'requests.post(f"{url}/demo", json={"on": True}, headers=headers, timeout=10)',
        "inventory.tests.test_setup_wizard",
    ),
    (
        "The board check forgets the controller's shared secret",
        ROOT / "inventory" / "views" / "setup.py",
        'response = requests.post(f"{url}/demo", json={"on": True}, headers=headers, timeout=10)',
        'response = requests.post(f"{url}/demo", json={"on": True}, headers={}, timeout=10)',
        "inventory.tests.test_setup_wizard",
    ),
    (
        "The flashing step is dropped from the wizard (unreachable from Settings)",
        ROOT / "inventory" / "wizard.py",
        "_ALL_STEPS = [ACCOUNT, SITE, LIGHTS, FLASH, PRINTER, REFERENCE, COMMUNITY, EMAIL, AI, ACCESS]",
        "_ALL_STEPS = [ACCOUNT, SITE, LIGHTS, PRINTER, REFERENCE, COMMUNITY, EMAIL, AI, ACCESS]",
        "inventory.tests.test_setup_wizard",
    ),
    (
        "The email step is dropped from the wizard (notifications hidden in Settings)",
        ROOT / "inventory" / "wizard.py",
        "_ALL_STEPS = [ACCOUNT, SITE, LIGHTS, FLASH, PRINTER, REFERENCE, COMMUNITY, EMAIL, AI, ACCESS]",
        "_ALL_STEPS = [ACCOUNT, SITE, LIGHTS, FLASH, PRINTER, REFERENCE, COMMUNITY, AI, ACCESS]",
        "inventory.tests.test_notifications",
    ),
    (
        "The flashing script looks for the console channel instead of the data one",
        ROOT / "led-controller" / "pi" / "flash-scorpio.py",
        'if entry.name.endswith("-if02"):',
        'if entry.name.endswith("-if00"):',
        "inventory.tests.test_flash_scorpio",
    ),
    (
        "The flashing script calls a present library missing (a false trail)",
        ROOT / "led-controller" / "pi" / "flash-scorpio.py",
        'candidates = [lib / f"{name}.mpy", lib / f"{name}.py", lib / name]',
        'candidates = [lib / f"{name}.mpy"]',
        "inventory.tests.test_flash_scorpio",
    ),
    # --- community search, messaging, and email notifications -----------------
    # The privacy boundaries these three features add: the shareable-only filter, the
    # fuzzed quantity, the block that stays sticky against reconnection, idempotent
    # delivery, and per-event email consent.
    (
        "Peer search drops the shareable filter (unshared categories exposed)",
        ROOT / "inventory" / "community_search.py",
        "Part.objects.filter(category__is_shareable=True)",
        "Part.objects.filter(category__isnull=False)",
        "inventory.tests.test_community_search",
    ),
    (
        "Peer search reports an exact count instead of a bucket",
        ROOT / "inventory" / "community_search.py",
        '    total = sum(counted)\n    if total <= 0:\n        return "none"\n    if total < 5:\n        return "a few"\n    return "some"',
        "    total = sum(counted)\n    return str(total)",
        "inventory.tests.test_community_search",
    ),
    (
        "A blocked workshop can reconnect with a fresh code",
        ROOT / "inventory" / "community_api.py",
        "        if peer.blocked:",
        "        if False:",
        "inventory.tests.test_community_messages",
    ),
    (
        "A retried message is stored twice (idempotency removed)",
        ROOT / "inventory" / "community_messages.py",
        '    if remote_id and Message.objects.filter(\n        peer=peer, direction=Message.INBOUND, remote_id=remote_id\n    ).exists():\n        return False',
        "    if False:\n        return False",
        "inventory.tests.test_community_messages",
    ),
    (
        "A revoked (or blocked) workshop can still message",
        ROOT / "inventory" / "community_messages.py",
        "    for peer in Peer.objects.filter(status=Peer.ACTIVE):",
        "    for peer in Peer.objects.filter(status__in=[Peer.ACTIVE, Peer.REVOKED]):",
        "inventory.tests.test_community_messages",
    ),
    (
        "Email notifications send regardless of the owner's per-event choices",
        ROOT / "inventory" / "notifications.py",
        "    if not (s and getattr(s, flag_field, False)):",
        "    if False:",
        "inventory.tests.test_notifications",
    ),
    # --- duplicate detection on intake ----------------------------------------
    (
        "Duplicate check skipped (a second entry created silently)",
        ROOT / "inventory" / "views" / "parts.py",
        '                if not request.POST.get("create_confirmed"):',
        "                if False:",
        "inventory.tests.test_duplicate_detection",
    ),
    # --- CSV import ------------------------------------------------------------
    (
        "Import stops matching existing parts (re-import creates duplicates)",
        ROOT / "inventory" / "csv_io.py",
        "            part = Part.objects.filter(normalized_name=normalized).first()",
        "            part = None",
        "inventory.tests.test_csv_io",
    ),
    # --- voice intake ----------------------------------------------------------
    (
        "Voice intake accepts a missing key (anyone can queue notes)",
        ROOT / "inventory" / "views" / "searching.py",
        '    provided_key = request.headers.get("X-Api-Key") or request.GET.get("key") or request.POST.get("key") or ""',
        '    provided_key = request.headers.get("X-Api-Key") or request.GET.get("key") or request.POST.get("key") or settings.VOICE_SEARCH_API_KEY or ""',
        "inventory.tests.test_voice_intake",
    ),
    # --- DeepSeek enrichment ---------------------------------------------------
    (
        "Enrichment button shows without a configured key (opt-in broken)",
        ROOT / "inventory" / "enrichment_ai.py",
        "def is_configured():\n    return bool(_api_key())",
        "def is_configured():\n    return True",
        "inventory.tests.test_enrichment_ai",
    ),
    # --- seed peer -------------------------------------------------------------
    (
        "Seed peer grants inventory access (the pins-only default is gone)",
        ROOT / "inventory" / "community_api.py",
        "        is_seed=True,\n        exchanges_pins=True,\n        shares_parts=False,",
        "        is_seed=True,\n        exchanges_pins=True,\n        shares_parts=True,",
        "inventory.tests.test_community_models",
    ),
    # --- feedback relay --------------------------------------------------------
    # The relay endpoint is public by design, so the only thing standing between it
    # and a spam pipe into the maintainer's inbox is the shared-secret check. Remove
    # that and any caller can fire emails at them.
    (
        "Feedback relay accepts any key (a public endpoint spams the maintainer)",
        PKG / "help.py",
        "    if expected_key and payload.get(\"key\") != expected_key:",
        "    if False:",
        "inventory.tests.test_feedback",
    ),
]


def run(label):
    proc = subprocess.run(
        [PY, "manage.py", "test", label],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


print("=" * 72)
print("BASELINE")
print("=" * 72)
ok, out = run("inventory")
print("clean tree ->", "PASS" if ok else "FAIL")
if not ok:
    print(out[-3000:])
    sys.exit(1)

results = []
for name, path, old, new, label in MUTATIONS:
    original = path.read_text(encoding="utf-8")
    if old not in original:
        results.append((name, "SKIPPED (anchor not found)"))
        print(f"  !! anchor not found in {path.name}: {name}")
        continue
    path.write_text(original.replace(old, new, 1), encoding="utf-8")
    try:
        ok, out = run(label)
        results.append((name, "caught" if not ok else "MISSED"))
    finally:
        path.write_text(original, encoding="utf-8")
        # Restoring the source is not enough on its own. Python decides whether cached
        # bytecode is current by comparing the source's mtime, at one-second
        # resolution -- so restoring a file in the same second the mutation was written
        # to leaves the *mutated* .pyc in place, and the next test run loads it. That
        # presents as the suite failing on a clean tree, which is a genuinely
        # confusing afternoon. Dropping the cached bytecode is the reliable fix.
        try:
            os.remove(importlib.util.cache_from_source(str(path)))
        except OSError:
            pass

print()
print("=" * 72)
print("MUTATION RESULTS")
print("=" * 72)
missed = 0
for name, verdict in results:
    mark = "OK  " if verdict == "caught" else "!!!!"
    if verdict != "caught":
        missed += 1
    print(f"  {mark} {verdict:9} {name}")
print()
print(f"{len(results) - missed}/{len(results)} mutations caught")
sys.exit(1 if missed else 0)
