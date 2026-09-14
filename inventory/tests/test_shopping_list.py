from django.test import TestCase
from django.urls import reverse

from ..models import Part, ShoppingListItem
from .factories import make_container, make_part, make_stock, make_user


class ShoppingListTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.container = make_container(number=1)
        self.part = make_part(name="M3 Bolt", min_quantity=10)

    def test_add_creates_item(self):
        resp = self.client.post(
            reverse("inventory:shopping_list_add", kwargs={"pk": self.part.pk}), {"quantity": "7"}
        )
        self.assertEqual(resp.status_code, 302)
        item = ShoppingListItem.objects.get()
        self.assertEqual(item.part, self.part)
        self.assertEqual(item.quantity, 7)

    def test_readd_bumps_quantity_instead_of_duplicating(self):
        ShoppingListItem.objects.create(part=self.part, quantity=3)
        self.client.post(
            reverse("inventory:shopping_list_add", kwargs={"pk": self.part.pk}), {"quantity": "7"}
        )
        self.assertEqual(ShoppingListItem.objects.count(), 1)
        self.assertEqual(ShoppingListItem.objects.get().quantity, 7)

    def test_toggle_and_clear(self):
        item = ShoppingListItem.objects.create(part=self.part, quantity=2, bought=True)
        self.client.post(reverse("inventory:shopping_list_toggle", kwargs={"pk": item.pk}))
        item.refresh_from_db()
        self.assertFalse(item.bought)
        # Mark bought again, then clear the bought rows.
        self.client.post(reverse("inventory:shopping_list_toggle", kwargs={"pk": item.pk}))
        self.client.post(reverse("inventory:shopping_list_clear"))
        self.assertEqual(ShoppingListItem.objects.count(), 0)

    def test_export_text(self):
        ShoppingListItem.objects.create(part=self.part, quantity=5)
        resp = self.client.get(reverse("inventory:shopping_list_export"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn("M3 Bolt", body)
        self.assertIn("x5", body)

    def test_reorder_page_has_add_button_for_short_parts(self):
        make_stock(self.part, self.container, quantity=2)  # have=2 < min=10
        resp = self.client.get(reverse("inventory:reorder"))
        self.assertContains(resp, "Add to list")

    def test_shopping_list_page_lists_items(self):
        ShoppingListItem.objects.create(part=self.part, quantity=4)
        resp = self.client.get(reverse("inventory:shopping_list"))
        self.assertContains(resp, "M3 Bolt")
        self.assertContains(resp, "4")
