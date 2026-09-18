"""Pairing two workshops.

The property that matters most is where the two credentials land. Each side ends up
holding a key it issued and a key it was issued, and neither can act as the other —
get that backwards and one workshop can sign requests as another, which is the whole
threat model in one bug.

`/api/community/claim/` is also the only unauthenticated write outside the setup
wizard, so its refusals are tested from every direction: no code, wrong code, spent
code, expired code, and too many attempts.
"""
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from inventory import community_api
from inventory.models import CommunityIdentity, Peer, PairingCode

from .factories import make_user


class FakeHostResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code

    def json(self):
        return self._payload


class PairingTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_login(self.user)

    def claim(self, **overrides):
        payload = {
            "code": PairingCode.issue().code,
            "name": "Eric's workshop",
            "base_url": "https://eric.example.com",
            "public_key": "ab" * 32,
            "callback_key": "eric-issued-this",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("inventory:api_community_claim"),
            data=json.dumps(payload),
            content_type="application/json",
        )


class ClaimEndpointTests(PairingTestCase):
    def test_a_valid_code_connects_the_workshop(self):
        response = self.claim()
        self.assertEqual(response.status_code, 200)
        peer = Peer.objects.get()
        self.assertEqual(peer.name, "Eric's workshop")
        self.assertEqual(peer.status, Peer.ACTIVE)

    def test_a_new_connection_exchanges_pins_but_cannot_search_parts(self):
        """The default that keeps connecting for the map from handing over inventory."""
        self.claim()
        peer = Peer.objects.get()
        self.assertTrue(peer.exchanges_pins)
        self.assertFalse(peer.shares_parts)

    def test_it_returns_the_key_the_joiner_needs_to_call_back(self):
        response = self.claim()
        payload = json.loads(response.content)
        peer = Peer.objects.get()
        self.assertEqual(payload["callback_key"], peer.inbound_api_key)
        self.assertTrue(payload["public_key"])

    def test_the_joiners_key_is_stored_for_calling_them(self):
        """The credential they issued to us, which is what we send when we call them."""
        self.claim(callback_key="eric-issued-this")
        self.assertEqual(Peer.objects.get().outbound_api_key, "eric-issued-this")

    def test_the_code_is_spent(self):
        code = PairingCode.issue()
        self.claim(code=code.code)
        code.refresh_from_db()
        self.assertIsNotNone(code.claimed_at)
        self.assertEqual(code.claimed_by, Peer.objects.get())

    def test_a_code_cannot_be_used_twice(self):
        """Single use is the real protection on a short code, so it has to be atomic
        and it has to hold."""
        code = PairingCode.issue()
        self.assertEqual(self.claim(code=code.code).status_code, 200)
        second = self.claim(code=code.code, public_key="cd" * 32)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Peer.objects.count(), 1)

    def test_an_unknown_code_is_refused(self):
        self.assertEqual(self.claim(code="ZZZZZZZZ").status_code, 400)
        self.assertFalse(Peer.objects.exists())

    def test_an_expired_code_is_refused(self):
        code = PairingCode.issue()
        code.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        code.save()
        self.assertEqual(self.claim(code=code.code).status_code, 400)

    def test_a_missing_code_is_refused(self):
        self.assertEqual(self.claim(code="").status_code, 400)

    def test_a_code_typed_the_way_a_person_would_is_accepted(self):
        """Read aloud, written down, typed back — with a dash, a space, or lower case."""
        code = PairingCode.issue()
        typed = f"{code.code[:4].lower()} {code.code[4:].lower()}"
        self.assertEqual(self.claim(code=typed).status_code, 200)

    def test_a_request_with_no_address_is_refused(self):
        response = self.claim(base_url="")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Peer.objects.exists())

    def test_a_request_with_no_public_key_is_refused(self):
        """Without a key there is no way to verify the pins they later publish."""
        self.assertEqual(self.claim(public_key="").status_code, 400)

    def test_it_does_not_need_a_login_or_a_csrf_token(self):
        """The caller is another server with no session and no cookie. CSRF protects
        browsers, and there is no browser here."""
        self.client.logout()
        response = self.claim()
        self.assertEqual(response.status_code, 200)

    def test_it_refuses_to_be_hammered(self):
        """40 bits is ample when a code is single-use and lasts a day, but only if
        guessing is expensive."""
        code = PairingCode.issue().code
        for _ in range(community_api_attempt_limit()):
            self.client.post(
                reverse("inventory:api_community_claim"),
                data=json.dumps({"code": "ZZZZZZZZ", "base_url": "https://x.test", "public_key": "ab" * 32}),
                content_type="application/json",
            )
        refused = self.claim(code=code)
        self.assertEqual(refused.status_code, 429)

    def test_broken_json_is_refused_not_crashed(self):
        response = self.client.post(
            reverse("inventory:api_community_claim"), data=b"not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_the_endpoint_is_reachable_on_a_virgin_install(self):
        """Exempt from the setup redirect: a peer connecting during your first five
        minutes should not be bounced to a wizard."""
        self.assertTrue(
            __import__("inventory.middleware", fromlist=["x"]).SetupRedirectMiddleware._is_exempt(
                "/api/community/claim/"
            )
        )

    def test_reconnecting_updates_rather_than_duplicating(self):
        key = "ab" * 32
        self.claim(public_key=key)
        self.claim(code=PairingCode.issue().code, public_key=key, name="Renamed")
        self.assertEqual(Peer.objects.count(), 1)
        self.assertEqual(Peer.objects.get().name, "Renamed")

    def test_reconnecting_does_not_hand_back_search_access(self):
        """A second code is a reconnection, not a reason to re-grant anything."""
        key = "ab" * 32
        self.claim(public_key=key)
        peer = Peer.objects.get()
        peer.shares_parts = True
        peer.save()

        self.claim(code=PairingCode.issue().code, public_key=key)
        self.assertTrue(Peer.objects.get().shares_parts, "an existing grant survives")

        self.claim(code=PairingCode.issue().code, public_key="cd" * 32)
        self.assertFalse(Peer.objects.get(public_key="cd" * 32).shares_parts, "a new one does not")


def community_api_attempt_limit():
    from inventory.views.community import CLAIM_ATTEMPTS

    return CLAIM_ATTEMPTS


class JoinFlowTests(PairingTestCase):
    """Joiner side: we have someone's address and code, and we call them."""

    def join(self, response=None, **overrides):
        data = {"host_url": "https://host.example.com", "code": "K7F29QX3"}
        data.update(overrides)
        patcher = mock.patch("requests.post")
        fake = patcher.start()
        self.addCleanup(patcher.stop)
        if response is not None:
            fake.return_value = response
        return fake, self.client.post(reverse("inventory:community_join"), data, follow=True)

    def test_a_successful_join_creates_an_active_peer(self):
        fake, _ = self.join(FakeHostResponse({"name": "Dad's workshop", "public_key": "ef" * 32, "callback_key": "host-issued"}))
        peer = Peer.objects.get(is_seed=False)
        self.assertEqual(peer.name, "Dad's workshop")
        self.assertEqual(peer.status, Peer.ACTIVE)
        self.assertTrue(peer.exchanges_pins)
        self.assertFalse(peer.shares_parts)

    def test_the_hosts_key_is_stored_for_calling_them(self):
        self.join(FakeHostResponse({"name": "H", "public_key": "ef" * 32, "callback_key": "host-issued"}))
        self.assertEqual(Peer.objects.get(is_seed=False).outbound_api_key, "host-issued")

    def test_our_own_key_is_stored_for_them_to_call_us(self):
        """The two credentials have to land on the right sides, or one workshop can
        act as the other."""
        self.join(FakeHostResponse({"name": "H", "callback_key": "host-issued"}))
        peer = Peer.objects.get(is_seed=False)
        self.assertTrue(peer.inbound_api_key)
        self.assertNotEqual(peer.inbound_api_key, peer.outbound_api_key)

    def test_the_code_we_send_is_normalised(self):
        fake, _ = self.join(FakeHostResponse({"name": "H"}), code="k7f2 9qx3")
        sent = fake.call_args.kwargs["json"]
        self.assertEqual(sent["code"], "K7F29QX3")

    def test_a_bare_host_gets_a_scheme(self):
        fake, _ = self.join(FakeHostResponse({"name": "H"}), host_url="host.example.com")
        self.assertEqual(fake.call_args[0][0], "http://host.example.com/api/community/claim/")

    def test_we_tell_them_where_to_reach_us(self):
        fake, _ = self.join(FakeHostResponse({"name": "H"}))
        sent = fake.call_args.kwargs["json"]
        self.assertTrue(sent["base_url"].startswith("http"))
        self.assertTrue(sent["public_key"])

    def test_a_refused_join_leaves_nothing_behind(self):
        """Half-connected state would be worse than a clean failure."""
        self.join(FakeHostResponse({"error": "That code isn't valid."}, status_code=400))
        self.assertFalse(Peer.objects.filter(is_seed=False).exists())

    def test_the_hosts_reason_is_shown(self):
        _, response = self.join(FakeHostResponse({"error": "That code isn't valid."}, status_code=400))
        self.assertContains(response, "isn&#x27;t valid")

    def test_an_unreachable_host_is_reported(self):
        import requests

        patcher = mock.patch("requests.post", side_effect=requests.ConnectionError("no route"))
        patcher.start()
        self.addCleanup(patcher.stop)
        response = self.client.post(
            reverse("inventory:community_join"), {"host_url": "https://host.example.com", "code": "K7F29QX3"}, follow=True
        )
        self.assertContains(response, "Couldn&#x27;t reach")

    def test_a_url_that_is_not_this_app_is_reported(self):
        _, response = self.join(FakeHostResponse(status_code=404))
        self.assertContains(response, "doesn&#x27;t look like this app")

    def test_a_non_json_answer_is_reported(self):
        class Bad(FakeHostResponse):
            def json(self):
                raise ValueError("not json")

        _, response = self.join(Bad())
        self.assertContains(response, "wasn&#x27;t JSON")

    def test_joining_needs_a_login(self):
        self.client.logout()
        response = self.client.post(reverse("inventory:community_join"), {"host_url": "x", "code": "y"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"), response["Location"])


@override_settings(ALLOWED_HOSTS=["*"])
class CallbackUrlTests(PairingTestCase):
    def test_the_saved_public_url_wins_over_the_host_header(self):
        """Behind a tunnel the host header is whatever the proxy forwarded, which may
        not be the public name at all."""
        from inventory.models import SiteSettings

        site = SiteSettings.load()
        site.public_url = "https://parts.example.com"
        site.save()

        request = self.client.get(reverse("inventory:community_connections")).wsgi_request
        request.META["HTTP_HOST"] = "internal-container:3200"
        self.assertEqual(community_api.my_callback_url(request), "https://parts.example.com")

    def test_without_a_saved_url_it_uses_the_request(self):
        from inventory.models import SiteSettings

        SiteSettings.objects.all().delete()
        request = self.client.get(reverse("inventory:community_connections")).wsgi_request
        request.META["HTTP_HOST"] = "192.168.1.50:3200"
        self.assertIn("192.168.1.50:3200", community_api.my_callback_url(request))


class IssueCodeTests(PairingTestCase):
    def test_issuing_a_code_creates_one(self):
        self.client.post(reverse("inventory:community_issue_code"))
        self.assertEqual(PairingCode.objects.count(), 1)
        self.assertTrue(PairingCode.objects.get().is_usable())

    def test_issuing_again_cancels_the_previous_code(self):
        """Otherwise the owner reads out a code from ten minutes ago and cannot work
        out why it fails."""
        self.client.post(reverse("inventory:community_issue_code"))
        first = PairingCode.objects.get().code
        self.client.post(reverse("inventory:community_issue_code"))

        self.assertFalse(PairingCode.objects.filter(code=first).exists())
        self.assertEqual(PairingCode.objects.count(), 1)

    def test_a_claimed_code_is_not_cancelled_by_issuing_a_new_one(self):
        """The history of who joined with which code is worth keeping."""
        code = PairingCode.issue()
        peer = Peer.objects.create(name="Them", base_url="https://x.test")
        code.claimed_at = timezone.now()
        code.claimed_by = peer
        code.save()

        self.client.post(reverse("inventory:community_issue_code"))
        self.assertTrue(PairingCode.objects.filter(pk=code.pk).exists())


class PeerManagementTests(PairingTestCase):
    def setUp(self):
        super().setUp()
        self.peer = Peer.objects.create(name="Dad's workshop", base_url="https://dad.example.com", status=Peer.ACTIVE)

    def test_the_two_capabilities_are_toggled_separately(self):
        self.client.post(
            reverse("inventory:community_update_peer", args=[self.peer.pk]),
            {"exchanges_pins": "1", "shares_parts": "1", "name": "Dad"},
        )
        self.peer.refresh_from_db()
        self.assertTrue(self.peer.exchanges_pins)
        self.assertTrue(self.peer.shares_parts)
        self.assertEqual(self.peer.name, "Dad")

    def test_unticking_pins_does_not_touch_sharing(self):
        self.peer.shares_parts = True
        self.peer.save()
        self.client.post(reverse("inventory:community_update_peer", args=[self.peer.pk]), {"shares_parts": "1"})
        self.peer.refresh_from_db()
        self.assertFalse(self.peer.exchanges_pins)
        self.assertTrue(self.peer.shares_parts)

    def test_revoking_switches_both_capabilities_off(self):
        """Disconnecting has to mean no access, not a status label."""
        self.peer.exchanges_pins = True
        self.peer.shares_parts = True
        self.peer.save()

        self.client.post(reverse("inventory:community_revoke", args=[self.peer.pk]))
        self.peer.refresh_from_db()
        self.assertEqual(self.peer.status, Peer.REVOKED)
        self.assertFalse(self.peer.shares_parts)
        self.assertFalse(self.peer.exchanges_pins)
        self.assertFalse(self.peer.is_active)

    def test_revoking_keeps_the_row_so_the_log_keeps_its_subject(self):
        self.client.post(reverse("inventory:community_revoke", args=[self.peer.pk]))
        self.assertTrue(Peer.objects.filter(pk=self.peer.pk).exists())

    def test_forgetting_removes_everything_about_them(self):
        from inventory.models import PeerSearchLog

        PeerSearchLog.objects.create(peer=self.peer, query="servo", result_count=3)
        self.client.post(reverse("inventory:community_forget", args=[self.peer.pk]))
        self.assertFalse(Peer.objects.filter(pk=self.peer.pk).exists())
        self.assertEqual(PeerSearchLog.objects.count(), 0)

    def test_management_actions_need_a_post(self):
        """These are destructive, and links get prefetched by browsers and scanners."""
        self.client.get(reverse("inventory:community_revoke", args=[self.peer.pk]))
        self.peer.refresh_from_db()
        self.assertEqual(self.peer.status, Peer.ACTIVE)


class ConnectionsPageTests(PairingTestCase):
    def test_it_needs_a_login(self):
        self.client.logout()
        response = self.client.get(reverse("inventory:community_connections"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"), response["Location"])

    def test_it_renders(self):
        self.assertEqual(self.client.get(reverse("inventory:community_connections")).status_code, 200)

    def test_it_shows_the_address_others_should_use(self):
        from inventory.models import SiteSettings

        site = SiteSettings.load()
        site.public_url = "https://parts.example.com"
        site.save()
        self.assertContains(self.client.get(reverse("inventory:community_connections")), "https://parts.example.com")

    def test_it_warns_when_there_is_no_district_to_be_found_at(self):
        # A plain apostrophe, unlike the message assertions elsewhere in this file:
        # Django escapes variables, but this warning is literal text in the template,
        # which is emitted exactly as written.
        response = self.client.get(reverse("inventory:community_connections"))
        self.assertContains(response, "haven't set a district")

    def test_it_lists_the_search_log(self):
        from inventory.models import PeerSearchLog

        peer = Peer.objects.create(name="Dad", base_url="https://dad.test")
        PeerSearchLog.objects.create(peer=peer, query="servo", result_count=2)
        self.assertContains(self.client.get(reverse("inventory:community_connections")), "servo")
