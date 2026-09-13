"""Model-level invariants.

These cover the bits of model behaviour other code silently depends on --
derived fields that must be populated on save, version numbering the BOM
feature builds on, and the bin row/column arithmetic the LED readout and the
bin-scan flow both rely on.
"""
from django.test import TestCase

from inventory.models import BOMRevision, BuildConsumption, Drawer, Part, Project, StockItem

from .factories import make_container, make_drawer, make_part, make_project_with_bom, make_stock


class PartNormalizationTests(TestCase):
    def test_normalized_name_is_populated_on_save(self):
        part = Part.objects.create(name="  Resistor 10k  ")
        self.assertEqual(part.normalized_name, "resistor 10k")

    def test_normalized_name_follows_a_rename(self):
        part = make_part(name="Original")
        part.name = "Renamed Thing"
        part.save()
        part.refresh_from_db()
        self.assertEqual(part.normalized_name, "renamed thing")


class BOMRevisionVersionTests(TestCase):
    def test_first_revision_is_version_one(self):
        project = Project.objects.create(name="P")
        rev = BOMRevision.objects.create(project=project)
        self.assertEqual(rev.version, 1)

    def test_versions_increment_per_project_independently(self):
        a = Project.objects.create(name="A")
        b = Project.objects.create(name="B")
        BOMRevision.objects.create(project=a)
        BOMRevision.objects.create(project=b)
        second_a = BOMRevision.objects.create(project=a)

        self.assertEqual(second_a.version, 2)
        self.assertEqual(BOMRevision.objects.filter(project=b).get().version, 1)

    def test_latest_revision_is_the_highest_version(self):
        project, first = make_project_with_bom()
        second = BOMRevision.objects.create(project=project)
        self.assertEqual(project.latest_revision, second)
        self.assertNotEqual(project.latest_revision, first)


class BinArithmeticTests(TestCase):
    """bin_number is 1-16 laid out as 4 rows of 4. The LED row readout and the
    bin-scan labels both compute row/column from it, so the boundaries matter."""

    def test_bin_row_and_column_for_all_sixteen_positions(self):
        container = make_container(number=38)
        drawer = make_drawer(container)
        expected = {
            1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (1, 4),
            5: (2, 1), 6: (2, 2), 7: (2, 3), 8: (2, 4),
            9: (3, 1), 10: (3, 2), 11: (3, 3), 12: (3, 4),
            13: (4, 1), 14: (4, 2), 15: (4, 3), 16: (4, 4),
        }
        from inventory.models import Bin

        for n, (row, col) in expected.items():
            b = Bin(drawer=drawer, bin_number=n)
            self.assertEqual((b.bin_row, b.bin_column), (row, col), f"bin {n}")

    def test_stock_item_bin_row_column_match_bin(self):
        container = make_container(number=38)
        drawer = make_drawer(container)
        part = make_part()
        si = make_stock(part, container, drawer=drawer, quantity=1, bin_number=7)
        self.assertEqual((si.bin_row, si.bin_column), (2, 3))

    def test_stock_item_bin_row_column_are_none_when_unset(self):
        container = make_container(number=38)
        drawer = make_drawer(container)
        si = make_stock(make_part(), container, drawer=drawer, quantity=1)
        self.assertIsNone(si.bin_row)
        self.assertIsNone(si.bin_column)


class BuildConsumptionTests(TestCase):
    def test_short_is_true_only_when_less_was_consumed(self):
        project, revision = make_project_with_bom(lines=[(make_part(), 2)])
        from inventory.models import Build

        build = Build.objects.create(project=project, revision=revision, quantity_built=1)
        exact = BuildConsumption.objects.create(build=build, part=make_part("A"), quantity_requested=3, quantity_consumed=3)
        short = BuildConsumption.objects.create(build=build, part=make_part("B"), quantity_requested=3, quantity_consumed=1)
        over = BuildConsumption.objects.create(build=build, part=make_part("C"), quantity_requested=3, quantity_consumed=4)

        self.assertFalse(exact.short)
        self.assertTrue(short.short)
        self.assertFalse(over.short)


class StringRepresentationTests(TestCase):
    """These strings are rendered straight into templates and the LED/serial
    error messages, so a silent change in format would be user-visible."""

    def test_container_and_drawer_str(self):
        container = make_container(number=38, container_type="cabinets", name="Cabinet 1")
        drawer = make_drawer(container, label="drawer 5")
        self.assertEqual(str(container), "#38 (Cabinet 1)")
        self.assertEqual(str(drawer), "#38 (Cabinet 1) / drawer 5")

    def test_container_falls_back_to_type_when_unnamed(self):
        self.assertEqual(str(make_container(number=7, container_type="black tote")), "#7 (black tote)")

    def test_drawer_led_segment_str_shows_the_index_range(self):
        from inventory.models import DrawerLedSegment

        drawer = make_drawer(make_container(number=38))
        seg = DrawerLedSegment.objects.create(drawer=drawer, led_strip="cabinet1-left", led_start_index=20, led_count=10)
        self.assertIn("cabinet1-left[20:30]", str(seg))
