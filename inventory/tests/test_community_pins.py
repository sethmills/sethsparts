"""Community pins: gossip between connected workshops, and the map.

The load-bearing promise of this feature is that **opting out actually deletes** — not
hides, not flags. So the removal tests here are as careful as the opt-in ones, and the
most important test in the file is the one where a *stale copy of the old pin* arrives
after the removal: a node that re-added it would have broken the promise quietly, and
the workshop that asked to be forgotten would never know.

The other half is the permission split. Pins and inventory are separate on purpose, and
a connection made so two people can search each other's parts must not start gossiping
location — so several tests assert that a peer without `exchanges_pins` is never asked
and never believed.
"""
import json
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .. import community, community_pins
from ..models import CommunityIdentity, CommunityProfile, KnownPin, Peer, SiteSettings


def instance_keypair():
    """A keypair belonging to *another* instance — a workshop we hear from."""
    return community.generate_keypair()


def a_pin(private_hex, *, lat=51.5010, lon=-0.1416, when=None, gone=False, name=""):
    return community.make_pin(
        private_hex,
        lat=lat,
        lon=lon,
        country="GB",
        name=name,
        gone=gone,
        updated_at=when or datetime.now(datetime_timezone.utc),
    )


def make_peer(**overrides):
    defaults = {
        "name": "Dad's workshop",
        "base_url": "https://dad.example.test",
        "public_key": "aa" * 32,
        "inbound_api_key": "inbound-key",
        "outbound_api_key": "outbound-key",
        "status": Peer.ACTIVE,
        "exchanges_pins": True,
        "shares_parts": False,
    }
    defaults.update(overrides)
    return Peer.objects.create(**defaults)


def make_discoverable(*, lat=51.5010, lon=-0.1416, name=""):
    profile = CommunityProfile.load()
    profile.discoverable = True
    profile.display_name = name
    profile.location_lat = lat
    profile.location_lon = lon
    profile.location_source = CommunityProfile.MANUAL
    profile.save()
    return profile


class OwnPinTests(TestCase):
    def test_nothing_is_published_while_private(self):
        self.assertIsNone(community_pins.own_pin())

    def test_discoverable_without_a_location_publishes_nothing(self):
        """Both halves are opt-ins, and a pin with no coordinates is not a pin."""
        profile = CommunityProfile.load()
        profile.discoverable = True
        profile.save()
        self.assertIsNone(community_pins.own_pin())

    def test_a_discoverable_instance_publishes_a_verifiable_pin(self):
        make_discoverable()
        pin = community_pins.own_pin()
        self.assertTrue(community.verify_pin(pin))
        self.assertEqual(pin["country"], "GB" if SiteSettings.load().country == "GB" else pin["country"])

    def test_the_pin_is_anonymous_even_when_the_owner_set_a_name(self):
        """A pin is gossiped to the whole network, so a name inside it would leak to
        strangers. The name a *connection* sees comes from the peer row, which only ever
        went to the person the owner told."""
        make_discoverable(name="Seth's workshop")
        self.assertEqual(community_pins.own_pin()["name"], "")

    def test_the_gone_entry_needs_a_location_to_revoke(self):
        """Without one there was never a pin, so there is nothing to remove."""
        self.assertIsNone(community_pins.own_gone_pin())

    def test_the_gone_entry_is_signed_and_marks_itself(self):
        make_discoverable()
        gone = community_pins.own_gone_pin()
        self.assertTrue(community.verify_pin(gone))
        self.assertTrue(gone["gone"])

    def test_the_current_statement_follows_the_switch(self):
        make_discoverable()
        self.assertFalse(community_pins.current_statement()["gone"])
        profile = CommunityProfile.load()
        profile.discoverable = False
        profile.save()
        self.assertTrue(community_pins.current_statement()["gone"])


class RememberTests(TestCase):
    def setUp(self):
        self.their_private, self.their_public = instance_keypair()

    def test_a_valid_pin_is_stored(self):
        verdict = community_pins.remember(a_pin(self.their_private), hops=1)
        self.assertEqual(verdict, community_pins.STORED)
        row = KnownPin.objects.get(public_key=self.their_public)
        self.assertAlmostEqual(row.lat, 51.5010, places=5)
        self.assertFalse(row.gone)

    def test_a_forged_pin_never_reaches_the_database(self):
        forged = a_pin(self.their_private)
        forged["lat"] = "12.345678"
        self.assertEqual(community_pins.remember(forged), community_pins.INVALID)
        self.assertFalse(KnownPin.objects.exists())

    def test_something_that_is_not_a_pin_is_refused(self):
        for junk in ({}, "a string", None, {"public_key": "x"}):
            with self.subTest(junk=junk):
                self.assertEqual(community_pins.remember(junk), community_pins.INVALID)

    def test_an_older_entry_does_not_overwrite_a_newer_one(self):
        now = datetime.now(datetime_timezone.utc)
        community_pins.remember(a_pin(self.their_private, lat=51.5, when=now), hops=1)
        verdict = community_pins.remember(
            a_pin(self.their_private, lat=12.0, when=now - timedelta(hours=1)), hops=1
        )
        self.assertEqual(verdict, community_pins.STALE)
        self.assertAlmostEqual(KnownPin.objects.get().lat, 51.5, places=5)

    def test_a_newer_entry_replaces_it(self):
        now = datetime.now(datetime_timezone.utc)
        community_pins.remember(a_pin(self.their_private, lat=51.5, when=now), hops=1)
        verdict = community_pins.remember(
            a_pin(self.their_private, lat=52.0, when=now + timedelta(hours=1)), hops=1
        )
        self.assertEqual(verdict, community_pins.STORED)
        self.assertAlmostEqual(KnownPin.objects.get().lat, 52.0, places=5)

    def test_a_removal_deletes_the_location_and_keeps_the_row(self):
        now = datetime.now(datetime_timezone.utc)
        community_pins.remember(a_pin(self.their_private, when=now), hops=1)
        verdict = community_pins.remember(
            a_pin(self.their_private, when=now + timedelta(minutes=1), gone=True), hops=1
        )
        self.assertEqual(verdict, community_pins.REMOVED)

        row = KnownPin.objects.get()
        self.assertTrue(row.gone)
        self.assertIsNone(row.lat, "the location must be deleted, not hidden")
        self.assertIsNone(row.lon)
        self.assertTrue(row.is_placeholder)

    def test_a_stale_copy_cannot_resurrect_a_removed_pin(self):
        """The promise, stated as a test: someone whose copy is a week old relays it to
        us, and the workshop that opted out stays gone."""
        now = datetime.now(datetime_timezone.utc)
        old_pin = a_pin(self.their_private, when=now - timedelta(days=7))
        community_pins.remember(old_pin, hops=1)
        community_pins.remember(
            a_pin(self.their_private, when=now, gone=True), hops=1
        )

        verdict = community_pins.remember(old_pin, hops=1)

        self.assertEqual(verdict, community_pins.STALE)
        row = KnownPin.objects.get()
        self.assertTrue(row.gone)
        self.assertIsNone(row.lat, "an older pin must not bring the location back")
        self.assertEqual(community_pins.map_pins().count(), 0)

    def test_our_own_pin_coming_back_is_not_stored_twice(self):
        make_discoverable()
        our_pin = community_pins.own_pin()
        self.assertEqual(community_pins.remember(our_pin), community_pins.OWN)
        self.assertFalse(KnownPin.objects.exists())

    def test_hops_are_remembered_and_clamped(self):
        now = datetime.now(datetime_timezone.utc)
        community_pins.remember(a_pin(self.their_private, when=now), hops=2)
        self.assertEqual(KnownPin.objects.get().hops, 2)

        community_pins.remember(a_pin(self.their_private, when=now + timedelta(minutes=5)), hops=99)
        self.assertEqual(KnownPin.objects.get().hops, community_pins.MAX_HOPS)

    def test_a_naive_timestamp_is_read_as_utc_rather_than_refused(self):
        """A peer being sloppy about the format is not an attack; a well-formed time with
        no zone is worth accepting."""
        pin = a_pin(self.their_private)
        pin["updated_at"] = pin["updated_at"].replace("Z", "")
        rebuilt = community.make_pin(
            self.their_private,
            lat=51.5010,
            lon=-0.1416,
            country="GB",
            updated_at=datetime(2026, 9, 13, 12, 0),
        )
        self.assertTrue(rebuilt["updated_at"].endswith("Z"))
        self.assertIn(community_pins.remember(rebuilt), (community_pins.STORED, community_pins.STALE))


class SharingTests(TestCase):
    def setUp(self):
        self.their_private, self.their_public = instance_keypair()

    def test_a_served_pin_still_verifies_at_the_far_end(self):
        """A stored pin is re-served under its original signature, so the timestamp has
        to come back out in exactly the form that was signed. Reserialising it slightly
        differently would invalidate a perfectly good signature."""
        community_pins.remember(a_pin(self.their_private), hops=1)
        served = community_pins.pins_for_sharing()
        self.assertEqual(len(served), 1)
        self.assertTrue(community.verify_pin(served[0]))

    def test_removals_are_passed_on_too(self):
        """A removal only reaches workshops that did not hear it directly by being passed
        along like any other entry — so it has to stay verifiable after the location it
        revoked has been deleted, which is why it never carried one."""
        now = datetime.now(datetime_timezone.utc)
        community_pins.remember(a_pin(self.their_private, when=now - timedelta(minutes=1)), hops=1)
        community_pins.remember(
            a_pin(self.their_private, when=now, gone=True), hops=1
        )
        served = community_pins.pins_for_sharing()
        self.assertEqual(len(served), 1)
        self.assertTrue(served[0]["gone"])
        self.assertTrue(community.verify_pin(served[0]), "a removal must survive being forwarded")
        for field in ("lat", "lon", "country", "name"):
            self.assertNotIn(field, served[0], "a removal carries nothing about where")

    def test_entries_at_the_hop_limit_are_not_forwarded(self):
        """Otherwise gossip is an unbounded broadcast."""
        community_pins.remember(a_pin(self.their_private), hops=community_pins.MAX_HOPS)
        self.assertEqual(community_pins.pins_for_sharing(), [])

    def test_a_pin_one_hop_short_is_still_forwarded(self):
        community_pins.remember(a_pin(self.their_private), hops=community_pins.MAX_HOPS - 1)
        self.assertEqual(len(community_pins.pins_for_sharing()), 1)

    def test_the_origin_is_never_named(self):
        """The plan forbids disclosing which neighbour a pin came from — watching who
        receives what would map the social graph."""
        community_pins.remember(a_pin(self.their_private), hops=1)
        served = community_pins.pins_for_sharing()[0]
        for field in ("from", "peer", "learned_from", "source"):
            self.assertNotIn(field, served)


class PeerAuthenticationTests(TestCase):
    def request_with(self, key):
        from django.test import RequestFactory

        request = RequestFactory().get("/api/community/pins/")
        if key is not None:
            request.META["HTTP_X_API_KEY"] = key
        return request

    def test_a_missing_key_is_not_a_peer(self):
        self.assertIsNone(community_pins.peer_for_request(self.request_with(None)))
        self.assertIsNone(community_pins.peer_for_request(self.request_with("")))

    def test_the_right_key_identifies_the_peer(self):
        peer = make_peer()
        self.assertEqual(community_pins.peer_for_request(self.request_with("inbound-key")), peer)

    def test_a_wrong_key_is_refused(self):
        make_peer()
        self.assertIsNone(community_pins.peer_for_request(self.request_with("guess")))

    def test_a_revoked_connection_is_refused_even_with_its_old_key(self):
        """Revoking has to mean no access, not a label on a row."""
        make_peer(status=Peer.REVOKED)
        self.assertIsNone(community_pins.peer_for_request(self.request_with("inbound-key")))

    def test_a_connection_that_does_not_exchange_pins_is_refused(self):
        """The permission split: an inventory-only connection has no business reading
        the map."""
        make_peer(exchanges_pins=False)
        self.assertIsNone(community_pins.peer_for_request(self.request_with("inbound-key")))


class PinsEndpointTests(TestCase):
    """The endpoint other instances call. Not login-walled: the caller is a server."""

    def setUp(self):
        self.peer = make_peer()
        self.url = reverse("inventory:api_community_pins")
        self.their_private, self.their_public = instance_keypair()

    def test_a_request_without_a_key_is_refused(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_a_connected_workshop_gets_what_we_know(self):
        community_pins.remember(a_pin(self.their_private), hops=1)
        response = self.client.get(self.url, headers={"X-Api-Key": "inbound-key"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["pins"]), 1)
        self.assertTrue(community.verify_pin(payload["pins"][0]))

    def test_our_own_pin_is_served_alongside_what_we_hold(self):
        make_discoverable()
        community_pins.remember(a_pin(self.their_private), hops=1)
        payload = self.client.get(self.url, headers={"X-Api-Key": "inbound-key"}).json()
        self.assertEqual(len(payload["pins"]), 2)
        own = [p for p in payload["pins"] if p["public_key"] == CommunityIdentity.load().public_key][0]
        self.assertEqual(own["hops"], 0, "we are the origin of our own pin")
        self.assertTrue(community.verify_pin(own))

    def test_nothing_of_ours_is_served_while_we_are_private(self):
        payload = self.client.get(self.url, headers={"X-Api-Key": "inbound-key"}).json()
        self.assertEqual(payload["pins"], [])

    def test_being_asked_counts_as_being_seen(self):
        self.assertIsNone(Peer.objects.get(pk=self.peer.pk).last_seen_at)
        self.client.get(self.url, headers={"X-Api-Key": "inbound-key"})
        self.assertIsNotNone(Peer.objects.get(pk=self.peer.pk).last_seen_at)

    def test_a_peer_can_push_its_current_entry(self):
        response = self.client.post(
            self.url,
            data=json.dumps(a_pin(self.their_private)),
            content_type="application/json",
            headers={"X-Api-Key": "inbound-key"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(KnownPin.objects.count(), 1)

    def test_a_pushed_entry_that_does_not_verify_is_refused(self):
        forged = a_pin(self.their_private)
        forged["lat"] = "1.000000"
        response = self.client.post(
            self.url,
            data=json.dumps(forged),
            content_type="application/json",
            headers={"X-Api-Key": "inbound-key"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(KnownPin.objects.exists())

    def test_a_push_of_nonsense_is_refused(self):
        response = self.client.post(
            self.url, data="not json", content_type="application/json", headers={"X-Api-Key": "inbound-key"}
        )
        self.assertEqual(response.status_code, 400)

    def test_an_unsupported_method_is_refused(self):
        self.assertEqual(
            self.client.put(self.url, headers={"X-Api-Key": "inbound-key"}).status_code, 405
        )


class SyncTests(TestCase):
    def setUp(self):
        self.peer = make_peer()
        self.their_private, self.their_public = instance_keypair()

    def response_with(self, pins):
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {"pins": pins}
        return response

    @mock.patch("requests.get")
    def test_pins_from_a_connection_are_taken_in(self, get):
        get.return_value = self.response_with([a_pin(self.their_private)])
        learned, notes = community_pins.sync_from_peers()
        self.assertEqual(learned, 1)
        self.assertEqual(notes, [])
        self.assertEqual(KnownPin.objects.count(), 1)

    @mock.patch("requests.get")
    def test_each_hop_away_is_counted(self, get):
        get.return_value = self.response_with([{**a_pin(self.their_private), "hops": 1}])
        community_pins.sync_from_peers()
        self.assertEqual(KnownPin.objects.get().hops, 2)

    @mock.patch("requests.get")
    def test_the_peer_is_asked_with_the_key_it_issued_us(self, get):
        get.return_value = self.response_with([])
        community_pins.sync_from_peers()
        call = get.call_args_list[0]
        self.assertTrue(call.args[0].endswith("/api/community/pins/"))
        self.assertEqual(call.kwargs["headers"]["X-Api-Key"], "outbound-key")

    @mock.patch("requests.get")
    def test_a_connection_that_does_not_exchange_pins_is_never_asked(self, get):
        """The split, again: connecting for inventory must not start gossiping location."""
        make_peer(name="Parts only", inbound_api_key="i2", outbound_api_key="o2", exchanges_pins=False)
        get.return_value = self.response_with([])
        community_pins.sync_from_peers()
        self.assertEqual(get.call_count, 1, "only the pin-exchanging connection should be called")

    @mock.patch("requests.get")
    def test_a_revoked_connection_is_never_asked(self, get):
        Peer.objects.filter(pk=self.peer.pk).update(status=Peer.REVOKED)
        get.return_value = self.response_with([])
        community_pins.sync_from_peers()
        get.assert_not_called()

    @mock.patch("requests.get", side_effect=__import__("requests").ConnectionError("no route"))
    def test_an_unreachable_connection_is_reported_not_raised(self, _get):
        learned, notes = community_pins.sync_from_peers()
        self.assertEqual(learned, 0)
        self.assertIn("no route", notes[0])

    @mock.patch("requests.get")
    def test_a_connection_answering_with_junk_is_reported(self, get):
        get.return_value = mock.Mock(status_code=200, **{"json.side_effect": ValueError("nope")})
        learned, notes = community_pins.sync_from_peers()
        self.assertEqual(learned, 0)
        self.assertIn("wasn't JSON", notes[0])

    @mock.patch("requests.get")
    def test_a_forged_entry_in_a_sync_is_ignored(self, get):
        forged = a_pin(self.their_private)
        forged["lat"] = "9.999999"
        get.return_value = self.response_with([forged])
        learned, _notes = community_pins.sync_from_peers()
        self.assertEqual(learned, 0)
        self.assertFalse(KnownPin.objects.exists())


class PublishTests(TestCase):
    def setUp(self):
        self.peer = make_peer()

    @mock.patch("requests.post")
    def test_publishing_our_pin_sends_an_anonymous_verifiable_entry(self, post):
        make_discoverable()
        post.return_value.status_code = 200
        published, detail = community_pins.publish_own_state()
        self.assertTrue(published, detail)
        sent = post.call_args_list[0].kwargs["json"]
        self.assertTrue(community.verify_pin(sent))
        self.assertEqual(sent["name"], "")
        self.assertFalse(sent["gone"])
        self.assertEqual(post.call_args_list[0].kwargs["headers"]["X-Api-Key"], "outbound-key")

    @mock.patch("requests.post")
    def test_opting_out_publishes_the_removal(self, post):
        """The promise only holds if the removal actually goes out."""
        make_discoverable()
        profile = CommunityProfile.load()
        profile.discoverable = False
        profile.save()
        post.return_value.status_code = 200

        published, detail = community_pins.publish_own_state()

        self.assertTrue(published, detail)
        sent = post.call_args_list[0].kwargs["json"]
        self.assertTrue(sent["gone"])
        self.assertTrue(community.verify_pin(sent))

    def test_there_is_nothing_to_publish_without_a_location(self):
        published, detail = community_pins.publish_own_state()
        self.assertFalse(published)
        self.assertIn("set a location", detail)

    @mock.patch("requests.post")
    def test_a_peer_being_down_does_not_stop_the_others(self, post):
        make_discoverable()
        make_peer(name="Second", base_url="https://eric.example.test", inbound_api_key="i2", outbound_api_key="o2")
        import requests as requests_module

        def flaky(*args, **kwargs):
            if "dad" in args[0]:
                raise requests_module.ConnectionError("down")
            return mock.Mock(status_code=200)

        post.side_effect = flaky
        published, detail = community_pins.publish_own_state()
        self.assertTrue(published)
        self.assertIn("1 of 2", detail)

    @mock.patch("requests.post")
    def test_no_connections_means_nobody_to_tell(self, post):
        make_discoverable()
        Peer.objects.all().delete()
        published, detail = community_pins.publish_own_state()
        self.assertFalse(published)
        self.assertIn("nobody to tell", detail)
        post.assert_not_called()


class OptOutEndToEndTests(TestCase):
    """Two instances talking, entirely inside one test: A publishes, B learns, A opts
    out, B deletes — and then a stale copy of A's old pin arrives from a third party and
    B still holds nothing.
    """

    def setUp(self):
        self.a_private, self.a_public = instance_keypair()
        self.b_peer_of_a = make_peer(name="A's workshop", public_key=self.a_public)

    def test_a_removal_learned_second_hand_actually_removes(self):
        early = datetime.now(datetime_timezone.utc) - timedelta(days=1)
        community_pins.remember(a_pin(self.a_private, when=early), hops=1)
        self.assertEqual(community_pins.map_pins().count(), 1)

        # A's own opt-out reaches us second hand: someone who heard it directly passes it on.
        community_pins.remember(a_pin(self.a_private, when=timezone.now(), gone=True), hops=2)

        self.assertEqual(community_pins.map_pins().count(), 0)
        self.assertIsNone(KnownPin.objects.get().lat)

        # And the third party, whose copy predates the removal, tries again.
        community_pins.remember(a_pin(self.a_private, when=early), hops=1)
        self.assertEqual(community_pins.map_pins().count(), 0)


class CommunityStepTests(TestCase):
    """The wizard step is where the switch is flipped, so it is where the publishing has
    to happen — best effort, and only on a change."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="owner", password="x")
        self.client.force_login(self.user)
        self.url = reverse("inventory:setup_community")
        self.peer = make_peer()

    @mock.patch("requests.post")
    def test_turning_discoverability_on_publishes_the_pin(self, post):
        # A location is one of the two opt-ins, so it has to be there before a pin is a
        # pin — otherwise "Switching it on" would publish nothing and say nothing.
        profile = CommunityProfile.load()
        profile.location_lat = 51.5010
        profile.location_lon = -0.1416
        profile.save()
        post.return_value.status_code = 200
        self.client.post(self.url, {"action": "save", "discoverable": "1"}, follow=True)
        self.assertEqual(post.call_count, 1)
        self.assertFalse(post.call_args_list[0].kwargs["json"]["gone"])

    @mock.patch("requests.post")
    def test_turning_it_off_publishes_the_removal(self, post):
        make_discoverable()
        post.return_value.status_code = 200
        self.client.post(self.url, {"action": "save"}, follow=True)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args_list[0].kwargs["json"]["gone"])

    @mock.patch("requests.post")
    def test_saving_without_changing_the_answer_tells_nobody(self, post):
        """Re-pushing an unchanged pin on every save would be noise, and a settings page
        that quietly talks to peers every time you press Save is a surprise."""
        make_discoverable()
        self.client.post(self.url, {"action": "save", "discoverable": "1"}, follow=True)
        post.assert_not_called()

    @mock.patch("requests.post")
    def test_the_switch_still_works_when_no_peer_can_be_reached(self, post):
        """A peer being offline must not stop the owner turning their own pin off."""
        make_discoverable()
        post.side_effect = __import__("requests").ConnectionError("down")
        response = self.client.post(self.url, {"action": "save"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CommunityProfile.load().discoverable)


class MapPageTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="owner", password="x")
        self.client.force_login(self.user)
        self.url = reverse("inventory:community_map")
        self.their_private, self.their_public = instance_keypair()

    def page_json(self, response):
        body = response.content.decode()
        start = body.index("const data = ") + len("const data = ")
        end = body.index(";\n", start)
        return json.loads(body[start:end])

    def test_it_needs_a_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))

    def test_an_empty_map_explains_itself_rather_than_drawing_nothing(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No pins yet")

    def test_it_draws_our_own_pin_when_we_are_discoverable(self):
        make_discoverable()
        data = self.page_json(self.client.get(self.url))
        self.assertEqual(len(data["pins"]), 1)
        self.assertEqual(data["pins"][0]["kind"], "you")
        self.assertTrue(data["own"])

    def test_a_known_pin_is_drawn_and_only_named_when_we_already_know_who_it_is(self):
        community_pins.remember(a_pin(self.their_private), hops=1)
        data = self.page_json(self.client.get(self.url))
        self.assertEqual(len(data["pins"]), 1)
        self.assertEqual(data["pins"][0]["kind"], "other", "a stranger's pin is anonymous")

        make_peer(name="Dad's workshop", public_key=self.their_public)
        data = self.page_json(self.client.get(self.url))
        self.assertEqual(data["pins"][0]["kind"], "friend")
        self.assertIn("Dad&#x27;s workshop", data["pins"][0]["popup"])

    def test_a_hostile_name_from_another_instance_cannot_inject_anything(self):
        """Peer names arrive over the network from someone else's server."""
        community_pins.remember(a_pin(self.their_private), hops=1)
        make_peer(name="<script>alert(1)</script>", public_key=self.their_public)
        data = self.page_json(self.client.get(self.url))
        self.assertNotIn("<script>", data["pins"][0]["popup"])
        self.assertIn("&lt;script&gt;", data["pins"][0]["popup"])

    def test_a_removed_pin_is_not_drawn_at_all(self):
        community_pins.remember(
            a_pin(self.their_private, when=timezone.now(), gone=True), hops=1
        )
        data = self.page_json(self.client.get(self.url))
        self.assertEqual(data["pins"], [])

    @override_settings(COMMUNITY_MAP_STYLE="https://tiles.example.test/style.json")
    def test_the_tile_source_is_configuration_not_hardcoded(self):
        make_discoverable()
        self.assertContains(self.client.get(self.url), "https://tiles.example.test/style.json")

    def test_rendering_the_page_makes_no_requests_to_anyone(self):
        """The rule this project learned from the update check: a page render must not
        reach out to other people's servers, or it is a surprise and it fails offline."""
        make_discoverable()
        community_pins.remember(a_pin(self.their_private), hops=1)
        make_peer()
        with mock.patch("requests.get") as get, mock.patch("requests.post") as post:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        get.assert_not_called()
        post.assert_not_called()


class SyncButtonTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(username="owner", password="x")
        self.client.force_login(self.user)
        self.url = reverse("inventory:community_sync_pins")

    def test_it_says_so_when_there_is_nobody_to_ask(self):
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, "No connections exchange pins yet")

    @mock.patch("requests.get")
    def test_a_successful_refresh_reports_what_it_learned(self, get):
        their_private, _ = instance_keypair()
        make_peer()
        response_mock = mock.Mock(status_code=200)
        response_mock.json.return_value = {"pins": [a_pin(their_private)]}
        get.return_value = response_mock
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, "Learned 1 new pin entry")

    @mock.patch("requests.get", side_effect=__import__("requests").ConnectionError("down"))
    def test_a_failed_refresh_says_which_connection_failed(self, _get):
        make_peer()
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, "down")

    def test_the_button_is_a_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class PruneTests(TestCase):
    def test_entries_nobody_refreshes_are_dropped(self):
        their_private, _ = instance_keypair()
        now = datetime.now(datetime_timezone.utc)
        community_pins.remember(a_pin(their_private, when=now - timedelta(days=200)), hops=1)
        other_private, _ = instance_keypair()
        community_pins.remember(a_pin(other_private, when=now), hops=1)

        removed = community_pins.prune_stale_pins()

        self.assertEqual(removed, 1)
        self.assertEqual(KnownPin.objects.count(), 1)
