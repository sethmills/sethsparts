"""Barcode resolution -- the `go()` view every physical scan lands on.

Scanning is the primary way Seth interacts with the workshop, so the resolver's
order (container -> drawer -> bin -> sub-bin) and its fall-through to a
"not found" page are load-bearing.
"""
from django.test import TestCase
from django.urls import reverse

from inventory.models import Bin, Container, Drawer, SubBin

from .factories import make_bin, make_container, make_drawer, make_user


class ScanResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.container = make_container(number=38, container_type="cabinets")
        cls.drawer = make_drawer(cls.container, label="drawer 5")
        cls.bin = make_bin(cls.drawer, bin_number=7)
        cls.sub_bin = SubBin.objects.create(bin=cls.bin, position=1)

    def setUp(self):
        self.client.force_login(self.user)

    def test_container_code_redirects_to_the_container(self):
        self.container.barcode_id = "C38"
        self.container.save()
        resp = self.client.get(reverse("inventory:go"), {"code": "C38"})
        self.assertRedirects(resp, reverse("inventory:container_detail", args=[38]))

    def test_drawer_code_redirects_to_the_drawer(self):
        self.drawer.barcode_id = "D38B5"
        self.drawer.save()
        resp = self.client.get(reverse("inventory:go"), {"code": "D38B5"})
        self.assertRedirects(resp, reverse("inventory:drawer_detail", args=[self.drawer.pk]))

    def test_bin_code_redirects_to_the_bin(self):
        self.bin.barcode_id = "BIN0007"
        self.bin.save()
        resp = self.client.get(reverse("inventory:go"), {"code": "BIN0007"})
        self.assertRedirects(resp, reverse("inventory:bin_detail", args=[self.bin.pk]))

    def test_sub_bin_code_redirects_to_its_parent_bin(self):
        """A sub-bin has no page of its own -- it resolves to the bin holding it."""
        self.sub_bin.barcode_id = "SUB0001"
        self.sub_bin.save()
        resp = self.client.get(reverse("inventory:go"), {"code": "SUB0001"})
        self.assertRedirects(resp, reverse("inventory:bin_detail", args=[self.bin.pk]))

    def test_unknown_code_renders_not_found_with_the_code_echoed(self):
        resp = self.client.get(reverse("inventory:go"), {"code": "NOPE-123"})
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "inventory/not_found.html")
        self.assertEqual(resp.context["code"], "NOPE-123")

    def test_blank_code_redirects_to_the_scan_page(self):
        resp = self.client.get(reverse("inventory:go"), {"code": "   "})
        self.assertRedirects(resp, reverse("inventory:scan"))

    def test_code_is_stripped_before_matching(self):
        self.container.barcode_id = "C38"
        self.container.save()
        resp = self.client.get(reverse("inventory:go"), {"code": "  C38  "})
        self.assertRedirects(resp, reverse("inventory:container_detail", args=[38]))

    def test_container_wins_when_a_code_collides_across_models(self):
        """Container/Drawer/Bin/SubBin barcode_id are each unique within their own
        table but not across tables -- the resolver's order is the tie-break, so
        pin it rather than leave it implicit."""
        self.container.barcode_id = "DUP"
        self.container.save()
        self.drawer.barcode_id = "DUP"
        self.drawer.save()

        resp = self.client.get(reverse("inventory:go"), {"code": "DUP"})
        self.assertRedirects(resp, reverse("inventory:container_detail", args=[38]))


class JumpToContainerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.container = make_container(number=38)

    def setUp(self):
        self.client.force_login(self.user)

    def test_valid_number_redirects_to_the_container(self):
        resp = self.client.get(reverse("inventory:jump_to_container"), {"number": 38})
        self.assertRedirects(resp, reverse("inventory:container_detail", args=[38]))

    def test_valid_number_carries_a_scanned_code_through(self):
        resp = self.client.get(reverse("inventory:jump_to_container"), {"number": 38, "code": "C38"})
        self.assertEqual(resp.url, reverse("inventory:container_detail", args=[38]) + "?code=C38")

    def test_missing_container_returns_to_scan_with_an_error(self):
        resp = self.client.get(reverse("inventory:jump_to_container"), {"number": 9999})
        self.assertRedirects(resp, reverse("inventory:scan"))


class LoginWallTests(TestCase):
    """Anonymous access must never reach inventory data.

    An account has to exist for this to describe anything real: the wall being tested
    is "log in to see this", which presumes there is something to log in with. On a
    genuinely virgin install — no account at all — the app sends you to the setup
    wizard instead, which is a different behaviour tested alongside the wizard.
    """

    def setUp(self):
        self.user = make_user()

    def test_scan_resolver_requires_login(self):
        resp = self.client.get(reverse("inventory:go"), {"code": "C38"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/login/"), resp.url)

    def test_browse_requires_login(self):
        resp = self.client.get(reverse("inventory:browse"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/login/"), resp.url)
