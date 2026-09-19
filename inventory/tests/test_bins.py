"""Bin / sub-bin behaviour -- seeding, the rapid bulk-scan flow, and conflicts.

A drawer's bin_count decides whether it has bins and how many (0 = none, default
16, up to 100). The idempotency of seeding is load-bearing: the seeding helper is
called on ordinary page loads.
"""
import json

from django.test import TestCase
from django.urls import reverse

from inventory.models import Bin, Container, SubBin
from inventory.views import _ensure_bins_for_drawer, _ensure_bins_seeded, _drawer_number

from .factories import make_bin, make_container, make_drawer, make_user


class BinEligibilityTests(TestCase):
    def test_sixteen_bins_is_the_default(self):
        from inventory.views import BINS_PER_DRAWER

        self.assertEqual(BINS_PER_DRAWER, 16)

    def test_a_drawer_defaults_to_sixteen_bins(self):
        drawer = make_drawer(make_container(number=38), label="drawer 1")
        self.assertEqual(drawer.bin_count, 16)


class BinsSeedingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cabinet = make_container(number=38, container_type="cabinets")
        cls.drawer = make_drawer(cls.cabinet, label="drawer 1")
        cls.tote = make_container(number=5, container_type="black tote")
        cls.tote_drawer = make_drawer(cls.tote, label="drawer 99", bin_count=0)

    def test_seeding_creates_sixteen_bins_on_an_eligible_drawer(self):
        _ensure_bins_seeded()
        self.assertEqual(self.drawer.bins.count(), 16)
        self.assertEqual(
            sorted(self.drawer.bins.values_list("bin_number", flat=True)), list(range(1, 17))
        )

    def test_seeding_leaves_ineligible_drawers_alone(self):
        """Cabinet 4 and the totes have no bin subdivision by design."""
        _ensure_bins_seeded()
        self.assertEqual(self.tote_drawer.bins.count(), 0)

    def test_seeding_is_idempotent(self):
        """This runs on ordinary page loads, so a second call must not
        duplicate rows or blow up on the unique_together constraint."""
        _ensure_bins_seeded()
        _ensure_bins_seeded()
        _ensure_bins_seeded()
        self.assertEqual(self.drawer.bins.count(), 16)

    def test_seeding_adds_only_the_missing_bins(self):
        """Half-scanned drawers must not be reset by a later seed."""
        existing = make_bin(self.drawer, bin_number=1, barcode_id="ALREADY")
        _ensure_bins_seeded()

        self.assertEqual(self.drawer.bins.count(), 16)
        existing.refresh_from_db()
        self.assertEqual(existing.barcode_id, "ALREADY")

    def test_per_drawer_helper_reports_eligibility(self):
        self.assertTrue(_ensure_bins_for_drawer(self.drawer))
        self.assertFalse(_ensure_bins_for_drawer(self.tote_drawer))
        self.assertEqual(self.drawer.bins.count(), 16)
        self.assertEqual(self.tote_drawer.bins.count(), 0)

    def test_per_drawer_helper_is_idempotent(self):
        _ensure_bins_for_drawer(self.drawer)
        _ensure_bins_for_drawer(self.drawer)
        self.assertEqual(self.drawer.bins.count(), 16)


class DrawerNumberSortTests(TestCase):
    """Drawer labels are free text ('drawer 5', 'drawer b2'), and browsing sorts
    by the numeric part so drawings appear in physical order rather than
    lexicographically ('drawer 10' before 'drawer 2')."""

    def test_extracts_the_first_number_from_the_label(self):
        container = make_container(number=38)
        self.assertEqual(_drawer_number(make_drawer(container, label="drawer 12")), 12)
        self.assertEqual(_drawer_number(make_drawer(container, label="Drawer 3")), 3)

    def test_label_with_no_digits_sorts_first(self):
        container = make_container(number=38)
        self.assertEqual(_drawer_number(make_drawer(container, label="unnumbered")), 0)

    def test_sorting_is_numeric_not_lexicographic(self):
        container = make_container(number=38)
        labels = ["drawer 10", "drawer 2", "drawer 1"]
        drawers = [make_drawer(container, label=lab) for lab in labels]
        drawers.sort(key=_drawer_number)
        self.assertEqual([d.label for d in drawers], ["drawer 1", "drawer 2", "drawer 10"])


class BinScanApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.cabinet = make_container(number=38, container_type="cabinets")
        cls.drawer = make_drawer(cls.cabinet, label="drawer 1")
        cls.bin = make_bin(cls.drawer, bin_number=1)

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("inventory:api_scan_bin", args=[self.bin.pk])

    def post_json(self, payload):
        return self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

    def test_scanning_a_free_bin_links_the_code(self):
        resp = self.post_json({"code": "BIN-A-1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})
        self.bin.refresh_from_db()
        self.assertEqual(self.bin.barcode_id, "BIN-A-1")

    def test_rescanning_the_same_bin_with_a_new_code_is_allowed(self):
        """Re-sticking a damaged label is a normal thing to need to do."""
        self.bin.barcode_id = "OLD"
        self.bin.save()
        resp = self.post_json({"code": "NEW"})
        self.assertEqual(resp.status_code, 200)
        self.bin.refresh_from_db()
        self.assertEqual(self.bin.barcode_id, "NEW")

    def test_a_code_already_on_another_bin_is_rejected_with_409(self):
        other = make_bin(self.drawer, bin_number=2, barcode_id="TAKEN")
        resp = self.post_json({"code": "TAKEN"})

        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIn("already linked", body["error"])
        # And crucially the target bin was not silently overwritten.
        self.bin.refresh_from_db()
        self.assertIsNone(self.bin.barcode_id)

    def test_the_conflict_message_names_where_the_code_already_lives(self):
        make_bin(self.drawer, bin_number=2, barcode_id="TAKEN")
        resp = self.post_json({"code": "TAKEN"})
        self.assertIn("bin 2", resp.json()["error"])

    def test_blank_code_is_rejected_with_400(self):
        resp = self.post_json({"code": "   "})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "no code given")

    def test_malformed_json_is_rejected_with_400(self):
        resp = self.client.post(self.url, data="{not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid json")

    def test_code_is_stripped_before_storing(self):
        self.post_json({"code": "  PADDED  "})
        self.bin.refresh_from_db()
        self.assertEqual(self.bin.barcode_id, "PADDED")


class BinSetupPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.cabinet = make_container(number=38, container_type="cabinets")
        cls.drawer = make_drawer(cls.cabinet, label="drawer 1")

    def setUp(self):
        self.client.force_login(self.user)

    def test_setup_page_seeds_and_reports_progress(self):
        resp = self.client.get(reverse("inventory:bin_setup"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_bins"], 16)
        self.assertEqual(resp.context["total_done"], 0)

    def test_progress_counts_scanned_bins(self):
        _ensure_bins_seeded()
        first, second = self.drawer.bins.order_by("bin_number")[:2]
        first.barcode_id = "SCAN-1"
        first.save(update_fields=["barcode_id"])
        second.barcode_id = "SCAN-2"
        second.save(update_fields=["barcode_id"])

        resp = self.client.get(reverse("inventory:bin_setup"))
        self.assertEqual(resp.context["total_done"], 2)

    def test_progress_points_at_the_first_unscanned_bin(self):
        _ensure_bins_seeded()
        first = self.drawer.bins.order_by("bin_number").first()
        first.barcode_id = "SCAN-1"
        first.save(update_fields=["barcode_id"])

        resp = self.client.get(reverse("inventory:bin_setup"))
        row = next(r for r in resp.context["rows"] if r["drawer"] == self.drawer)
        self.assertEqual(row["start_bin"].bin_number, 2)

    def test_scan_page_offers_every_position(self):
        resp = self.client.get(reverse("inventory:bin_scan"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["positions_json"]), 16)

    def test_scan_page_can_resume_at_a_given_bin(self):
        _ensure_bins_seeded()
        target = self.drawer.bins.order_by("bin_number")[5]
        resp = self.client.get(reverse("inventory:bin_scan"), {"start": target.pk})
        self.assertEqual(resp.context["start_index"], 5)

    def test_unknown_resume_pk_falls_back_to_the_start(self):
        resp = self.client.get(reverse("inventory:bin_scan"), {"start": 999999})
        self.assertEqual(resp.context["start_index"], 0)


class BinDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.cabinet = make_container(number=38, container_type="cabinets")
        cls.drawer = make_drawer(cls.cabinet, label="drawer 1")

    def setUp(self):
        self.client.force_login(self.user)

    def test_bin_detail_shows_only_stock_in_that_bin(self):
        from .factories import make_part, make_stock

        b7 = make_bin(self.drawer, bin_number=7)
        here = make_stock(make_part(name="In this bin"), self.cabinet, drawer=self.drawer, quantity=1, bin_number=7)
        make_stock(make_part(name="Other bin"), self.cabinet, drawer=self.drawer, quantity=1, bin_number=8)

        resp = self.client.get(reverse("inventory:bin_detail", args=[b7.pk]))
        self.assertEqual(list(resp.context["stock_items"]), [here])

    def test_sub_bins_can_be_added_up_to_four(self):
        b = make_bin(self.drawer, bin_number=1)
        url = reverse("inventory:add_sub_bin", args=[b.pk])

        for _ in range(4):
            self.client.post(url, {"size": SubBin.SMALL})
        self.assertEqual(b.sub_bins.count(), 4)

        # A fifth is refused rather than silently accepted.
        self.client.post(url, {"size": SubBin.SMALL})
        self.assertEqual(b.sub_bins.count(), 4)

    def test_sub_bin_positions_are_sequential(self):
        b = make_bin(self.drawer, bin_number=1)
        url = reverse("inventory:add_sub_bin", args=[b.pk])
        self.client.post(url, {"size": SubBin.SMALL})
        self.client.post(url, {"size": SubBin.MEDIUM})

        self.assertEqual(list(b.sub_bins.values_list("size", flat=True)), [SubBin.SMALL, SubBin.MEDIUM])
