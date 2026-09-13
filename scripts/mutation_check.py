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
    original = path.read_text()
    if old not in original:
        results.append((name, "SKIPPED (anchor not found)"))
        print(f"  !! anchor not found in {path.name}: {name}")
        continue
    path.write_text(original.replace(old, new, 1))
    try:
        ok, out = run(label)
        results.append((name, "caught" if not ok else "MISSED"))
    finally:
        path.write_text(original)

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
