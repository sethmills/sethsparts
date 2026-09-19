"""Pick-list / walk mode: step through a BOM one part at a time."""
from django.test import TestCase
from django.urls import reverse

from ..models import BOMLine, BOMRevision, Project, ShoppingListItem, StockItem
from .factories import make_container, make_part, make_user


class PickModeTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.container = make_container(number=1)
        self.part1 = make_part(name="Resistor")
        self.part2 = make_part(name="Capacitor")
        StockItem.objects.create(part=self.part1, container=self.container, quantity=10)
        StockItem.objects.create(part=self.part2, container=self.container, quantity=10)
        self.project = Project.objects.create(name="Amp")
        self.rev = BOMRevision.objects.create(project=self.project)
        BOMLine.objects.create(revision=self.rev, part=self.part1, quantity_required=2)
        BOMLine.objects.create(revision=self.rev, part=self.part2, quantity_required=3)
        self.url = reverse("inventory:pick", kwargs={"pk": self.project.pk})

    def test_walk_through_all_parts(self):
        self.client.post(self.url, {"action": "start"})
        resp = self.client.get(self.url)
        self.assertContains(resp, "Part 1 of 2")

        self.client.post(self.url, {"action": "pulled"})
        resp = self.client.get(self.url)
        self.assertContains(resp, "Part 2 of 2")

        self.client.post(self.url, {"action": "missing"})
        resp = self.client.get(self.url)
        self.assertContains(resp, "Summary")
        self.assertContains(resp, "Couldn't find")

    def test_missing_parts_add_to_shopping_list(self):
        self.client.post(self.url, {"action": "start"})
        self.client.post(self.url, {"action": "missing"})
        self.client.post(self.url, {"action": "missing"})
        self.client.post(self.url, {"action": "add_missing_to_list"})
        self.assertEqual(ShoppingListItem.objects.count(), 2)
