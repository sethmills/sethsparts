"""The audit trail records stock adjustments, moves, and removals."""
from django.test import TestCase
from django.urls import reverse

from ..models import AuditEvent, StockItem
from .factories import make_container, make_part, make_user


class AuditTrailTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.part = make_part(name="10k resistor")
        self.container = make_container(number=1)
        self.stock = StockItem.objects.create(part=self.part, container=self.container, quantity=100)

    def test_stock_adjust_is_logged(self):
        self.client.post(
            reverse("inventory:update_stock_quantity", kwargs={"pk": self.stock.pk}),
            {"quantity": "60"},
        )
        ev = AuditEvent.objects.get()
        self.assertEqual(ev.verb, "stock.adjust")
        self.assertEqual(ev.part, self.part)
        self.assertEqual(ev.actor, self.user)
        self.assertEqual(ev.payload["before"], 100)
        self.assertEqual(ev.payload["after"], 60)

    def test_stock_move_is_logged(self):
        self.client.post(
            reverse("inventory:update_stock_bin", kwargs={"pk": self.stock.pk}),
            {"bin_number": "4"},
        )
        ev = AuditEvent.objects.get()
        self.assertEqual(ev.verb, "stock.move")
        self.assertEqual(ev.payload["after"], 4)

    def test_stock_add_is_logged(self):
        self.client.post(
            reverse("inventory:add_stock_item", kwargs={"pk": self.part.pk}),
            {"location": f"container:{self.container.number}", "quantity": "25"},
        )
        ev = AuditEvent.objects.get()
        self.assertEqual(ev.verb, "stock.add")
        self.assertEqual(ev.payload["quantity"], 25)

    def test_stock_remove_is_logged(self):
        self.client.post(reverse("inventory:delete_stock_item", kwargs={"pk": self.stock.pk}))
        ev = AuditEvent.objects.get()
        self.assertEqual(ev.verb, "stock.remove")
        self.assertEqual(ev.payload["quantity"], 100)

    def test_audit_log_page_renders(self):
        from .. import audit

        audit.log("stock.adjust", part=self.part, actor=self.user, before=1, after=2)
        resp = self.client.get(reverse("inventory:audit_log"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "stock.adjust")
