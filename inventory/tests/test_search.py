"""Search behaviour -- the synonym map and the Q-object builder.

This is the logic behind "search by function, not just by name", used by both
the human /search/ page and the Home Assistant voice endpoint, so a
regression here silently degrades both.
"""
from django.test import TestCase
from django.urls import reverse

from inventory.models import Part
from inventory.search import build_search_query, expand_terms

from .factories import make_category, make_part, make_user


class ExpandTermsTests(TestCase):
    def test_empty_query_expands_to_nothing(self):
        self.assertEqual(expand_terms(""), [])
        self.assertEqual(expand_terms("   "), [])

    def test_display_pulls_in_the_panel_technologies(self):
        terms = expand_terms("display")
        for expected in ("oled", "tft", "lcd", "screen", "e-ink"):
            self.assertIn(expected, terms)

    def test_the_query_itself_is_not_returned_as_its_own_synonym(self):
        self.assertNotIn("display", expand_terms("display"))

    def test_matching_is_case_insensitive(self):
        self.assertEqual(expand_terms("DISPLAY"), expand_terms("display"))

    def test_a_query_containing_a_key_pulls_that_key_s_expansions(self):
        # "motor driver" is its own key; "driver" is a separate one. A query
        # mentioning either should surface the h-bridge family.
        self.assertIn("h-bridge", expand_terms("motor driver"))
        self.assertIn("h-bridge", expand_terms("driver"))

    def test_unrelated_query_expands_to_nothing(self):
        self.assertEqual(expand_terms("zzzznotathing"), [])


class BuildSearchQueryTests(TestCase):
    def setUp(self):
        make_category(name="Sensors")

    def test_empty_query_returns_a_permissive_q_object(self):
        """FOOTGUN, pinned deliberately: build_search_query("") returns an empty
        Q(), and filter(Q()) matches EVERY row. Both current callers guard before
        calling (parts_search checks `if query:`, api_locate_part returns 400 on a
        blank q), so this is safe today -- but a future caller that forgets the
        guard leaks the entire inventory into a search result. If you are adding
        a caller, guard first. See PartsSearchViewTests for the view-level
        behaviour that actually protects the user.
        """
        make_part(name="anything at all")
        self.assertEqual(Part.objects.filter(build_search_query("")).count(), 1)

    def test_plain_substring_match_on_name(self):
        hit = make_part(name="Resistor 10k 0.25W")
        make_part(name="Capacitor 100uF")
        self.assertIn(hit, Part.objects.filter(build_search_query("resist")))

    def test_matches_across_name_description_manufacturer_and_category(self):
        by_name = make_part(name="Blue Button")
        by_desc = make_part(name="X1", description="a lovely blue thing")
        by_manu = make_part(name="X2", manufacturer="Blue Origin Ltd")
        by_cat = make_part(name="X3", category=make_category(name="Blue Stuff"))

        ids = set(Part.objects.filter(build_search_query("Blue")).values_list("id", flat=True))
        for p in (by_name, by_desc, by_manu, by_cat):
            self.assertIn(p.id, ids, p.name)

    def test_synonym_reaches_a_part_whose_name_never_says_display(self):
        """The whole point of the feature: searching 'display' finds a TFT module
        even though the part never uses the word 'display'."""
        tft = make_part(name="1.8 inch SPI TFT module")
        self.assertNotIn("display", tft.name.lower())
        self.assertIn(tft, Part.objects.filter(build_search_query("display")))

    def test_synonyms_match_whole_words_only(self):
        """Short abbreviations like 'ble' must not fire inside 'cable'/'table'.

        'ble' is a Bluetooth synonym, so this is the exact near-miss the
        original implementation was written to avoid.
        """
        cable = make_part(name="Cable assembly 2m")
        self.assertNotIn(cable, Part.objects.filter(build_search_query("bluetooth")))

    def test_word_boundary_synonym_does_match_the_abbreviation_itself(self):
        ble = make_part(name="BLE module nRF52")
        self.assertIn(ble, Part.objects.filter(build_search_query("bluetooth")))

    def test_partial_word_still_matches(self):
        """The raw query stays a plain icontains match, so a half-typed word
        (the common case when typing into /search/ live) still hits."""
        part = make_part(name="Solderless Breadboard 830 tie")
        self.assertIn(part, Part.objects.filter(build_search_query("breadb")))

    def test_a_genuine_typo_does_not_match(self):
        """Documents the actual limit of the design: this is substring matching
        plus a fixed synonym map, not fuzzy/typo correction. If someone later
        adds real fuzzy matching, this test should be the thing that fails."""
        make_part(name="Solderless Breadboard 830 tie")
        self.assertEqual(Part.objects.filter(build_search_query("breadbrd")).count(), 0)


class PartsSearchViewTests(TestCase):
    """The /search/ view is what actually protects the user from the permissive
    build_search_query("") behaviour documented above."""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()

    def setUp(self):
        self.client.force_login(self.user)

    def test_a_completely_unfiltered_search_returns_nothing(self):
        """Landing on /search/ with no params must not dump the whole inventory."""
        make_part(name="Should not appear")
        resp = self.client.get(reverse("inventory:parts_search"))
        self.assertEqual(list(resp.context["parts"]), [])

    def test_a_real_query_returns_matches(self):
        hit = make_part(name="Resistor 10k")
        make_part(name="Capacitor 100uF")
        resp = self.client.get(reverse("inventory:parts_search"), {"q": "resistor"})
        self.assertEqual(list(resp.context["parts"]), [hit])

    def test_whitespace_only_query_is_treated_as_no_query(self):
        make_part(name="Should not appear")
        resp = self.client.get(reverse("inventory:parts_search"), {"q": "   "})
        self.assertEqual(list(resp.context["parts"]), [])

    def test_results_are_capped_at_150(self):
        """A broad query must not stream the entire catalogue into one page."""
        Part.objects.bulk_create(
            [Part(name=f"Resistor {i}", normalized_name=f"resistor {i}") for i in range(200)]
        )
        resp = self.client.get(reverse("inventory:parts_search"), {"q": "resistor"})
        self.assertEqual(len(resp.context["parts"]), 150)

    def test_synonym_expansions_are_surfaced_for_the_ui(self):
        resp = self.client.get(reverse("inventory:parts_search"), {"q": "display"})
        self.assertIn("tft", resp.context["matched_extra_terms"])
