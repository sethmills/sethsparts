"""Mutation check: deliberately break real logic, confirm the suite notices.

A test suite that passes is worthless on its own -- what matters is whether it
FAILS when the behaviour it claims to protect is broken. Each mutation below
inverts a real decision the app makes. Anything that stays green is a blind spot.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWS = ROOT / "inventory" / "views.py"
MODELS = ROOT / "inventory" / "models.py"
PY = str(ROOT / "venv" / "bin" / "python")

MUTATIONS = [
    (
        "LED row/column split reversed (row->right, col->left)",
        VIEWS,
        'if row and segment.led_strip.endswith("-left"):',
        'if row and segment.led_strip.endswith("-right"):',
        "inventory.tests.test_led",
    ),
    (
        "FIFO stock consumption reversed to LIFO",
        VIEWS,
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
        VIEWS,
        "BINS_PER_DRAWER = 16",
        "BINS_PER_DRAWER = 8",
        "inventory.tests.test_bins",
    ),
    (
        "Empty kiosk token now matches any supplied token",
        VIEWS,
        "if not settings.KIOSK_AUTOLOGIN_TOKEN or not secrets.compare_digest(token, settings.KIOSK_AUTOLOGIN_TOKEN):",
        "if not secrets.compare_digest(token, settings.KIOSK_AUTOLOGIN_TOKEN):",
        "inventory.tests.test_kiosk_auth",
    ),
    (
        "Voice API accepts a missing key when none is configured",
        VIEWS,
        "if not settings.VOICE_SEARCH_API_KEY or provided_key != settings.VOICE_SEARCH_API_KEY:",
        "if provided_key != settings.VOICE_SEARCH_API_KEY:",
        "inventory.tests.test_voice_api",
    ),
    (
        "Bin scan conflict check removed (silent overwrite)",
        VIEWS,
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
        VIEWS,
        "lines = [line for line in lines if line]",
        "lines = lines",
        "inventory.tests.test_intake",
    ),
]


def run(label):
    proc = subprocess.run(
        [PY, "manage.py", "test", label],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    out = proc.stdout + proc.stderr
    return proc.returncode == 0, out


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
        print(f"  !! anchor not found for: {name}")
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
