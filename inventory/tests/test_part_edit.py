"""Editing a part's metadata after it has been created."""
from django.test import TestCase
from django.urls import reverse

from ..models import Part
from .factories import make_part, make_user


class PartEditTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.part = make_part(name="Old name")

    def test_edit_updates_metadata(self):
        self.client.post(
            reverse("inventory:part_edit", kwargs={"pk": self.part.pk}),
            {
                "name": "New name",
                "manufacturer": "Acme",
                "description": "A widget",
                "reorder_url": "https://example.com/buy",
                "datasheet_url": "https://example.com/ds.pdf",
                "price": "£1.20",
                "min_quantity": "5",
                "is_electronic": "on",
            },
        )
        self.part.refresh_from_db()
        self.assertEqual(self.part.name, "New name")
        self.assertEqual(self.part.manufacturer, "Acme")
        self.assertEqual(self.part.description, "A widget")
        self.assertEqual(self.part.reorder_url, "https://example.com/buy")
        self.assertEqual(self.part.datasheet_url, "https://example.com/ds.pdf")
        self.assertEqual(self.part.price, "£1.20")
        self.assertEqual(self.part.min_quantity, 5)
        self.assertTrue(self.part.is_electronic)

    def test_edit_rejects_blank_name(self):
        self.client.post(reverse("inventory:part_edit", kwargs={"pk": self.part.pk}), {"name": "   "})
        self.part.refresh_from_db()
        self.assertEqual(self.part.name, "Old name")

    def test_blank_min_quantity_clears_threshold(self):
        self.part.min_quantity = 10
        self.part.save()
        self.client.post(
            reverse("inventory:part_edit", kwargs={"pk": self.part.pk}),
            {"name": "New name", "min_quantity": ""},
        )
        self.part.refresh_from_db()
        self.assertIsNone(self.part.min_quantity)
