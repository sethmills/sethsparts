"""Custom label rendering and the ZPL bridge.

Clever bit worth protecting: labels are rendered as a full bitmap with Pillow
(real TTFs, so genuine bold/italic) and packed into a single ZPL ^GFA graphic
field, rather than fighting ZPL's own font commands. That means the pixel maths
and the bit-packing are the parts most likely to break silently -- a wrong
stride still produces a syntactically valid ZPL string that just prints garbage.
"""
import io
from unittest import mock

from PIL import Image
from django.test import TestCase, override_settings

from inventory.label_drivers import zpl_graphic_field
from inventory.label_printing import (
    DPI,
    LABEL_SIZES,
    _wrap_text,
    print_label,
    render_label,
    render_label_png_bytes,
)

PRINTER_ON = override_settings(LABEL_PRINTER_URL="https://label.example.test", LABEL_PRINTER_KEY="secret")


class LabelSizeTests(TestCase):
    def test_the_three_sizes_seth_actually_owns(self):
        self.assertEqual(set(LABEL_SIZES), {"large", "tote", "barcode"})

    def test_dimensions_derive_from_the_physical_size_at_printer_dpi(self):
        for key, spec in LABEL_SIZES.items():
            image, w, h = render_label("HELLO", key)
            self.assertEqual(w, round(spec["width_in"] * DPI), key)
            self.assertEqual(h, round(spec["height_in"] * DPI), key)
            self.assertEqual(image.size, (w, h), key)

    def test_large_label_is_four_by_two_inches(self):
        _, w, h = render_label("HELLO", "large")
        self.assertEqual((w, h), (812, 406))


class RenderLabelTests(TestCase):
    def test_returns_a_one_bit_image(self):
        """ZPL ^GFA is a 1-bit format -- handing it greyscale would silently
        print a mess."""
        image, _, _ = render_label("Resistor 10k", "large")
        self.assertEqual(image.mode, "1")

    def test_empty_text_still_renders_a_valid_blank_label(self):
        image, w, h = render_label("", "tote")
        self.assertEqual(image.size, (w, h))

    def test_every_bold_italic_combination_renders(self):
        for bold in (False, True):
            for italic in (False, True):
                image, _, _ = render_label("Test", "large", bold=bold, italic=italic)
                self.assertEqual(image.mode, "1", f"bold={bold} italic={italic}")

    def test_a_barcode_composites_above_the_text(self):
        plain, _, _ = render_label("12345", "barcode")
        with_barcode, _, _ = render_label("12345", "barcode", barcode_value="C38")
        # The barcode version must contain ink the plain version doesn't.
        self.assertNotEqual(list(plain.getdata()), list(with_barcode.getdata()))

    def test_overlong_text_shrinks_to_fit_instead_of_overflowing(self):
        """The shrink-to-fit loop must terminate and still render. If it ever
        regressed to an infinite loop this test would hang rather than fail;
        the render() call is the assertion."""
        long_text = " ".join(["supercalifragilistic"] * 60)
        image, w, h = render_label(long_text, "barcode", font_pt=72)
        self.assertEqual(image.size, (w, h))
        self.assertEqual(image.mode, "1")

    def test_the_rendered_label_actually_contains_ink(self):
        image, _, _ = render_label("X", "large", font_pt=48)
        self.assertIn(0, set(image.getdata()), "a rendered label should have black pixels")

    def test_png_preview_round_trips(self):
        data = render_label_png_bytes("Preview me", "tote")
        img = Image.open(io.BytesIO(data))
        self.assertEqual(img.format, "PNG")

    def test_a_realistic_three_line_label_renders(self):
        image, _, _ = render_label("Container 1\nDrawer 5\nResistors", "large")
        self.assertIn(0, set(image.getdata()))


class WrapTextTests(TestCase):
    def setUp(self):
        from inventory.label_printing import _load_font

        self.image = Image.new("L", (400, 200), color=255)
        from PIL import ImageDraw

        self.draw = ImageDraw.Draw(self.image)
        self.font = _load_font(False, False, 24)

    def test_explicit_newlines_are_respected(self):
        lines = _wrap_text(self.draw, "one\ntwo\nthree", self.font, 400)
        self.assertEqual(lines, ["one", "two", "three"])

    def test_long_text_wraps_onto_multiple_lines(self):
        lines = _wrap_text(self.draw, "a b c d e f g h i j k l m n o p", self.font, 60)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(self.draw.textlength(line, font=self.font), 60)

    def test_a_single_word_too_long_for_the_width_is_kept_not_dropped(self):
        """It cannot be broken, so it must stay on its own line rather than
        vanish -- shrink-to-fit in render_label handles the overflow."""
        lines = _wrap_text(self.draw, "unbreakablewordthatisverylong", self.font, 20)
        self.assertEqual(lines, ["unbreakablewordthatisverylong"])

    def test_no_text_produces_one_empty_line(self):
        self.assertEqual(_wrap_text(self.draw, "", self.font, 400), [""])


class ZplGraphicFieldTests(TestCase):
    """The bit packing, which now lives in label_drivers with the other encoders."""
    def test_bit_packing_places_black_pixels_at_the_right_bits(self):
        """Concrete, hand-checkable case: a 16x2 image with one black pixel in
        the top-left and one in the bottom-right.

        Row stride is ceil(16/8) = 2 bytes, so 4 bytes total. ZPL's ^GFA sets
        bit 1 = print, most significant bit first.
        """
        image = Image.new("1", (16, 2), 1)
        image.putpixel((0, 0), 0)    # first byte, high bit   -> 0x80
        image.putpixel((15, 1), 0)   # last byte, low bit     -> 0x01

        zpl = zpl_graphic_field(image, 16, 2)

        self.assertIn("^GFA,4,4,2,80000001", zpl)

    def test_zpl_envelope_and_dimensions(self):
        image = Image.new("1", (16, 2), 1)
        zpl = zpl_graphic_field(image, 16, 2)

        self.assertTrue(zpl.startswith("^XA\n"))
        self.assertTrue(zpl.rstrip().endswith("^XZ"))
        self.assertIn("^PW16", zpl)
        self.assertIn("^LL2", zpl)

    def test_byte_counts_match_the_image_for_a_real_label(self):
        image, w, h = render_label("Hello", "large")
        zpl = zpl_graphic_field(image, w, h)

        bytes_per_row = (w + 7) // 8
        total = bytes_per_row * h
        self.assertIn(f"^GFA,{total},{total},{bytes_per_row},", zpl)

    def test_hex_payload_has_exactly_the_expected_length(self):
        image, w, h = render_label("Hello", "tote")
        zpl = zpl_graphic_field(image, w, h)

        payload = zpl.split("^GFA,")[1].split("^FS")[0].split(",")[3]
        bytes_per_row = (w + 7) // 8
        self.assertEqual(len(payload), bytes_per_row * h * 2)  # 2 hex chars per byte

    def test_a_blank_label_still_produces_a_well_formed_field(self):
        image = Image.new("1", (8, 1), 1)
        zpl = zpl_graphic_field(image, 8, 1)
        self.assertIn("^GFA,1,1,1,00", zpl)


class PrintLabelTests(TestCase):
    def test_unconfigured_printer_reports_rather_than_raising(self):
        with override_settings(LABEL_PRINTER_URL=""):
            ok, error = print_label("Hello", "large")
        self.assertFalse(ok)
        self.assertIn("No label printer configured", error)

    @PRINTER_ON
    @mock.patch("requests.post")
    def test_posts_zpl_bytes_to_the_bridge(self, post):
        post.return_value.raise_for_status.return_value = None

        ok, error = print_label("Hello", "large")

        self.assertTrue(ok)
        self.assertIsNone(error)
        call = post.call_args_list[0]
        self.assertEqual(call.args[0], "https://label.example.test/print")
        self.assertTrue(call.kwargs["data"].startswith(b"^XA"))
        self.assertEqual(call.kwargs["headers"]["X-Api-Key"], "secret")

    @PRINTER_ON
    @mock.patch("requests.post", side_effect=__import__("requests").ConnectionError("refused"))
    def test_an_unreachable_bridge_returns_the_error(self, post):
        ok, error = print_label("Hello", "large")
        self.assertFalse(ok)
        self.assertIn("refused", error)
