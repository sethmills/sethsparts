"""Printing the 4x4 bin-barcode grid sheet for a drawer."""
from django.test import TestCase
from django.urls import reverse

from ..models import Bin
from .factories import make_container, make_drawer, make_user


class BinGridPrintTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.container = make_container(number=38)  # one of the bin-eligible cabinets
        self.drawer = make_drawer(self.container, label="drawer b2")

    def test_grid_seeds_bins_and_assigns_barcodes(self):
        self.client.get(reverse("inventory:print_bin_grid", kwargs={"pk": self.drawer.pk}))
        bins = Bin.objects.filter(drawer=self.drawer)
        self.assertEqual(bins.count(), 16)
        for b in bins:
            self.assertTrue(b.barcode_id, f"bin {b.bin_number} has no barcode")
            self.assertTrue(b.barcode_id.endswith(f"-{b.bin_number:02d}"))

    def test_grid_page_renders(self):
        resp = self.client.get(reverse("inventory:print_bin_grid", kwargs={"pk": self.drawer.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bin 1")
        self.assertContains(resp, "Bin 16")

    def test_non_bin_drawer_is_redirected(self):
        drawer = make_drawer(make_container(number=119), label="drawer a")  # cabinet 4, no bins
        resp = self.client.get(reverse("inventory:print_bin_grid", kwargs={"pk": drawer.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Bin.objects.filter(drawer=drawer).count(), 0)
