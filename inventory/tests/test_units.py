"""Measurement units.

The load-bearing property is the boring one: a quantity with no unit must render
exactly as it did before units existed. Every existing row in Seth's database is
unitless, so a regression here would put "each" or a stray symbol on 1,379 stock
lines overnight.
"""
from django.test import SimpleTestCase, TestCase

from inventory.units import (
    DEFAULT_UNIT,
    IMPERIAL_UNITS,
    METRIC_UNITS,
    UNIT_CHOICES,
    UNITS,
    format_quantity,
    is_known,
    label,
    symbol,
    units_for_system,
)


class SymbolTests(SimpleTestCase):
    def test_each_has_no_symbol(self):
        """Deliberate: '5' reads better than '5 ea' everywhere the app already
        shows a quantity, so the common case stays visually unchanged."""
        self.assertEqual(symbol("ea"), "")

    def test_real_units_have_short_symbols(self):
        for code, expected in [("m", "m"), ("ft", "ft"), ("g", "g"), ("ml", "ml")]:
            with self.subTest(unit=code):
                self.assertEqual(symbol(code), expected)

    def test_an_unknown_unit_falls_back_to_each(self):
        for bad in ("", None, "furlong", "EA"):
            with self.subTest(unit=bad):
                self.assertEqual(symbol(bad), "")


class LabelTests(SimpleTestCase):
    def test_singular_for_one(self):
        self.assertEqual(label("m", 1), "metre")

    def test_plural_for_more_than_one(self):
        self.assertEqual(label("m", 5), "metres")
        self.assertEqual(label("m", 0), "metres")

    def test_plural_when_no_quantity_is_given(self):
        self.assertEqual(label("m"), "metres")

    def test_irregular_plurals(self):
        self.assertEqual(label("ft", 1), "foot")
        self.assertEqual(label("ft", 2), "feet")


class FormatQuantityTests(SimpleTestCase):
    def test_a_plain_count_has_no_suffix(self):
        self.assertEqual(format_quantity(5, "ea"), "5")

    def test_a_measured_quantity_carries_its_symbol(self):
        self.assertEqual(format_quantity(5, "m"), "5 m")
        self.assertEqual(format_quantity(1, "ft"), "1 ft")

    def test_zero_is_shown_as_zero_not_as_missing(self):
        """Zero stock is a real, useful answer and must not read as 'unknown'."""
        self.assertEqual(format_quantity(0, "ea"), "0")

    def test_none_reads_as_unknown(self):
        """This app distinguishes 'no quantity recorded' from zero — the spreadsheet
        had values like '10 aprox' that never became a number."""
        self.assertEqual(format_quantity(None, "ea"), "unknown")

    def test_empty_string_reads_as_unknown(self):
        self.assertEqual(format_quantity("", "ea"), "unknown")

    def test_a_unitless_quantity_is_just_the_number(self):
        self.assertEqual(format_quantity(12), "12")


class UnitSystemTests(SimpleTestCase):
    def test_metric_is_offered_first_for_a_metric_install(self):
        ordered = units_for_system("metric")
        self.assertEqual(ordered[0], "ea")
        self.assertLess(ordered.index("m"), ordered.index("ft"))

    def test_imperial_is_offered_first_for_an_imperial_install(self):
        ordered = units_for_system("imperial")
        self.assertEqual(ordered[0], "ea")
        self.assertLess(ordered.index("ft"), ordered.index("m"))

    def test_every_unit_stays_selectable_in_both_systems(self):
        """A UK workshop buying from US suppliers genuinely has both, so ordering
        is a preference and never a filter."""
        for system in ("metric", "imperial"):
            with self.subTest(system=system):
                offered = set(units_for_system(system))
                self.assertEqual(offered, set(METRIC_UNITS) | set(IMPERIAL_UNITS))

    def test_an_unknown_system_falls_back_to_metric(self):
        self.assertEqual(units_for_system("martian"), units_for_system("metric"))


class UnitTableTests(SimpleTestCase):
    def test_every_choice_is_well_formed(self):
        for code, names in UNIT_CHOICES:
            with self.subTest(unit=code):
                self.assertEqual(len(names), 3, f"{code} needs (singular, plural, symbol)")
                self.assertTrue(code)
                self.assertTrue(names[1])

    def test_codes_are_unique(self):
        codes = [code for code, _ in UNIT_CHOICES]
        self.assertEqual(len(codes), len(set(codes)))

    def test_each_is_the_default(self):
        self.assertEqual(DEFAULT_UNIT, "ea")

    def test_short_codes_are_friendly_to_narrow_columns(self):
        """These go in a CharField(max_length=8) and on printed labels."""
        for code in UNITS:
            with self.subTest(unit=code):
                self.assertLessEqual(len(code), 8)

    def test_is_known_rejects_junk(self):
        self.assertTrue(is_known("m"))
        self.assertFalse(is_known("furlong"))
        self.assertFalse(is_known(""))
        self.assertFalse(is_known(None))


class StockItemUnitTests(TestCase):
    """Inheritance, which is what keeps existing data unchanged."""

    def setUp(self):
        from .factories import make_container, make_drawer, make_part

        self.container = make_container()
        self.drawer = make_drawer(self.container)
        self.part = make_part(name="Hook-up wire")

    def stock(self, **kwargs):
        from .factories import make_stock

        return make_stock(self.part, self.container, drawer=self.drawer, **kwargs)

    def test_a_part_defaults_to_each(self):
        self.assertEqual(self.part.default_unit, "ea")

    def test_a_stock_row_with_no_unit_inherits_each(self):
        self.assertEqual(self.stock(quantity=10).effective_unit, "ea")

    def test_a_stock_row_inherits_the_part_unit(self):
        self.part.default_unit = "m"
        self.part.save()
        self.assertEqual(self.stock(quantity=5).effective_unit, "m")

    def test_a_stock_row_can_override_the_part(self):
        """One shelf can hold a part counted individually while another holds it by
        length — the same part is not always stored the same way everywhere."""
        self.part.default_unit = "m"
        self.part.save()
        self.assertEqual(self.stock(quantity=5, unit="ea").effective_unit, "ea")

    def test_an_existing_style_row_displays_exactly_as_before(self):
        """The regression that matters: 1,379 rows in production have no unit, and
        they must keep reading as plain numbers."""
        self.assertEqual(self.stock(quantity=42).quantity_display, "42")

    def test_a_measured_row_displays_with_its_symbol(self):
        self.part.default_unit = "m"
        self.part.save()
        self.assertEqual(self.stock(quantity=5).quantity_display, "5 m")

    def test_unknown_quantity_still_reads_as_unknown(self):
        self.assertEqual(self.stock(quantity=None).quantity_display, "unknown")
