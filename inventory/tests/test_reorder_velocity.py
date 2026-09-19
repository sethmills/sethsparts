"""The reorder dashboard shows last-30-days consumption so velocity is visible."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import BOMLine, BOMRevision, Build, BuildConsumption, Project, StockItem
from .factories import make_container, make_part, make_user


class ReorderVelocityTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.container = make_container(number=1)
        self.part = make_part(name="10k resistor", min_quantity=10)
        StockItem.objects.create(part=self.part, container=self.container, quantity=3)  # below threshold

    def _consume(self, amount, days_ago):
        project = Project.objects.create(name="Amp")
        rev = BOMRevision.objects.create(project=project)
        BOMLine.objects.create(revision=rev, part=self.part, quantity_required=amount)
        build = Build.objects.create(project=project, revision=rev, quantity_built=1)
        # auto_now_add overrides an explicit built_at on create, so set it afterwards.
        Build.objects.filter(pk=build.pk).update(built_at=timezone.now() - timedelta(days=days_ago))
        BuildConsumption.objects.create(build=build, part=self.part, quantity_requested=amount, quantity_consumed=amount)

    def test_velocity_shows_recent_consumption(self):
        self._consume(37, days_ago=5)
        resp = self.client.get(reverse("inventory:reorder"))
        self.assertContains(resp, "30d use")
        self.assertIn(">37<", resp.content.decode())

    def test_consumption_older_than_30_days_is_ignored(self):
        self._consume(37, days_ago=45)
        resp = self.client.get(reverse("inventory:reorder"))
        self.assertNotIn(">37<", resp.content.decode())
