"""Portability guard.

This project is meant to be run by other people on whatever they happen to have:
Docker, Linux, macOS, and Windows if possible. The app is portable *by
construction* today — no POSIX-only imports, no shell-outs, no locale-dependent
file reads — but that is easy to lose one convenient `fcntl` import at a time, and
the loss is invisible on the machine it is developed on (a Mac).

So the contract is enforced by reading the source. That is deliberately a test
rather than a paragraph in a document: a rule nobody runs is a rule that erodes.

**What is exempt, and why.** `pi-kiosk/`, `led-controller/pi/` and
`label-printer/pi/` are Raspberry Pi hardware code. They legitimately use
`pkill`, `chromium`, GPIO and shell scripts, and a Windows user simply does not
run them. What matters is that the *app* never assumes any of that — which is why
it talks to the lights and the printer over HTTP instead of linking to GPIO.
`scripts/` is developer tooling and checked for encoding only.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent.parent

# The shipped application. Everything here must run on any platform.
SHIPPED_DIRS = ["inventory", "config"]
# Developer tooling: a dev script may legitimately shell out, so only the encoding
# rules apply to it.
DEV_TOOL_DIRS = ["scripts"]

SKIP_PARTS = {"venv", ".venv", "__pycache__", "node_modules", ".git", ".mypy_cache"}

# Modules that exist on only one family of platforms. Importing any of these makes
# the app unrunnable elsewhere; `nt`/`winreg`/`msvcrt` are included for symmetry,
# because being Windows-only is just as much a portability bug.
PLATFORM_ONLY_MODULES = {
    "fcntl", "termios", "pwd", "grp", "resource", "pty", "tty", "crypt",
    "syslog", "posix", "nt", "msvcrt", "winreg", "winsound", "mmap", "select",
}

# Hardware libraries. The app must reach hardware over HTTP, never by importing a
# Pi-specific driver, or every non-Pi install breaks.
HARDWARE_MODULES = {
    "RPi", "gpiozero", "board", "busio", "digitalio", "microcontroller",
    "adafruit_blinka", "adafruit_bus_device", "smbus", "smbus2", "spidev",
    "pigpio", "RPLCD", "serial",
}

# Settings that must be optional, and must therefore be declared with an empty
# default. An install with no lights and no printer has to work — that is the
# whole point of a project other people can run.
OPTIONAL_HARDWARE_SETTINGS = [
    "LED_CONTROLLER_URL", "LED_CONTROLLER_KEY",
    "LABEL_PRINTER_URL", "LABEL_PRINTER_KEY",
    "VOICE_SEARCH_API_KEY", "KIOSK_AUTOLOGIN_TOKEN",
]


SELF = Path(__file__).resolve()

# Substrings that never belong in the shipped app: they are the fastest route to
# code that only runs on one operating system.
SHELL_NEEDLES = ("subprocess", "os.system", "os.popen", "shell=True", "popen(")


def python_files(dirs):
    for name in dirs:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if SKIP_PARTS.intersection(path.parts):
                continue
            if path.resolve() == SELF:
                # This guard necessarily contains the patterns it searches for, so
                # scanning itself would always "fail". Skipping one file is clearer
                # than obfuscating the patterns to dodge a self-match.
                continue
            yield path


def parsed(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def dotted_names(tree):
    """Every module name referenced by an import, as dotted strings."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                yield node.module, node.lineno


def matches(dotted, candidates):
    """True if the module or its root package is in `candidates`."""
    root = dotted.split(".")[0]
    return dotted in candidates or root in candidates


class ImportPortabilityTests(SimpleTestCase):
    def test_no_platform_only_imports_in_the_shipped_app(self):
        offenders = []
        for path in python_files(SHIPPED_DIRS):
            for dotted, lineno in dotted_names(parsed(path)):
                if matches(dotted, PLATFORM_ONLY_MODULES):
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno} imports {dotted}")
        self.assertEqual(
            offenders, [],
            "Platform-specific import in the app — this makes it unrunnable on other "
            "operating systems:\n  " + "\n  ".join(offenders),
        )

    def test_no_direct_hardware_library_imports(self):
        """Hardware is reached over HTTP through the settings in config/settings.py.

        Importing a Pi driver here would mean the app cannot even start on a laptop,
        which defeats the point of releasing it for other people to run.
        """
        offenders = []
        for path in python_files(SHIPPED_DIRS):
            for dotted, lineno in dotted_names(parsed(path)):
                if matches(dotted, HARDWARE_MODULES):
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno} imports {dotted}")
        self.assertEqual(
            offenders, [],
            "Direct hardware-library import — reach hardware over the configured HTTP "
            "service instead:\n  " + "\n  ".join(offenders),
        )


class ShellExecutionTests(SimpleTestCase):
    def test_the_app_never_shells_out(self):
        """Spawning processes is the fastest route to platform-specific code."""
        offenders = []
        for path in python_files(SHIPPED_DIRS):
            text = path.read_text(encoding="utf-8")
            for needle in SHELL_NEEDLES:
                if needle in text:
                    offenders.append(f"{path.relative_to(ROOT)} contains {needle!r}")
        self.assertEqual(
            offenders, [],
            "Process-spawning calls in the shipped app — this is the fastest way to "
            "make an app platform-specific:\n  " + "\n  ".join(offenders),
        )


class EncodingTests(SimpleTestCase):
    """Windows defaults to a legacy locale encoding (cp1252 on most installs) rather
    than UTF-8, so any read or write without an explicit encoding either crashes or
    silently mangles non-ASCII text — accented part names, the × in label sizes, the
    em-dashes in this project's own docstrings."""

    def check(self, dirs):
        offenders = []
        for path in python_files(dirs):
            tree = parsed(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                missing = None
                func = node.func
                if isinstance(func, ast.Name) and func.id == "open":
                    missing = "open()"
                elif isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text"):
                    missing = f".{func.attr}()"
                elif (
                    isinstance(func, ast.Attribute) and func.attr == "open"
                    and isinstance(func.value, ast.Name) and func.value.id == "io"
                ):
                    missing = "io.open()"
                if missing and not any(kw.arg == "encoding" for kw in node.keywords):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} {missing}")
        return offenders

    def test_shipped_app_always_states_an_encoding(self):
        offenders = self.check(SHIPPED_DIRS)
        self.assertEqual(
            offenders, [],
            "File access without an explicit encoding — on Windows this reads/writes "
            "using cp1252 and breaks on non-ASCII text:\n  " + "\n  ".join(offenders),
        )

    def test_dev_tooling_always_states_an_encoding(self):
        offenders = self.check(DEV_TOOL_DIRS)
        self.assertEqual(
            offenders, [],
            "Dev tooling without an explicit encoding:\n  " + "\n  ".join(offenders),
        )


class OptionalHardwareTests(SimpleTestCase):
    def test_hardware_settings_are_declared_with_empty_defaults(self):
        """Read from the source, not from settings.

        Asserting on the live values would be a trap: the container sets these, so
        such a test would pass on a laptop and fail in production — or worse, drive
        real hardware. See docs/HANDOFF.md item 21.
        """
        source = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
        for name in OPTIONAL_HARDWARE_SETTINGS:
            with self.subTest(setting=name):
                self.assertIn(
                    f'os.environ.get("{name}", "")', source,
                    f"{name} must be declared as optional with an empty default, so an "
                    "install without that hardware still runs",
                )

    def test_the_app_asks_for_hardware_addresses_not_hardware_access(self):
        """The integration is HTTP against a URL, which is why a Mac or a Windows box
        can run the app while the lights stay on a Pi."""
        source = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
        for name in ("LED_CONTROLLER_URL", "LABEL_PRINTER_URL"):
            with self.subTest(setting=name):
                self.assertIn(f'"{name}"', source)


class LabelFontTests(SimpleTestCase):
    """Labels are rasterised on whatever machine the app runs on, so the font chain
    has to resolve everywhere rather than only where it was written."""

    def test_every_font_chain_covers_all_three_platforms(self):
        from inventory.label_printing import _FONT_CANDIDATES

        for key, paths in _FONT_CANDIDATES.items():
            with self.subTest(font=key):
                joined = " ".join(paths)
                self.assertTrue(any(p.startswith("/usr/share/fonts") for p in paths),
                                f"{key}: no Linux font")
                self.assertTrue(any(p.startswith("/System/Library/Fonts") for p in paths),
                                f"{key}: no macOS font")
                self.assertTrue(any(p.startswith("C:/Windows/Fonts") for p in paths),
                                f"{key}: no Windows font (got: {joined})")

    def test_every_bold_italic_combination_is_covered(self):
        from inventory.label_printing import _FONT_CANDIDATES

        for bold in (False, True):
            for italic in (False, True):
                self.assertIn((bold, italic), _FONT_CANDIDATES)

    def test_the_fallback_renders_at_the_requested_size(self):
        """The last resort must not silently shrink the text. Bare load_default()
        ignores the size argument entirely, which on a machine with none of the
        fonts above would produce unreadable labels rather than an error.

        The font chain is forced to fail here rather than relying on this machine
        happening to lack a font — on a Mac the chain resolves to real Arial and the
        fallback branch would never run, so the test would pass without testing it.
        """
        from unittest import mock

        from inventory import label_printing

        with mock.patch.dict(
            label_printing._FONT_CANDIDATES, {(False, False): ["/nonexistent/nope.ttf"]}
        ):
            big = label_printing._load_font(False, False, 80)
            small = label_printing._load_font(False, False, 12)
        self.assertGreater(big.getbbox("Wg")[3], small.getbbox("Wg")[3])

    def test_a_missing_font_file_falls_through_rather_than_raising(self):
        """Every entry in the chain is optional; a machine with none of them must still
        print labels."""
        from unittest import mock

        from inventory import label_printing

        empty = {key: ["/nonexistent/a.ttf", "/nonexistent/b.ttf"] for key in label_printing._FONT_CANDIDATES}
        with mock.patch.dict(label_printing._FONT_CANDIDATES, empty):
            for bold in (False, True):
                for italic in (False, True):
                    with self.subTest(bold=bold, italic=italic):
                        self.assertIsNotNone(label_printing._load_font(bold, italic, 24))

    def test_loading_a_font_never_raises(self):
        """Whatever fonts exist on this machine, this must return something usable."""
        from inventory.label_printing import _load_font

        for bold in (False, True):
            for italic in (False, True):
                with self.subTest(bold=bold, italic=italic):
                    self.assertIsNotNone(_load_font(bold, italic, 24))


class ServerPortabilityTests(SimpleTestCase):
    def test_requirements_ship_a_server_for_windows_too(self):
        """gunicorn is POSIX-only — it needs fork(). Without a second server a Windows
        user can install the app and then have no way to serve it."""
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("gunicorn", text)
        self.assertIn("waitress", text, "no Windows-capable WSGI server declared")
        self.assertIn('sys_platform == "win32"', text,
                      "the Windows server must be behind an environment marker so "
                      "POSIX installs do not download it")
