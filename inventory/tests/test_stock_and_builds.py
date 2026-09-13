"""Stock arithmetic -- FIFO consumption, build-time deduction, reorder maths.

`_consume_stock` mutates real stock rows, so it is the highest-consequence
logic in the app: a bug here silently writes off inventory. It is also the
exact behaviour the HANDOFF describes as "FIFO-consumes real stock", so these
tests pin the ordering and the short-stock accounting.
"""
from django.test import TestCase
from django.urls import reverse

from inventory.models import Build, BuildConsumption, StockItem
from inventory.views import _consume_stock, _current_stock, _reorder_link

from .factories import make_container, make_drawer, make_part, make_project_with_bom, make_stock, make_user


class ConsumeStockTests(TestCase):
    def setUp(self):
        self.container = make_container(number=1)
        self.part = make_part()

    def test_consumes_oldest_stock_item_first(self):
        first = make_stock(self.part, self.container, quantity=5)
        second = make_stock(self.part, self.container, quantity=5)

        consumed = _consume_stock(self.part, 3)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(consumed, 3)
        self.assertEqual(first.quantity, 2)   # oldest drawn down
        self.assertEqual(second.quantity, 5)  # newer untouched

    def test_spills_over_into_the_next_stock_item(self):
        first = make_stock(self.part, self.container, quantity=2)
        second = make_stock(self.part, self.container, quantity=4)

        consumed = _consume_stock(self.part, 5)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(consumed, 5)
        self.assertEqual(first.quantity, 0)
        self.assertEqual(second.quantity, 1)

    def test_consumes_exactly_when_stock_is_exact(self):
        item = make_stock(self.part, self.container, quantity=4)
        self.assertEqual(_consume_stock(self.part, 4), 4)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 0)

    def test_returns_less_than_requested_when_stock_is_short(self):
        item = make_stock(self.part, self.container, quantity=2)
        consumed = _consume_stock(self.part, 10)
        item.refresh_from_db()
        self.assertEqual(consumed, 2)
        self.assertEqual(item.quantity, 0)

    def test_requesting_zero_consumes_nothing(self):
        item = make_stock(self.part, self.container, quantity=5)
        self.assertEqual(_consume_stock(self.part, 0), 0)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 5)

    def test_free_text_quantities_are_never_decremented(self):
        """StockItems with quantity=None come from spreadsheet free text like
        '10 aprox' and cannot be reliably decremented -- they must be skipped
        entirely rather than treated as zero or None-crashed."""
        vague = make_stock(self.part, self.container, quantity=None, quantity_raw="10 aprox")
        real = make_stock(self.part, self.container, quantity=3)

        consumed = _consume_stock(self.part, 3)

        vague.refresh_from_db()
        real.refresh_from_db()
        self.assertEqual(consumed, 3)
        self.assertIsNone(vague.quantity)
        self.assertEqual(real.quantity, 0)

    def test_already_empty_stock_items_are_skipped(self):
        empty = make_stock(self.part, self.container, quantity=0)
        full = make_stock(self.part, self.container, quantity=2)

        self.assertEqual(_consume_stock(self.part, 2), 2)
        empty.refresh_from_db()
        self.assertEqual(empty.quantity, 0)

    def test_other_parts_are_untouched(self):
        other = make_part(name="Something else")
        other_item = make_stock(other, self.container, quantity=9)
        make_stock(self.part, self.container, quantity=1)

        _consume_stock(self.part, 1)

        other_item.refresh_from_db()
        self.assertEqual(other_item.quantity, 9)


class CurrentStockTests(TestCase):
    def test_sums_across_all_locations(self):
        part = make_part()
        make_stock(part, make_container(number=1), quantity=3)
        make_stock(part, make_container(number=2), quantity=4)
        self.assertEqual(_current_stock(part), 7)

    def test_ignores_unparseable_quantities(self):
        part = make_part()
        make_stock(part, make_container(number=1), quantity=3)
        make_stock(part, make_container(number=2), quantity=None, quantity_raw="some")
        self.assertEqual(_current_stock(part), 3)

    def test_is_zero_with_no_stock(self):
        self.assertEqual(_current_stock(make_part()), 0)


class ReorderLinkTests(TestCase):
    def test_uses_the_stored_reorder_url_when_present(self):
        part = make_part(reorder_url="https://example.com/buy")
        self.assertEqual(_reorder_link(part), "https://example.com/buy")

    def test_falls_back_to_a_google_search_on_the_name(self):
        part = make_part(name="Resistor 10k")
        self.assertIn("google.com/search", _reorder_link(part))
        self.assertIn("Resistor", _reorder_link(part))


class BuildProjectTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.container = make_container(number=1)

    def test_build_deducts_the_bom_quantity_times_units_built(self):
        part = make_part(name="LED")
        stock = make_stock(part, self.container, quantity=10)
        project, _ = make_project_with_bom(name="Blinky", lines=[(part, 2)])

        self.client.post(reverse("inventory:build_project", args=[project.pk]), {"quantity_built": 3})

        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 4)  # 10 - (2 * 3)

    def test_build_records_a_consumption_row_per_bom_line(self):
        part = make_part(name="LED")
        make_stock(part, self.container, quantity=10)
        project, _ = make_project_with_bom(name="Blinky", lines=[(part, 2)])

        self.client.post(reverse("inventory:build_project", args=[project.pk]), {"quantity_built": 1})

        build = Build.objects.get(project=project)
        self.assertEqual(build.quantity_built, 1)
        consumption = BuildConsumption.objects.get(build=build, part=part)
        self.assertEqual(consumption.quantity_requested, 2)
        self.assertEqual(consumption.quantity_consumed, 2)
        self.assertFalse(consumption.short)

    def test_short_stock_is_recorded_honestly_and_flagged(self):
        """The build still happens; what actually came out of stock is recorded
        rather than the number that was wanted."""
        part = make_part(name="LED")
        stock = make_stock(part, self.container, quantity=3)
        project, _ = make_project_with_bom(name="Blinky", lines=[(part, 2)])

        self.client.post(reverse("inventory:build_project", args=[project.pk]), {"quantity_built": 5})

        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 0)
        consumption = BuildConsumption.objects.get(part=part)
        self.assertEqual(consumption.quantity_requested, 10)
        self.assertEqual(consumption.quantity_consumed, 3)
        self.assertTrue(consumption.short)

    def test_builds_against_the_latest_revision(self):
        part = make_part(name="LED")
        make_stock(part, self.container, quantity=100)
        project, first = make_project_with_bom(name="Blinky", lines=[(part, 1)])

        from inventory.models import BOMLine, BOMRevision

        second = BOMRevision.objects.create(project=project)
        BOMLine.objects.create(revision=second, part=part, quantity_required=7)

        self.client.post(reverse("inventory:build_project", args=[project.pk]), {"quantity_built": 1})

        self.assertEqual(Build.objects.get(project=project).revision, second)

    def test_non_post_does_not_build(self):
        part = make_part(name="LED")
        stock = make_stock(part, self.container, quantity=10)
        project, _ = make_project_with_bom(name="Blinky", lines=[(part, 2)])

        self.client.get(reverse("inventory:build_project", args=[project.pk]))

        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 10)
        self.assertEqual(Build.objects.count(), 0)

    def test_project_without_a_revision_does_not_build(self):
        from inventory.models import Project

        project = Project.objects.create(name="Empty")
        self.client.post(reverse("inventory:build_project", args=[project.pk]), {"quantity_built": 1})
        self.assertEqual(Build.objects.count(), 0)

    def test_nonsense_quantity_built_falls_back_to_one(self):
        part = make_part(name="LED")
        stock = make_stock(part, self.container, quantity=10)
        project, _ = make_project_with_bom(name="Blinky", lines=[(part, 2)])

        self.client.post(reverse("inventory:build_project", args=[project.pk]), {"quantity_built": "banana"})

        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 8)
        self.assertEqual(Build.objects.get(project=project).quantity_built, 1)

    def test_zero_or_negative_quantity_built_is_clamped_to_one(self):
        part = make_part(name="LED")
        stock = make_stock(part, self.container, quantity=10)
        project, _ = make_project_with_bom(name="Blinky", lines=[(part, 2)])

        self.client.post(reverse("inventory:build_project", args=[project.pk]), {"quantity_built": 0})

        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 8)


class ReorderDashboardTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.container = make_container(number=1)

    def test_lists_only_parts_at_or_below_their_threshold(self):
        low = make_part(name="Low part", min_quantity=10)
        make_stock(low, self.container, quantity=2)
        fine = make_part(name="Fine part", min_quantity=10)
        make_stock(fine, self.container, quantity=50)

        resp = self.client.get(reverse("inventory:reorder"))

        names = [row["part"].name for row in resp.context["needs_reorder"]]
        self.assertIn("Low part", names)
        self.assertNotIn("Fine part", names)

    def test_exactly_at_threshold_is_not_flagged(self):
        """The comparison is `have < min_quantity`, so hitting the threshold
        exactly means no reorder is needed."""
        part = make_part(name="Exact", min_quantity=10)
        make_stock(part, self.container, quantity=10)

        resp = self.client.get(reverse("inventory:reorder"))
        self.assertEqual(resp.context["needs_reorder"], [])

    def test_parts_without_a_threshold_are_ignored(self):
        part = make_part(name="No threshold")
        make_stock(part, self.container, quantity=0)

        resp = self.client.get(reverse("inventory:reorder"))
        self.assertEqual(resp.context["needs_reorder"], [])

    def test_a_part_with_no_stock_at_all_is_low(self):
        part = make_part(name="Ghost", min_quantity=1)
        resp = self.client.get(reverse("inventory:reorder"))
        self.assertIn("Ghost", [row["part"].name for row in resp.context["needs_reorder"]])


class UpdateStockQuantityTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.part = make_part()
        self.stock = make_stock(self.part, make_container(number=1), quantity=5)

    def test_quantity_can_be_set(self):
        self.client.post(reverse("inventory:update_stock_quantity", args=[self.stock.pk]), {"quantity": "12"})
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 12)

    def test_quantity_can_be_cleared_to_unknown(self):
        """NOTE / judgement call, pinned as-is rather than "fixed": blank is
        currently REJECTED (int("") raises ValueError) so the old value survives,
        whereas update_stock_bin DOES clear on blank. That asymmetry is
        inconsistent, but it is the shipped behaviour and changing it would alter
        production data handling -- flagged to Seth rather than silently altered.
        """
        self.client.post(reverse("inventory:update_stock_quantity", args=[self.stock.pk]), {"quantity": ""})
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 5)

    def test_non_numeric_quantity_is_rejected_and_leaves_the_value_alone(self):
        """Asserts on a fragment without the apostrophe -- the rendered message is
        HTML-escaped (&#x27;lots&#x27; isn&#x27;t...)."""
        resp = self.client.post(
            reverse("inventory:update_stock_quantity", args=[self.stock.pk]), {"quantity": "lots"}, follow=True
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 5)
        self.assertContains(resp, "t a whole number")

    def test_negative_quantity_is_clamped_to_zero(self):
        self.client.post(reverse("inventory:update_stock_quantity", args=[self.stock.pk]), {"quantity": "-5"})
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 0)

    def test_quantity_raw_is_kept_in_step_with_the_quantity(self):
        self.client.post(reverse("inventory:update_stock_quantity", args=[self.stock.pk]), {"quantity": "9"})
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_raw, "9")

    def test_bin_number_out_of_range_is_rejected(self):
        url = reverse("inventory:update_stock_bin", args=[self.stock.pk])
        for bad in ("0", "17", "-1"):
            self.client.post(url, {"bin_number": bad})
            self.stock.refresh_from_db()
            self.assertIsNone(self.stock.bin_number, f"bin_number={bad} should have been refused")

    def test_bin_number_can_be_set_and_cleared(self):
        url = reverse("inventory:update_stock_bin", args=[self.stock.pk])
        self.client.post(url, {"bin_number": "7"})
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.bin_number, 7)

        self.client.post(url, {"bin_number": ""})
        self.stock.refresh_from_db()
        self.assertIsNone(self.stock.bin_number)
