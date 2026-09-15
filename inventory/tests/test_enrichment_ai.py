from unittest import mock

import requests as requests_lib
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import Part
from .factories import make_part, make_user


@override_settings(DEEPSEEK_API_KEY="test-key", DEEPSEEK_MODEL="deepseek-chat")
class EnrichmentSuggestTests(TestCase):
    def test_suggest_parses_json(self):
        from ..enrichment_ai import suggest_enrichment

        with mock.patch("inventory.enrichment_ai.requests.post") as post:
            post.return_value.raise_for_status = mock.Mock()
            post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"category": "Electronics", "description": "10k resistor", "manufacturer": "Vishay"}'}}]
            }
            result, err = suggest_enrichment("10k resistor")
        self.assertIsNone(err)
        self.assertEqual(result["category"], "Electronics")
        self.assertEqual(result["description"], "10k resistor")
        self.assertEqual(result["manufacturer"], "Vishay")

    def test_suggest_reports_request_failure(self):
        from ..enrichment_ai import suggest_enrichment

        with mock.patch("inventory.enrichment_ai.requests.post", side_effect=requests_lib.RequestException("boom")):
            result, err = suggest_enrichment("10k resistor")
        self.assertIsNone(result)
        self.assertIn("boom", err)

    def test_suggest_handles_non_json_reply(self):
        from ..enrichment_ai import suggest_enrichment

        with mock.patch("inventory.enrichment_ai.requests.post") as post:
            post.return_value.raise_for_status = mock.Mock()
            post.return_value.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
            result, err = suggest_enrichment("10k resistor")
        self.assertIsNone(result)
        self.assertIn("unexpected response", err)

    def test_extract_json_tolerates_fences_and_prose(self):
        from ..enrichment_ai import _extract_json

        obj = '{"category": "Tools", "description": "x", "manufacturer": ""}'
        self.assertEqual(_extract_json('```json\n' + obj + '\n```'), obj)
        self.assertEqual(_extract_json('Here you go: ' + obj), obj)


@override_settings(DEEPSEEK_API_KEY="")
class EnrichmentNotConfiguredTests(TestCase):
    def test_is_configured_false(self):
        from ..enrichment_ai import is_configured

        self.assertFalse(is_configured())

    def test_suggest_errors(self):
        from ..enrichment_ai import suggest_enrichment

        result, err = suggest_enrichment("x")
        self.assertIsNone(result)
        self.assertIn("isn't configured", err)


@override_settings(DEEPSEEK_API_KEY="test-key")
class EnrichmentViewFlowTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.part = make_part(name="10k Resistor")

    def test_suggest_then_apply_updates_part(self):
        suggestion = {"category": "Electronics", "description": "10k resistor", "manufacturer": "Vishay"}
        url = reverse("inventory:part_detail", kwargs={"pk": self.part.pk})
        with mock.patch("inventory.views.parts.suggest_enrichment", return_value=(suggestion, None)):
            resp = self.client.post(url, {"action": "suggest_enrichment"})
        self.assertRedirects(resp, url)

        resp = self.client.get(url)
        self.assertContains(resp, "Vishay")

        resp = self.client.post(url, {"action": "apply_enrichment"})
        self.assertRedirects(resp, url)
        self.part.refresh_from_db()
        self.assertEqual(self.part.category.name, "Electronics")
        self.assertEqual(self.part.manufacturer, "Vishay")
        self.assertEqual(self.part.description, "10k resistor")
        self.assertEqual(self.part.enrichment_status, Part.ENRICHMENT_DONE)

    def test_discard_clears_suggestion(self):
        suggestion = {"category": "Electronics", "description": "", "manufacturer": ""}
        url = reverse("inventory:part_detail", kwargs={"pk": self.part.pk})
        with mock.patch("inventory.views.parts.suggest_enrichment", return_value=(suggestion, None)):
            self.client.post(url, {"action": "suggest_enrichment"})
        self.client.post(url, {"action": "discard_enrichment"})
        self.part.refresh_from_db()
        self.assertIsNone(self.part.category)
        self.assertNotIn("enrichment_suggestion", self.client.session)

    @override_settings(DEEPSEEK_API_KEY="")
    def test_no_button_when_not_configured(self):
        url = reverse("inventory:part_detail", kwargs={"pk": self.part.pk})
        resp = self.client.get(url)
        self.assertNotContains(resp, "Suggest enrichment")


@override_settings(DEEPSEEK_API_KEY="test-key", DEEPSEEK_MODEL="deepseek-chat")
class EnrichmentInAppTests(TestCase):
    """The queue-side, in-app enrichment actions: flag, bulk classify, AI enrich, AI scan."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_flag_part_for_enrichment_sets_pending(self):
        part = make_part(name="ESP32 devkit")
        self.client.post(reverse("inventory:flag_part_for_enrichment", args=[part.pk]))
        part.refresh_from_db()
        self.assertEqual(part.enrichment_status, Part.ENRICHMENT_PENDING)

    def test_bulk_classify_updates_statuses_from_the_queue(self):
        a = make_part(name="A", enrichment_status=Part.ENRICHMENT_NEEDS_CLARIFICATION)
        b = make_part(name="B", enrichment_status=Part.ENRICHMENT_NEEDS_CLARIFICATION)
        self.client.post(
            reverse("inventory:bulk_classify"),
            {f"status_{a.pk}": Part.ENRICHMENT_PENDING, f"status_{b.pk}": Part.ENRICHMENT_NOT_NEEDED},
        )
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.enrichment_status, Part.ENRICHMENT_PENDING)
        self.assertEqual(b.enrichment_status, Part.ENRICHMENT_NOT_NEEDED)

    def test_bulk_classify_ignores_an_unknown_status(self):
        a = make_part(name="A", enrichment_status=Part.ENRICHMENT_NEEDS_CLARIFICATION)
        self.client.post(reverse("inventory:bulk_classify"), {f"status_{a.pk}": "bogus"})
        a.refresh_from_db()
        self.assertEqual(a.enrichment_status, Part.ENRICHMENT_NEEDS_CLARIFICATION)

    def test_enrich_pending_applies_suggestions_in_app(self):
        part = make_part(name="ESP32 devkit", enrichment_status=Part.ENRICHMENT_PENDING)
        suggestion = {"category": "Electronics", "description": "ESP32 development board", "manufacturer": "Espressif"}
        with mock.patch("inventory.views.enrichment.enrichment_ai.suggest_enrichment", return_value=(suggestion, None)):
            self.client.post(reverse("inventory:enrich_pending_with_ai"))
        part.refresh_from_db()
        self.assertEqual(part.enrichment_status, Part.ENRICHMENT_DONE)
        self.assertEqual(part.manufacturer, "Espressif")
        self.assertEqual(part.category.name, "Electronics")

    def test_enrich_pending_flags_a_thin_suggestion_for_review(self):
        part = make_part(name="Mystery widget", enrichment_status=Part.ENRICHMENT_PENDING)
        suggestion = {"category": "", "description": "", "manufacturer": ""}
        with mock.patch("inventory.views.enrichment.enrichment_ai.suggest_enrichment", return_value=(suggestion, None)):
            self.client.post(reverse("inventory:enrich_pending_with_ai"))
        part.refresh_from_db()
        self.assertEqual(part.enrichment_status, Part.ENRICHMENT_NEEDS_REVIEW)

    def test_ai_scan_flags_candidates(self):
        a = make_part(name="Specific ESP32 board", enrichment_status=Part.ENRICHMENT_NOT_NEEDED)
        b = make_part(name="assorted screws", enrichment_status=Part.ENRICHMENT_NOT_NEEDED)
        classifications = {"Specific ESP32 board": "pending", "assorted screws": "not_needed"}
        with mock.patch("inventory.views.enrichment.enrichment_ai.ai_classify_candidates", return_value=(classifications, None)):
            self.client.post(reverse("inventory:ai_scan_candidates"))
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.enrichment_status, Part.ENRICHMENT_PENDING)
        self.assertEqual(b.enrichment_status, Part.ENRICHMENT_NOT_NEEDED)

    def test_enrich_pending_uses_web_research_when_configured(self):
        part = make_part(name="ESP32 devkit", enrichment_status=Part.ENRICHMENT_PENDING)
        data = {
            "category": "Electronics",
            "description": "ESP32 development board",
            "manufacturer": "Espressif",
            "product_url": "https://example.test/p",
            "datasheet_url": "https://example.test/d.pdf",
            "confidence": "high",
        }
        with mock.patch("inventory.views.enrichment.research.is_configured", return_value=True), mock.patch(
            "inventory.views.enrichment.research.research_part", return_value=(data, None)
        ):
            self.client.post(reverse("inventory:enrich_pending_with_ai"))
        part.refresh_from_db()
        self.assertEqual(part.reorder_url, "https://example.test/p")
        self.assertEqual(part.datasheet_url, "https://example.test/d.pdf")
        self.assertEqual(part.manufacturer, "Espressif")
        self.assertEqual(part.enrichment_status, Part.ENRICHMENT_DONE)

    @override_settings(DEEPSEEK_API_KEY="")
    def test_enrich_requires_configuration(self):
        part = make_part(name="ESP32", enrichment_status=Part.ENRICHMENT_PENDING)
        self.client.post(reverse("inventory:enrich_pending_with_ai"))
        part.refresh_from_db()
        self.assertEqual(part.enrichment_status, Part.ENRICHMENT_PENDING)
