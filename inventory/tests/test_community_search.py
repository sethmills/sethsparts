"""Community search: the inbound endpoint peers call, and the outbound fan-out.

Two promises, both about privacy. A peer sees only the *shareable* subset of the
inventory — never an unshared category, never a precise count, never a location —
and the search is gated on `shares_parts`, so connecting for the map never grants
inventory access. The outbound half is the inverse: asking a connection is a live
query, and one dead workshop must not hide what the others answered.
"""
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from .. import community_search
from ..models import Category, Peer, PeerSearchLog

from .factories import make_container, make_part, make_stock, make_user


def make_peer(**overrides):
    defaults = {
        "name": "Dad's workshop",
        "base_url": "https://dad.example.test",
        "public_key": "aa" * 32,
        "inbound_api_key": "inbound-key",
        "outbound_api_key": "outbound-key",
        "status": Peer.ACTIVE,
        "exchanges_pins": False,
        "shares_parts": True,
    }
    defaults.update(overrides)
    return Peer.objects.create(**defaults)


_counter = {"n": 9000}


def make_shareable_part(name, quantities):
    """A part in a shareable category, holding the given quantities (ints or None)."""
    _counter["n"] += 1
    category = Category.objects.create(name=f"shared-{name}", is_shareable=True)
    part = make_part(name=name, category=category, manufacturer="Acme")
    container = make_container(number=_counter["n"])
    for q in quantities:
        make_stock(part, container, quantity=q)
    return part


class FuzzQuantityTests(TestCase):
    def test_an_empty_stock_list_is_none(self):
        self.assertEqual(community_search.fuzz_quantity([]), "none")

    def test_present_but_uncounted_is_some(self):
        """An uncounted part is still a part worth asking about."""
        self.assertEqual(community_search.fuzz_quantity([None]), "some")

    def test_zero_stock_is_none(self):
        self.assertEqual(community_search.fuzz_quantity([0, 0]), "none")

    def test_a_small_amount_is_a_few(self):
        self.assertEqual(community_search.fuzz_quantity([1, 3]), "a few")

    def test_a_larger_amount_is_some(self):
        self.assertEqual(community_search.fuzz_quantity([5]), "some")
        self.assertEqual(community_search.fuzz_quantity([100]), "some")

    def test_an_uncounted_row_does_not_hide_a_counted_one(self):
        self.assertEqual(community_search.fuzz_quantity([None, 2]), "a few")

    def test_a_negative_total_is_none_not_some(self):
        """A mid-audit negative adjustment must never read as 'have some'."""
        self.assertEqual(community_search.fuzz_quantity([-2, 1]), "none")


class ShareableResultsTests(TestCase):
    def test_only_shareable_categories_are_returned(self):
        make_shareable_part("Resistor", [3])
        hidden = Category.objects.create(name="hidden", is_shareable=False)
        make_part(name="Secret part", category=hidden)

        names = {p.name for p in community_search.shareable_results("")}
        self.assertIn("Resistor", names)
        self.assertNotIn("Secret part", names)

    def test_a_part_with_no_category_is_never_shareable(self):
        """The safe default: shareability derives from the category, so an
        uncategorised part cannot be shared by accident."""
        make_part(name="Orphan")
        self.assertFalse(community_search.shareable_results("Orphan").exists())

    def test_the_query_matches_the_same_way_local_search_does(self):
        make_shareable_part("Raspberry Pi Zero", [1])
        make_shareable_part("Relay module", [10])

        names = {p.name for p in community_search.shareable_results("pi")}
        self.assertIn("Raspberry Pi Zero", names)
        self.assertNotIn("Relay module", names)


class PeerSearchAuthTests(TestCase):
    def request_with(self, key):
        from django.test import RequestFactory

        request = RequestFactory().get("/api/community/peer-search/")
        if key is not None:
            request.META["HTTP_X_API_KEY"] = key
        return request

    def test_a_missing_key_is_not_a_peer(self):
        self.assertIsNone(community_search.peer_for_search(self.request_with(None)))
        self.assertIsNone(community_search.peer_for_search(self.request_with("")))

    def test_the_right_key_identifies_the_peer(self):
        peer = make_peer()
        self.assertEqual(community_search.peer_for_search(self.request_with("inbound-key")), peer)

    def test_a_wrong_key_is_refused(self):
        make_peer()
        self.assertIsNone(community_search.peer_for_search(self.request_with("guess")))

    def test_a_revoked_connection_is_refused_even_with_its_old_key(self):
        make_peer(status=Peer.REVOKED)
        self.assertIsNone(community_search.peer_for_search(self.request_with("inbound-key")))

    def test_a_connection_that_does_not_share_parts_is_refused(self):
        """The split: a pins-only connection has no business searching inventory."""
        make_peer(shares_parts=False)
        self.assertIsNone(community_search.peer_for_search(self.request_with("inbound-key")))


class PeerSearchEndpointTests(TestCase):
    def setUp(self):
        self.peer = make_peer()
        self.url = reverse("inventory:api_community_peer_search")

    def test_a_request_without_a_key_is_refused(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_an_empty_query_is_refused(self):
        response = self.client.get(self.url, {"q": ""}, headers={"X-Api-Key": "inbound-key"})
        self.assertEqual(response.status_code, 400)

    def test_results_are_fuzzed_and_never_locate(self):
        """The promise: a peer learns 'worth asking', not stock levels or drawers."""
        make_shareable_part("Raspberry Pi Zero", [3])
        response = self.client.get(self.url, {"q": "pi"}, headers={"X-Api-Key": "inbound-key"})
        self.assertEqual(response.status_code, 200)

        match = response.json()["matches"][0]
        self.assertEqual(match["name"], "Raspberry Pi Zero")
        self.assertEqual(match["quantity_summary"], "a few")

        for field in ("name", "manufacturer", "category", "quantity_summary"):
            self.assertIn(field, match)
        for field in ("drawer", "bin", "container", "location", "quantity", "barcode"):
            self.assertNotIn(field, match)
        self.assertNotIsInstance(match["quantity_summary"], int)

    def test_unshared_categories_are_never_returned(self):
        make_shareable_part("Shared thing", [10])
        hidden = Category.objects.create(name="hidden", is_shareable=False)
        make_part(name="Private thing", category=hidden)

        payload = self.client.get(self.url, {"q": "thing"}, headers={"X-Api-Key": "inbound-key"}).json()
        names = [m["name"] for m in payload["matches"]]
        self.assertIn("Shared thing", names)
        self.assertNotIn("Private thing", names)

    def test_every_search_is_logged_against_the_peer(self):
        """The owner can check what a connection has looked for, not take it on trust."""
        make_shareable_part("Servo", [2])
        self.client.get(self.url, {"q": "servo"}, headers={"X-Api-Key": "inbound-key"})

        entry = PeerSearchLog.objects.get(peer=self.peer)
        self.assertEqual(entry.query, "servo")
        self.assertEqual(entry.result_count, 1)


class SearchPeersTests(TestCase):
    def setUp(self):
        self.peer = make_peer()

    def response_with(self, matches):
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {"matches": matches}
        return response

    @mock.patch("requests.get")
    def test_results_are_gathered_from_each_connection(self, get):
        get.return_value = self.response_with(
            [{"name": "Servo", "manufacturer": "Acme", "category": "Parts", "quantity_summary": "some"}]
        )
        results, notes = community_search.search_peers("servo")
        self.assertEqual(notes, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Dad's workshop")
        self.assertEqual(results[0]["matches"][0]["name"], "Servo")

    @mock.patch("requests.get")
    def test_the_peer_is_asked_with_the_key_it_issued_us(self, get):
        get.return_value = self.response_with([])
        community_search.search_peers("servo")
        call = get.call_args_list[0]
        self.assertTrue(call.args[0].endswith("/api/community/peer-search/"))
        self.assertEqual(call.kwargs["headers"]["X-Api-Key"], "outbound-key")

    @mock.patch("requests.get")
    def test_a_connection_that_does_not_share_parts_is_never_asked(self, get):
        make_peer(name="Pins only", inbound_api_key="i2", outbound_api_key="o2", shares_parts=False)
        get.return_value = self.response_with([])
        community_search.search_peers("servo")
        self.assertEqual(get.call_count, 1)

    @mock.patch("requests.get", side_effect=__import__("requests").ConnectionError("no route"))
    def test_an_unreachable_connection_is_reported_not_raised(self, _get):
        results, notes = community_search.search_peers("servo")
        self.assertEqual(results, [])
        self.assertIn("no route", notes[0])

    @mock.patch("requests.get")
    def test_a_connection_answering_with_junk_is_reported(self, get):
        get.return_value = mock.Mock(status_code=200, **{"json.side_effect": ValueError("nope")})
        results, notes = community_search.search_peers("servo")
        self.assertEqual(results, [])
        self.assertIn("wasn't JSON", notes[0])

    @mock.patch("requests.get")
    def test_an_http_error_is_reported(self, get):
        get.return_value = mock.Mock(status_code=403)
        results, notes = community_search.search_peers("servo")
        self.assertEqual(results, [])
        self.assertIn("HTTP 403", notes[0])


class NetworkSearchPageTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.url = reverse("inventory:community_network_search")

    def test_it_needs_a_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))

    def test_rendering_without_a_query_makes_no_requests(self):
        """Opening the page must not reach out to anyone — only searching does."""
        make_peer()
        with mock.patch("requests.get") as get:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        get.assert_not_called()

    @mock.patch("requests.get")
    def test_a_query_searches_peers_and_renders_results(self, get):
        make_peer()
        get.return_value = mock.Mock(
            status_code=200,
            **{"json.return_value": {"matches": [{"name": "Servo", "manufacturer": "Acme", "category": "Parts", "quantity_summary": "some"}]}},
        )
        response = self.client.get(self.url, {"q": "servo"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Servo")
        self.assertContains(response, "some")

    @mock.patch("requests.get")
    def test_a_failed_peer_is_noted_inline(self, get):
        make_peer()
        get.side_effect = __import__("requests").ConnectionError("no route")
        response = self.client.get(self.url, {"q": "servo"})
        self.assertContains(response, "no route")
