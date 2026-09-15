"""Web research (Tavily search + DeepSeek extraction) and the AI key settings page."""
from unittest import mock

import requests as requests_lib
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory import research
from inventory.models import SiteSettings

from .factories import make_user


@override_settings(TAVILY_API_KEY="tvly-test", DEEPSEEK_API_KEY="ds-test", DEEPSEEK_MODEL="deepseek-chat")
class ResearchSearchTests(TestCase):
    def test_search_part_returns_results(self):
        payload = {"results": [{"title": "ESP32 datasheet", "url": "https://example.test/esp32.pdf", "content": "ESP32 series"}]}
        with mock.patch("inventory.research.requests.post") as post:
            post.return_value.raise_for_status = mock.Mock()
            post.return_value.json.return_value = payload
            results, err = research.search_part("ESP32")
        self.assertIsNone(err)
        self.assertEqual(results[0]["url"], "https://example.test/esp32.pdf")

    def test_search_part_reports_failure(self):
        with mock.patch("inventory.research.requests.post", side_effect=requests_lib.RequestException("boom")):
            results, err = research.search_part("ESP32")
        self.assertEqual(results, [])
        self.assertIn("boom", err)

    def test_extract_part_data_parses_fields(self):
        results = [{"title": "t", "url": "https://example.test/x", "content": "c"}]
        content = (
            '{"matched_product_name": "ESP32", "category": "Electronics", "manufacturer": "Espressif", '
            '"product_url": "https://example.test/p", "datasheet_url": "https://example.test/d.pdf", '
            '"pinout_url": "", "price": "", "confidence": "high"}'
        )
        with mock.patch("inventory.research.requests.post") as post:
            post.return_value.raise_for_status = mock.Mock()
            post.return_value.json.return_value = {"choices": [{"message": {"content": content}}]}
            data, err = research.extract_part_data("ESP32", results)
        self.assertIsNone(err)
        self.assertEqual(data["manufacturer"], "Espressif")
        self.assertEqual(data["product_url"], "https://example.test/p")
        self.assertEqual(data["confidence"], "high")

    def test_research_part_orchestrates_search_and_extract(self):
        with mock.patch("inventory.research.search_part", return_value=([{"title": "t", "url": "u", "content": "c"}], None)), mock.patch(
            "inventory.research.extract_part_data", return_value=({"manufacturer": "Espressif", "confidence": "high"}, None)
        ):
            data, err = research.research_part("ESP32")
        self.assertIsNone(err)
        self.assertEqual(data["manufacturer"], "Espressif")


@override_settings(TAVILY_API_KEY="", DEEPSEEK_API_KEY="")
class ResearchKeyResolutionTests(TestCase):
    def test_is_configured_false_without_keys(self):
        self.assertFalse(research.is_configured())

    def test_search_part_reports_no_key(self):
        results, err = research.search_part("x")
        self.assertEqual(results, [])
        self.assertIn("Tavily isn't configured", err)

    def test_keys_come_from_site_settings_when_env_is_empty(self):
        SiteSettings.objects.create(deepseek_api_key="ds-from-site", tavily_api_key="tvly-from-site")
        self.assertTrue(research.is_configured())


class SetupAiPageTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_page_shows_the_form(self):
        resp = self.client.get(reverse("inventory:setup_ai"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Tavily")
        self.assertContains(resp, "DeepSeek")

    def test_page_saves_keys_to_site_settings(self):
        self.client.post(reverse("inventory:setup_ai"), {"deepseek_api_key": "sk-abc", "tavily_api_key": "tvly-xyz"})
        site = SiteSettings.objects.get()
        self.assertEqual(site.deepseek_api_key, "sk-abc")
        self.assertEqual(site.tavily_api_key, "tvly-xyz")
