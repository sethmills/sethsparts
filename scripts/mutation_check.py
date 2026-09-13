"""Mutation check: deliberately break real logic, confirm the suite notices.

A test suite that passes is worthless on its own -- what matters is whether it
FAILS when the behaviour it claims to protect is broken. Each mutation below
inverts a real decision the app makes. Anything that stays green is a blind spot.

The view logic was split out of a single views.py into inventory/views/<topic>.py,
so the anchors below point at the module that now owns each behaviour. If a
mutation reports "anchor not found", the logic has moved and this list needs
updating -- which is itself useful signal that a refactor happened.
"""
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
        ROOT / "inventory" / "label_printing.py",
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
