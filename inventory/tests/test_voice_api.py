"""The machine-to-machine voice-search endpoint Home Assistant calls.

This one is not @login_required -- HA has no browser session -- so the shared
secret IS the security boundary. Getting the rejection paths wrong would expose
the whole inventory to anyone who finds the URL.
"""
import json

from django.test import TestCase, override_settings
from django.urls import reverse

from .factories import make_container, make_drawer, make_part, make_stock

URL = "/api/locate/"
KEY = "voice-secret"
ON = override_settings(VOICE_SEARCH_API_KEY=KEY)


class VoiceApiAuthTests(TestCase):
    def setUp(self):
        make_stock(make_part(name="Resistor 10k"), make_container(number=1), quantity=5)

    def test_403_when_no_key_is_configured_at_all(self):
        """Unset must mean 'reject everything', not 'allow everything'."""
        with override_settings(VOICE_SEARCH_API_KEY=""):
            resp = self.client.get(URL, {"q": "resistor"})
        self.assertEqual(resp.status_code, 403)

    @ON
    def test_403_with_no_key_supplied(self):
        resp = self.client.get(URL, {"q": "resistor"})
        self.assertEqual(resp.status_code, 403)

    @ON
    def test_403_with_a_wrong_key(self):
        resp = self.client.get(URL, {"q": "resistor", "key": "nope"})
        self.assertEqual(resp.status_code, 403)

    @ON
    def test_403_with_a_wrong_header_key(self):
        resp = self.client.get(URL, {"q": "resistor"}, headers={"X-Api-Key": "nope"})
        self.assertEqual(resp.status_code, 403)

    @ON
    def test_403_response_body_does_not_leak_inventory(self):
        resp = self.client.get(URL, {"q": "resistor"})
        self.assertEqual(json.loads(resp.content), {"error": "unauthorized"})

    @ON
    def test_the_key_can_come_from_the_header(self):
        resp = self.client.get(URL, {"q": "resistor"}, headers={"X-Api-Key": KEY})
        self.assertEqual(resp.status_code, 200)

    @ON
    def test_the_key_can_come_from_the_query_string(self):
        resp = self.client.get(URL, {"q": "resistor", "key": KEY})
        self.assertEqual(resp.status_code, 200)

    @ON
    def test_the_header_wins_over_the_query_string(self):
        resp = self.client.get(URL, {"q": "resistor", "key": "wrong"}, headers={"X-Api-Key": KEY})
        self.assertEqual(resp.status_code, 200)

    def test_the_endpoint_needs_no_login(self):
        """The whole reason it exists -- asserted so nobody bolts @login_required
        onto it later and silently breaks Seth's voice control."""
        with override_settings(VOICE_SEARCH_API_KEY=KEY):
            resp = self.client.get(URL, {"q": "resistor", "key": KEY})
        self.assertNotIn(resp.status_code, (301, 302))


class VoiceApiQueryTests(TestCase):
    def setUp(self):
        self.container = make_container(number=38, container_type="cabinets")
        self.drawer = make_drawer(self.container, label="drawer 5")

    def call(self, **params):
        return self.client.get(URL, {**params, "key": KEY})

    @ON
    def test_missing_q_is_a_400(self):
        resp = self.call()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(json.loads(resp.content)["error"], "missing q")

    @ON
    def test_blank_q_is_a_400(self):
        resp = self.client.get(URL, {"q": "   ", "key": KEY})
        self.assertEqual(resp.status_code, 400)

    @ON
    def test_a_match_reports_name_manufacturer_and_locations(self):
        part = make_part(name="Resistor 10k", manufacturer="Yageo")
        make_stock(part, self.container, drawer=self.drawer, quantity=5)

        body = json.loads(self.call(q="resistor").content)

        self.assertEqual(body["query"], "resistor")
        self.assertEqual(body["count"], 1)
        match = body["matches"][0]
        self.assertEqual(match["name"], "Resistor 10k")
        self.assertEqual(match["manufacturer"], "Yageo")
        self.assertEqual(match["locations"], [str(self.drawer)])

    @ON
    def test_locations_fall_back_to_the_container_for_undrawered_stock(self):
        part = make_part(name="Resistor 10k")
        make_stock(part, self.container, quantity=5)

        match = json.loads(self.call(q="resistor").content)["matches"][0]
        self.assertEqual(match["locations"], [str(self.container)])

    @ON
    def test_locations_are_deduplicated_and_sorted(self):
        part = make_part(name="Resistor 10k")
        other = make_drawer(self.container, label="drawer 1")
        make_stock(part, self.container, drawer=other, quantity=1)
        make_stock(part, self.container, drawer=self.drawer, quantity=1)
        make_stock(part, self.container, drawer=self.drawer, quantity=2)

        match = json.loads(self.call(q="resistor").content)["matches"][0]
        self.assertEqual(match["locations"], sorted([str(other), str(self.drawer)]))
        self.assertEqual(len(match["locations"]), 2)

    @ON
    def test_quantity_summary_prefers_the_raw_spreadsheet_text(self):
        """'10 aprox' is more honest to read back aloud than 'unknown qty'."""
        part = make_part(name="Resistor 10k")
        make_stock(part, self.container, quantity=None, quantity_raw="10 aprox")

        match = json.loads(self.call(q="resistor").content)["matches"][0]
        self.assertIn("10 aprox", match["quantity_summary"])

    @ON
    def test_quantity_summary_says_unknown_when_there_is_no_number(self):
        part = make_part(name="Resistor 10k")
        make_stock(part, self.container, quantity=None)

        match = json.loads(self.call(q="resistor").content)["matches"][0]
        self.assertIn("unknown qty", match["quantity_summary"])

    @ON
    def test_results_are_capped_at_five_for_a_spoken_answer(self):
        for i in range(12):
            make_stock(make_part(name=f"Resistor {i}"), self.container, quantity=1)

        body = json.loads(self.call(q="resistor").content)
        self.assertEqual(body["count"], 5)
        self.assertEqual(len(body["matches"]), 5)

    @ON
    def test_no_matches_is_a_clean_empty_result_not_an_error(self):
        body = json.loads(self.call(q="zzzznotathing").content)
        self.assertEqual(body, {"query": "zzzznotathing", "count": 0, "matches": []})

    @ON
    def test_synonym_expansion_applies_here_too(self):
        """'where is my display' should find the TFT module, same as the web search."""
        part = make_part(name="1.8 inch SPI TFT module")
        make_stock(part, self.container, quantity=1)

        body = json.loads(self.call(q="display").content)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["matches"][0]["name"], part.name)

    @ON
    def test_the_query_is_echoed_back_stripped(self):
        body = json.loads(self.client.get(URL, {"q": "  resistor  ", "key": KEY}).content)
        self.assertEqual(body["query"], "resistor")
