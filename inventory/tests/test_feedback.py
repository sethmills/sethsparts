"""In-app feedback: the form and the relay endpoint.

The important property: a beta install with only FEEDBACK_URL configured (no SMTP, no
email) can still send feedback, and a relay endpoint that can't reach anyone never
crashes — it answers honestly and the sender falls back to copy-to-clipboard.
"""
import json
from unittest import mock

import requests

from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.models import SiteSettings

from .factories import make_user


class FeedbackFormTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user())

    def test_page_renders(self):
        self.assertEqual(self.client.get(reverse("inventory:feedback")).status_code, 200)

    def test_needs_login(self):
        self.client.logout()
        response = self.client.get(reverse("inventory:feedback"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"), response["Location"])

    @override_settings(FEEDBACK_URL="https://relay.example.com/api/feedback/", FEEDBACK_KEY="secret")
    @mock.patch("requests.post")
    def test_posts_to_relay_when_url_configured(self, post):
        post.return_value = mock.Mock(status_code=200)
        response = self.client.post(
            reverse("inventory:feedback"),
            {"kind": "bug", "title": "Broken", "message": "It broke", "page": "/parts/"},
        )
        self.assertEqual(response.status_code, 302)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["title"], "Broken")
        self.assertEqual(payload["key"], "secret")
        self.assertEqual(payload["page"], "/parts/")

    @override_settings(FEEDBACK_URL="https://relay.example.com/api/feedback/")
    @mock.patch("requests.post", side_effect=requests.ConnectionError("down"))
    def test_relay_down_falls_back_to_copy(self, post):
        response = self.client.post(
            reverse("inventory:feedback"),
            {"kind": "bug", "title": "Broken", "message": "It broke"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "It broke")

    @mock.patch("inventory.notifications.send", return_value=(True, ""))
    def test_emails_locally_when_no_url(self, send):
        SiteSettings.objects.create(feedback_email="owner@example.com")
        response = self.client.post(
            reverse("inventory:feedback"),
            {"kind": "feature", "title": "Want X", "message": "Please add X"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(send.call_args.kwargs["to"], "owner@example.com")

    def test_copy_fallback_when_no_route(self):
        response = self.client.post(
            reverse("inventory:feedback"),
            {"kind": "bug", "title": "Broken", "message": "It broke"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "It broke")


class FeedbackRelayEndpointTests(TestCase):
    def setUp(self):
        self.url = reverse("inventory:api_feedback")

    def test_rejects_get(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_rejects_invalid_json(self):
        response = self.client.post(self.url, data="not json", content_type="text/plain")
        self.assertEqual(response.status_code, 400)

    @override_settings(FEEDBACK_KEY="secret")
    def test_rejects_bad_key(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"key": "wrong", "title": "x", "message": "y"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    @mock.patch("inventory.notifications.send", return_value=(True, ""))
    def test_accepts_valid_payload(self, send):
        SiteSettings.objects.create(feedback_email="owner@example.com")
        response = self.client.post(
            self.url,
            data=json.dumps(
                {
                    "kind": "bug",
                    "title": "x",
                    "message": "y",
                    "instance": "Dad's shop",
                    "version": "0.4.0",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(send.call_args.kwargs["to"], "owner@example.com")

    def test_no_address_502(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"title": "x", "message": "y"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 502)

    def test_empty_payload_400(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"title": "", "message": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
