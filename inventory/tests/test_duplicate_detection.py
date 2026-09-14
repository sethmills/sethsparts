from django.test import TestCase
from django.urls import reverse

from ..duplicate_detection import find_duplicate_parts
from ..models import Part
from .factories import make_container, make_part, make_user


class DuplicateDetectionTests(TestCase):
    def test_exact_normalized_match(self):
        make_part(name="M3 Bolt")
        result = find_duplicate_parts("m3 bolt")
        self.assertEqual([name for _, name in result], ["M3 Bolt"])

    def test_plural_is_a_near_match(self):
        make_part(name="M3 Bolt")
        result = find_duplicate_parts("M3 bolts")
        self.assertEqual([name for _, name in result], ["M3 Bolt"])

    def test_extra_spec_is_a_token_match(self):
        make_part(name="M3 Bolt")
        result = find_duplicate_parts("M3 bolt 10mm")
        self.assertEqual([name for _, name in result], ["M3 Bolt"])

    def test_short_name_matches_longer_existing(self):
        make_part(name="LED strip 5m")
        result = find_duplicate_parts("LED")
        self.assertEqual([name for _, name in result], ["LED strip 5m"])

    def test_no_false_positive_for_unrelated(self):
        make_part(name="Arduino Uno")
        self.assertEqual(find_duplicate_parts("relay module"), [])

    def test_empty_name_returns_nothing(self):
        self.assertEqual(find_duplicate_parts(""), [])


class PartIntakeDuplicateFlowTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.container = make_container(number=1)
        self.url = reverse("inventory:part_intake")

    def _post(self, **data):
        return self.client.post(self.url, {"container": "1", **data})

    def test_existing_duplicate_is_surfaced_instead_of_creating(self):
        make_part(name="M3 Bolt")
        resp = self._post(name="M3 Bolt", quantity="5")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "You may already have this part")
        self.assertEqual(Part.objects.count(), 1)

    def test_create_confirmed_makes_new_part(self):
        make_part(name="M3 Bolt")
        resp = self._post(name="M3 Bolt", quantity="5", create_confirmed="1")
        self.assertRedirects(resp, reverse("inventory:container_detail", kwargs={"number": 1}))
        self.assertEqual(Part.objects.count(), 2)

    def test_use_existing_adds_stock_without_new_part(self):
        existing = make_part(name="M3 Bolt")
        resp = self._post(name="M3 bolts", quantity="5", existing_part=str(existing.pk))
        self.assertRedirects(resp, reverse("inventory:container_detail", kwargs={"number": 1}))
        self.assertEqual(Part.objects.count(), 1)
        self.assertEqual(existing.stock_items.count(), 1)
        self.assertEqual(existing.stock_items.first().quantity, 5)

    def test_no_duplicate_creates_directly(self):
        resp = self._post(name="Relay module", quantity="3")
        self.assertRedirects(resp, reverse("inventory:container_detail", kwargs={"number": 1}))
        self.assertEqual(Part.objects.count(), 1)
        self.assertEqual(Part.objects.first().stock_items.first().quantity, 3)

    def test_get_with_name_prefill_shows_candidates(self):
        make_part(name="M3 Bolt")
        resp = self.client.get(self.url, {"name": "M3 bolts", "container": "1"})
        self.assertContains(resp, "You may already have this part")
