"""The label driver layer, and the bridge that delivers what it produces.

Only the ZPL path has ever been printed on real hardware. The others are written from
the manufacturers' own manuals, so what these tests pin is the byte layout each manual
specifies. That does not prove a Brother or a Dymo will print it -- nothing on a
machine without the printer can -- but it does two useful things: it gives whoever
first tries one on real hardware a single place to compare against, and it stops a
careless refactor from silently changing what gets sent to a device nobody is watching.

The other thing worth protecting here is the cross-module agreement: the settings page's
stored choices, the driver registry, and the bridge's accepted content types all have to
name the same printers. Drift between them would present as "nothing prints", which is
exactly the kind of failure that takes an afternoon to find.
"""
import importlib.util
import os
from pathlib import Path
from unittest import mock

from PIL import Image
from django.test import TestCase, override_settings

from .. import label_printing
from ..label_drivers import (
    DRIVERS,
    brother_ql_raster,
    dymo_raster,
    driver_keys,
    get_driver,
    zpl_graphic_field,
)
from ..models import SiteSettings

PI_BRIDGE = Path(__file__).resolve().parent.parent.parent / "label-printer" / "pi" / "server.py"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def load_pi_bridge():
    """The Pi's bridge module, loaded off-Pi.

    Nothing in it needs hardware to be imported -- which is deliberate, and the same
    reason the LED controller's strip-map logic is importable without pyserial.
    """
    spec = importlib.util.spec_from_file_location("label_pi_bridge", PI_BRIDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bitmap(width, height, black=()):
    """A blank white image with the listed pixels inked in.

    One pixel is the smallest thing that can show which bit a dot lands on, which is
    the only way to check bit order without a printer.
    """
    image = Image.new("1", (width, height), 1)
    for x, y in black:
        image.putpixel((x, y), 0)
    return image


class RegistryTests(TestCase):
    def test_the_registry_matches_what_the_settings_page_can_store(self):
        """The settings page validates against the registry; a key the registry doesn't
        know is stored as ZPL, so a choice that exists in only one of the two places is
        a silent downgrade of the owner's printer."""
        stored = {choice[0] for choice in SiteSettings._meta.get_field("label_driver").choices}
        self.assertEqual(set(DRIVERS), stored)

    def test_only_zpl_claims_to_have_been_used_on_real_hardware(self):
        """The whole honesty of this module rests on this flag. If a driver gets tested
        for real, change it deliberately -- don't let it drift."""
        tested = [key for key, driver in DRIVERS.items() if driver.tested]
        self.assertEqual(tested, ["zpl"])

    def test_every_driver_says_what_it_is_and_where_it_came_from(self):
        for key, driver in DRIVERS.items():
            with self.subTest(driver=key):
                self.assertTrue(driver.name)
                self.assertTrue(driver.note, "the owner is shown this; an empty one is a lie by omission")
                self.assertTrue(driver.reference, "the byte layout needs a source")
                self.assertTrue(driver.content_type)
                self.assertGreater(driver.default_dpi, 0)

    def test_an_unknown_printer_type_falls_back_to_the_tested_one(self):
        for key in ("nonsense", "", None):
            with self.subTest(key=key):
                self.assertEqual(get_driver(key).key, "zpl")

    def test_the_drivers_are_offered_in_a_stable_order(self):
        self.assertEqual(driver_keys(), list(DRIVERS))


class DpiTests(TestCase):
    def test_the_default_is_the_printers_own_resolution(self):
        self.assertEqual(label_printing.configured_dpi(), 203)

    def test_a_saved_resolution_wins_over_the_default(self):
        SiteSettings.objects.create(label_dpi="300")
        self.assertEqual(label_printing.configured_dpi(), 300)

    def test_blank_means_the_printers_own_resolution(self):
        SiteSettings.objects.create(label_dpi="")
        self.assertEqual(label_printing.configured_dpi(), 203)

    def test_the_default_follows_the_printer_type(self):
        """A Brother QL is 300dpi, so choosing one has to move the renderer with it --
        otherwise labels come out the right shape at the wrong size."""
        SiteSettings.objects.create(label_driver="brother_ql")
        self.assertEqual(label_printing.configured_dpi(), 300)

    def test_a_nonsense_saved_resolution_is_ignored_rather_than_raised(self):
        """A hand-edited database should not be able to break label printing."""
        for value in ("banana", "0", "99999", "-203"):
            with self.subTest(value=value):
                SiteSettings.objects.all().delete()
                SiteSettings.objects.create(label_dpi=value)
                self.assertEqual(label_printing.configured_dpi(), 203)

    def test_rendering_follows_the_resolution(self):
        """The same physical label at a denser printer is more dots, which is the whole
        point of the setting."""
        at_203, width_203, height_203 = label_printing.render_label("Hello", "large")
        at_300, width_300, height_300 = label_printing.render_label("Hello", "large", dpi=300)
        self.assertEqual((width_203, height_203), (812, 406))
        self.assertEqual((width_300, height_300), (1200, 600))
        self.assertEqual(at_300.size, (1200, 600))
        self.assertEqual(at_203.size, (812, 406))

    def test_the_preview_uses_the_configured_resolution(self):
        """So the preview shows what will actually come out, not a differently
        proportioned likeness."""
        SiteSettings.objects.create(label_dpi="300")
        png = label_printing.render_label_png_bytes("Preview", "large")
        image = Image.open(__import__("io").BytesIO(png))
        self.assertEqual(image.size, (1200, 600))


class ZplDriverTests(TestCase):
    def test_it_produces_a_zpl_document(self):
        payload = get_driver("zpl").encode(bitmap(32, 8), 32, 8)
        self.assertIsInstance(payload, bytes)
        self.assertTrue(payload.startswith(b"^XA"))
        self.assertTrue(payload.rstrip().endswith(b"^XZ"))

    def test_it_declares_the_label_dimensions(self):
        payload = get_driver("zpl").encode(bitmap(32, 8), 32, 8)
        self.assertIn(b"^PW32", payload)
        self.assertIn(b"^LL8", payload)

    def test_it_sends_a_graphic_field_not_text(self):
        """The bitmap is the whole point: ZPL's own fonts cannot do italics."""
        payload = get_driver("zpl").encode(bitmap(16, 2), 16, 2)
        self.assertIn(b"^GFA,", payload)

    def test_the_encoder_and_the_packer_agree(self):
        image = bitmap(16, 2, black=[(0, 0)])
        self.assertEqual(get_driver("zpl").encode(image, 16, 2), zpl_graphic_field(image, 16, 2).encode("utf-8"))


class BrotherQlTests(TestCase):
    def job(self, width=64, height=3, black=()):
        return brother_ql_raster(bitmap(width, height, black), width, height)

    def test_the_job_starts_by_clearing_the_printer(self):
        """A 400-byte invalidate followed by ESC @, per the manual's initialization
        sequence -- a printer holding an earlier job's buffer is the failure this
        prevents."""
        job = self.job()
        self.assertEqual(job[:400], b"\x00" * 400)
        self.assertEqual(job[400:402], b"\x1b\x40")

    def test_it_switches_the_printer_into_raster_mode(self):
        self.assertIn(b"\x1b\x69\x61\x01", self.job())

    def test_it_declares_continuous_tape_at_the_tape_width(self):
        """ESC i z with the valid flag saying "believe the media type and width".
        Continuous tape is 0x0A; declaring die-cut labels while continuous tape is
        loaded makes the printer report an error instead of printing."""
        job = self.job()
        self.assertIn(bytes([0x1B, 0x69, 0x7A, 0x86, 0x0A, 62]), job)

    def test_it_tells_the_printer_how_many_raster_lines_to_expect(self):
        job = self.job(height=7)
        block = job.split(b"\x1b\x69\x7a")[1][:10]
        raster_count = int.from_bytes(block[4:8], "little")
        self.assertEqual(raster_count, 7)

    def test_one_raster_line_per_row_of_the_image(self):
        """Counted on a blank label, whose data cannot contain the line marker by
        accident."""
        height = 5
        job = self.job(width=64, height=height)
        self.assertEqual(job.count(b"\x67\x00\x5a"), height)

    def test_every_raster_line_is_the_full_print_head_width(self):
        """The head is 90 bytes wide whatever the label is, because the unused dots
        still have to be shifted through. A short line leaves stale dots on the
        previous label in the head's register."""
        height = 3
        job = self.job(width=64, height=height)
        lines = job.split(b"\x67\x00\x5a")[1:]
        self.assertEqual(len(lines), height)
        for line in lines[:-1]:
            self.assertEqual(len(line), 90)
        # The last line runs straight into the print command, so it is the marker,
        # 90 bytes, then Control-Z -- nothing else.
        self.assertEqual(lines[-1], b"\x00" * 90 + b"\x1a")

    def test_a_black_dot_lands_inside_the_print_area_not_at_the_heads_edge(self):
        """The raster data starts at the print area rather than the left edge of the
        head: 12 dots of margin at 300dpi. A dot drawn at bit 0 would sit 1mm left of
        where the layout expects it."""
        job = self.job(width=8, height=1, black=[(0, 0)])
        row = job.split(b"\x67\x00\x5a")[1][:90]
        self.assertEqual(row[0], 0x00, "nothing should land on the first byte")
        self.assertEqual(row[1], 0x08, "the first dot belongs 12 dots in")

    def test_it_ends_with_the_print_command(self):
        self.assertTrue(self.job().endswith(b"\x1a"))


class DymoDriverTests(TestCase):
    def job(self, width=64, height=3, black=()):
        return dymo_raster(bitmap(width, height, black), width, height)

    def test_the_job_resets_and_declares_the_line_width(self):
        job = self.job()
        self.assertTrue(job.startswith(b"\x1b\x40"), "ESC @ first")
        self.assertIn(bytes([0x1B, 0x42, 0x00]), job, "ESC B 0: start at the left margin")
        self.assertIn(bytes([0x1B, 0x44, 56]), job, "ESC D: 56 bytes per line")

    def test_one_syn_line_per_row_of_the_image(self):
        height = 4
        self.assertEqual(self.job(height=height).count(b"\x16"), height)

    def test_every_line_is_the_full_print_head_width_whatever_the_label_is(self):
        """Dymo's manual is explicit that the whole line must be sent every time,
        because there is no command for clearing the shift register."""
        for width in (8, 100, 448):
            with self.subTest(width=width):
                job = self.job(width=width, height=2)
                lines = job.split(b"\x16")[1:]
                self.assertEqual(len(lines), 2)
                for line in lines:
                    self.assertTrue(line.startswith(b"\x00" * 56) or len(line) >= 56)

    def test_the_leftmost_dot_is_the_most_significant_bit(self):
        """The manual says bit 7 prints at the left margin. Getting this backwards
        prints the label mirrored, which reads as a layout bug."""
        job = self.job(width=8, height=1, black=[(0, 0)])
        row = job.split(b"\x16")[1][:56]
        self.assertEqual(row[0], 0x80)
        self.assertEqual(row[1], 0x00)

    def test_the_rightmost_dot_of_a_byte_is_the_low_bit(self):
        job = self.job(width=8, height=1, black=[(7, 0)])
        row = job.split(b"\x16")[1][:56]
        self.assertEqual(row[0], 0x01)

    def test_a_narrow_label_is_padded_rather_than_shortened(self):
        job = self.job(width=8, height=1)
        row = job.split(b"\x16")[1][:56]
        self.assertEqual(row, b"\x00" * 56)

    def test_it_ends_with_a_form_feed(self):
        self.assertTrue(self.job().endswith(b"\x1b\x45"))


class CupsDriverTests(TestCase):
    def test_it_sends_a_png_for_the_queue_to_render(self):
        payload = get_driver("cups").encode(bitmap(32, 8), 32, 8)
        self.assertTrue(payload.startswith(PNG_MAGIC))
        self.assertEqual(Image.open(__import__("io").BytesIO(payload)).format, "PNG")

    def test_it_takes_any_width_because_the_driver_scales(self):
        self.assertIsNone(get_driver("cups").max_width_dots)


PRINTER_ON = override_settings(LABEL_PRINTER_URL="https://label.example.test", LABEL_PRINTER_KEY="secret")


class PrintLabelTests(TestCase):
    """What actually goes over the wire, per printer type."""

    def post_for(self, driver_key, size_key="large"):
        SiteSettings.objects.create(label_driver=driver_key)
        with mock.patch("requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            ok, error = label_printing.print_label("Hello", size_key)
        return ok, error, post

    @PRINTER_ON
    def test_the_configured_printer_decides_the_bytes_and_their_type(self):
        expected = {
            "zpl": (b"^XA", "application/x-zpl"),
            "cups": (PNG_MAGIC, "image/png"),
        }
        for key, (prefix, content_type) in expected.items():
            with self.subTest(driver=key):
                SiteSettings.objects.all().delete()
                ok, error, post = self.post_for(key)
                self.assertTrue(ok, error)
                call = post.call_args_list[0]
                self.assertTrue(call.kwargs["data"].startswith(prefix))
                self.assertEqual(call.kwargs["headers"]["Content-Type"], content_type)
                self.assertEqual(call.kwargs["headers"]["X-Api-Key"], "secret")

    @PRINTER_ON
    def test_a_brother_job_starts_with_the_invalidate_block(self):
        ok, error, post = self.post_for("brother_ql", size_key="tote")
        self.assertTrue(ok, error)
        self.assertTrue(post.call_args_list[0].kwargs["data"].startswith(b"\x00" * 400))
        self.assertEqual(post.call_args_list[0].kwargs["headers"]["Content-Type"], "application/vnd.brother-ql")

    @PRINTER_ON
    def test_a_dymo_job_starts_with_a_reset(self):
        ok, error, post = self.post_for("dymo", size_key="tote")
        self.assertTrue(ok, error)
        self.assertTrue(post.call_args_list[0].kwargs["data"].startswith(b"\x1b\x40"))
        self.assertEqual(
            post.call_args_list[0].kwargs["headers"]["Content-Type"], "application/vnd.dymo-labelwriter"
        )

    @PRINTER_ON
    def test_a_label_too_wide_for_the_printer_is_refused_before_anything_is_sent(self):
        """A print head is a fixed width. Sending a 4" label to a 448-dot Dymo would
        print a clipped label and report success, so the app has to say no."""
        SiteSettings.objects.create(label_driver="dymo")
        with mock.patch("requests.post") as post:
            ok, error = label_printing.print_label("Hello", "large")
        self.assertFalse(ok)
        self.assertIn("448", error)
        self.assertIn("Dymo", error)
        post.assert_not_called()

    @PRINTER_ON
    def test_the_widest_label_still_fits_the_printer_this_was_built_for(self):
        SiteSettings.objects.create(label_driver="zpl")
        with mock.patch("requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            ok, error = label_printing.print_label("Hello", "large")
        self.assertTrue(ok, error)
        post.assert_called_once()

    def test_an_unconfigured_printer_still_reports_rather_than_raising(self):
        with override_settings(LABEL_PRINTER_URL=""):
            ok, error = label_printing.print_label("Hello", "large")
        self.assertFalse(ok)
        self.assertIn("No label printer configured", error)


class BridgeRoutingTests(TestCase):
    """The Pi side. Loaded as a module, so its decisions are tested off the Pi."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bridge = load_pi_bridge()

    def test_printer_bytes_go_straight_to_the_device(self):
        for content_type in ("application/x-zpl", "application/vnd.brother-ql", "application/vnd.dymo-labelwriter"):
            with self.subTest(content_type=content_type):
                self.assertEqual(self.bridge.route_for(content_type), "raw")

    def test_an_image_goes_to_cups_instead(self):
        self.assertEqual(self.bridge.route_for("image/png"), "cups")

    def test_a_content_type_with_parameters_still_routes(self):
        self.assertEqual(self.bridge.route_for("image/png; charset=binary"), "cups")

    def test_something_it_cannot_print_is_refused_rather_than_guessed_at(self):
        """Writing a JPEG to a raw printer device prints pages of binary noise, at the
        printer, wherever the printer is."""
        for content_type in ("image/jpeg", "application/pdf", "text/html"):
            with self.subTest(content_type=content_type):
                self.assertIsNone(self.bridge.route_for(content_type))

    def test_an_older_app_sending_no_content_type_still_prints(self):
        """The bridge predates content types; a raw write is what it always did."""
        self.assertEqual(self.bridge.route_for(None), "raw")
        self.assertEqual(self.bridge.route_for(""), "raw")

    def test_the_bridge_accepts_every_printer_type_the_app_offers(self):
        """Agreement between two files that are deployed separately -- the app on a
        server, this on a Pi that only gets updated by hand. Drift here looks like
        "nothing prints"."""
        app_types = {driver.content_type for driver in DRIVERS.values()}
        accepted = set(self.bridge.RAW_CONTENT_TYPES) | {self.bridge.CUPS_CONTENT_TYPE}
        self.assertEqual(app_types - accepted, set())

    @mock.patch("shutil.which", return_value=None)
    def test_cups_missing_is_explained_not_crashed(self, _which):
        ok, detail = self.bridge._spool_to_cups(b"not really a png")
        self.assertFalse(ok)
        self.assertIn("CUPS isn't installed", detail)

    @staticmethod
    def fake_lp(returncode=0, stderr=""):
        """Stands in for the `lp` command.

        The bridge runs it through `_run_lp`, which is the seam here: the real thing
        needs a printer and a CUPS install, and this asserts on the command it would
        have run instead.
        """
        result = mock.Mock(returncode=returncode, stdout="", stderr=stderr)
        return mock.Mock(return_value=result)

    @mock.patch("shutil.which", return_value="/usr/bin/lp")
    def test_the_image_is_spooled_as_a_file_and_the_file_is_cleaned_up(self, _which):
        runner = self.fake_lp()
        with mock.patch.object(self.bridge, "_run_lp", runner):
            ok, detail = self.bridge._spool_to_cups(b"\x89PNG\r\n\x1a\nfake")
        self.assertTrue(ok, detail)
        command = runner.call_args.args[0]
        self.assertEqual(command[0], "lp")
        self.assertTrue(command[-1].endswith(".png"))
        self.assertFalse(os.path.exists(command[-1]), "a failed job must not leave files behind either")

    @mock.patch("shutil.which", return_value="/usr/bin/lp")
    def test_a_named_queue_is_used_when_one_is_configured(self, _which):
        runner = self.fake_lp()
        with mock.patch.object(self.bridge, "_run_lp", runner):
            with mock.patch.object(self.bridge, "CUPS_QUEUE", "workshop"):
                ok, _detail = self.bridge._spool_to_cups(b"\x89PNG\r\n\x1a\nfake")
        self.assertTrue(ok)
        self.assertEqual(runner.call_args.args[0][:3], ["lp", "-d", "workshop"])

    @mock.patch("shutil.which", return_value="/usr/bin/lp")
    def test_cups_refusing_the_job_is_reported_with_its_own_message(self, _which):
        runner = self.fake_lp(returncode=1, stderr="lp: Destination 'gone' does not exist.")
        with mock.patch.object(self.bridge, "_run_lp", runner):
            ok, detail = self.bridge._spool_to_cups(b"\x89PNG\r\n\x1a\nfake")
        self.assertFalse(ok)
        self.assertIn("does not exist", detail)
