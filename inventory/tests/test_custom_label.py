from django.test import TestCase
from django.urls import reverse

from .factories import make_user


class CustomLabelViewTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user())

    def test_custom_label_page_renders(self):
        # Guards against a broken `label_printing` import turning this page into a 500.
        resp = self.client.get(reverse("inventory:custom_label"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Custom label")
