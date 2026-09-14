"""The Scorpio flashing script's decisions.

`led-controller/pi/flash-scorpio.py` runs on the Pi, where the board's USB is, and it is
interactive — but the parts that decide *what to do* are pure functions, and they are the
parts that can be wrong in ways nobody notices until a stranger's board is half-flashed.
So they are tested here, against temporary directory trees rather than real hardware.

Two of these tests exist because of a specific way the previous flash went wrong (recorded
in `docs/HANDOFF.md`): `boot.py`'s second serial channel only appears after a true hardware
reset, and `SCORPIO_SERIAL_PORT` has to point at that channel (`-if02`), not at the console
one or at a bare `/dev/ttyACM0` that could be either.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

SCRIPT = Path(__file__).resolve().parent.parent.parent / "led-controller" / "pi" / "flash-scorpio.py"


def load_script():
    """Loaded by path: `led-controller/pi/` is not a package, and it is hardware-side code."""
    spec = importlib.util.spec_from_file_location("flash_scorpio", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


flash = load_script()


class FakeTree(SimpleTestCase):
    """A throwaway directory tree, for the functions that look at the filesystem."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def make(self, *parts, content=""):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


class MountTests(FakeTree):
    def test_finds_a_labelled_volume(self):
        self.make("media", "RPI-RP2", "INFO_UF2.TXT")
        self.assertEqual(flash.find_mount("RPI-RP2", roots=[self.root / "media"]), self.root / "media" / "RPI-RP2")

    def test_returns_none_when_the_label_is_not_there(self):
        self.make("media", "CIRCUITPY", "boot_out.txt")
        self.assertIsNone(flash.find_mount("RPI-RP2", roots=[self.root / "media"]))

    def test_checks_the_roots_in_order(self):
        self.make("one", "CIRCUITPY", "a")
        self.make("two", "CIRCUITPY", "b")
        found = flash.find_mount("CIRCUITPY", roots=[self.root / "two", self.root / "one"])
        self.assertEqual(found, self.root / "two" / "CIRCUITPY")

    def test_mount_roots_are_per_user_first(self):
        roots = [str(r) for r in flash.mount_roots("pi")]
        self.assertEqual(roots[0], "/media/pi")
        self.assertIn("/run/media/pi", roots)


class RouteTests(SimpleTestCase):
    def test_a_board_in_bootloader_gets_circuitpython_installed(self):
        self.assertEqual(flash.decide_route(Path("/media/RPI-RP2"), None), "circuitpython")

    def test_a_running_board_only_needs_the_firmware_files(self):
        self.assertEqual(flash.decide_route(None, Path("/media/CIRCUITPY")), "firmware")

    def test_no_board_means_nothing_to_do(self):
        self.assertEqual(flash.decide_route(None, None), "nothing")

    def test_a_forced_route_wins(self):
        """`--route firmware` with the board in bootloader mode is a mistake worth honouring."""
        self.assertEqual(flash.decide_route(Path("/media/RPI-RP2"), None, "firmware"), "firmware")
        self.assertEqual(flash.decide_route(None, Path("/media/CIRCUITPY"), "circuitpython"), "circuitpython")


class SerialPortTests(FakeTree):
    def test_the_two_channels_are_told_apart(self):
        self.make("dev", "serial", "by-id", "usb-Adafruit_Feather_RP2040_Scorpio_1234-if00", "")
        self.make("dev", "serial", "by-id", "usb-Adafruit_Feather_RP2040_Scorpio_1234-if02", "")
        ports = flash.serial_ports(self.root / "dev")
        self.assertTrue(str(ports["console"]).endswith("-if00"))
        self.assertTrue(str(ports["data"]).endswith("-if02"))

    def test_another_board_is_ignored(self):
        """Only the Scorpio is ours; a second RP2040 on the same Pi must not be mistaken for it."""
        self.make("dev", "serial", "by-id", "usb-Adafruit_Feather_RP2040_OTHER_1234-if02", "")
        ports = flash.serial_ports(self.root / "dev")
        self.assertIsNone(ports["data"])

    def test_a_board_without_boot_py_has_no_data_channel(self):
        """The honest "is the firmware running?" signal: one channel means no protocol channel."""
        self.make("dev", "serial", "by-id", "usb-Adafruit_Feather_RP2040_Scorpio_1234-if00", "")
        ports = flash.serial_ports(self.root / "dev")
        self.assertIsNone(ports["data"])

    def test_ttyacm_devices_are_listed_as_a_fallback(self):
        self.make("dev", "ttyACM0", "")
        self.make("dev", "ttyACM1", "")
        ports = flash.serial_ports(self.root / "dev")
        self.assertEqual([p.name for p in ports["ttyacm"]], ["ttyACM0", "ttyACM1"])

    def test_missing_devices_do_not_raise(self):
        ports = flash.serial_ports(self.root / "nope")
        self.assertEqual(ports, {"console": None, "data": None, "ttyacm": []})


class LibraryTests(FakeTree):
    def test_compiled_libraries_count_as_present(self):
        for name in flash.REQUIRED_LIBRARIES:
            self.make("CIRCUITPY", "lib", f"{name}.mpy", "")
        self.assertEqual(flash.missing_libraries(self.root / "CIRCUITPY"), [])

    def test_source_libraries_count_as_present_too(self):
        """A hand-copied .py works. Reporting it as missing sends someone down a false trail."""
        for name in flash.REQUIRED_LIBRARIES:
            self.make("CIRCUITPY", "lib", f"{name}.py", "")
        self.assertEqual(flash.missing_libraries(self.root / "CIRCUITPY"), [])

    def test_a_library_directory_counts_as_present(self):
        """`circup` installs some libraries as a package directory rather than one file."""
        for name in flash.REQUIRED_LIBRARIES:
            self.make("CIRCUITPY", "lib", name, "__init__.py", content="")
        self.assertEqual(flash.missing_libraries(self.root / "CIRCUITPY"), [])

    def test_only_the_missing_ones_are_reported(self):
        self.make("CIRCUITPY", "lib", "adafruit_neopxl8.mpy", "")
        self.assertEqual(
            flash.missing_libraries(self.root / "CIRCUITPY"),
            ["adafruit_pioasm", "adafruit_pixelbuf"],
        )

    def test_an_empty_board_misses_all_of_them(self):
        self.make("CIRCUITPY", "boot_out.txt", "")
        self.assertEqual(flash.missing_libraries(self.root / "CIRCUITPY"), list(flash.REQUIRED_LIBRARIES))


class FirmwareDirTests(FakeTree):
    def test_both_files_are_expected(self):
        self.make("boot.py", "")
        self.make("code.py", "")
        self.assertEqual(flash.missing_firmware(self.root), [])

    def test_a_half_copied_firmware_directory_is_reported(self):
        self.make("code.py", "")
        self.assertEqual(flash.missing_firmware(self.root), ["boot.py"])

    def test_the_files_are_named_for_the_board(self):
        self.assertEqual(sorted(flash.firmware_files(self.root)), ["boot.py", "code.py"])


class Uf2Tests(FakeTree):
    def test_an_explicit_image_is_used(self):
        image = self.make("somewhere", "cp.uf2", "")
        self.assertEqual(flash.find_uf2(str(image), self.root), image)

    def test_an_explicit_image_that_does_not_exist_is_reported_as_none(self):
        self.assertIsNone(flash.find_uf2(str(self.root / "nope.uf2"), self.root))

    def test_an_image_sitting_beside_the_firmware_is_picked_up(self):
        """How a stranger is told to do it: drop the .uf2 in and re-run."""
        self.make("adafruit-circuitpython-adafruit_feather_rp2040_scorpio-10.2.1.uf2", "")
        found = flash.find_uf2(None, self.root)
        self.assertTrue(found.name.endswith(".uf2"))

    def test_saying_how_to_get_one_names_the_board_page(self):
        message = flash.says_how_to_get_a_uf2(None)
        self.assertIn("adafruit_feather_rp2040_scorpio", message)
        self.assertIn("--uf2", message)


class EnvFileTests(FakeTree):
    def test_values_are_read(self):
        env = self.make(
            "env",
            content="# comment\n\nLED_CONTROLLER_KEY=abc123\nSCORPIO_SERIAL_PORT=/dev/serial/by-id/usb-X-if02\n",
        )
        parsed = flash.read_env_file(env)
        self.assertEqual(parsed["LED_CONTROLLER_KEY"], "abc123")
        self.assertTrue(parsed["SCORPIO_SERIAL_PORT"].endswith("-if02"))

    def test_quotes_and_spacing_are_tolerated(self):
        env = self.make("env", content='LED_CONTROLLER_KEY = "quoted value" \n')
        self.assertEqual(flash.read_env_file(env)["LED_CONTROLLER_KEY"], "quoted value")

    def test_an_unreadable_file_is_empty_rather_than_an_error(self):
        """Normal: the file holds the service's key and is often root-only."""
        self.assertEqual(flash.read_env_file(self.root / "not-there"), {})

    def test_the_real_default_is_the_service_env_file(self):
        self.assertEqual(str(flash.ENV_FILE), "/etc/led-controller/env")


if __name__ == "__main__":
    unittest.main()
