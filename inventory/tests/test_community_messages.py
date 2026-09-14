"""Messaging between connected workshops, and blocking.

The consent model is "connecting is the consent to be messaged", so the inbound
endpoint accepts any active connection's key — no separate message permission. The
split that matters is the other way round: blocking must cut messaging, search, and
pins together, and stay cut off even with a fresh pairing code.
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .. import community_api, community_messages
from ..models import Message, PairingCode, Peer

from .factories import make_user


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


class ReceiveTests(TestCase):
    def setUp(self):
        self.peer = make_peer()

    def test_a_message_is_stored_as_inbound_unread(self):
        self.assertTrue(community_messages.receive(self.peer, "abc", "hello"))
        message = Message.objects.get()
        self.assertEqual(message.direction, Message.INBOUND)
        self.assertFalse(message.read)
        self.assertEqual(message.body, "hello")

    def test_an_empty_body_is_dropped(self):
        self.assertFalse(community_messages.receive(self.peer, "abc", "   "))
        self.assertFalse(Message.objects.exists())

    def test_a_retry_of_a_received_message_is_not_stored_twice(self):
        community_messages.receive(self.peer, "abc", "hello")
        self.assertFalse(community_messages.receive(self.peer, "abc", "hello"))
        self.assertEqual(Message.objects.count(), 1)

    def test_the_same_id_from_a_different_peer_is_a_new_message(self):
        other = make_peer(name="Other", inbound_api_key="i2", outbound_api_key="o2", public_key="bb" * 32)
        community_messages.receive(self.peer, "abc", "hello")
        self.assertTrue(community_messages.receive(other, "abc", "hello"))
        self.assertEqual(Message.objects.count(), 2)


class PeerAuthTests(TestCase):
    def request_with(self, key):
        from django.test import RequestFactory

        request = RequestFactory().post("/api/community/messages/")
        if key is not None:
            request.META["HTTP_X_API_KEY"] = key
        return request

    def test_any_active_connection_is_accepted(self):
        """Connecting is the consent: neither pin nor parts sharing is required to
        message, only that the connection is active."""
        peer = make_peer(exchanges_pins=False, shares_parts=False)
        self.assertEqual(community_messages.peer_for_messages(self.request_with("inbound-key")), peer)

    def test_a_missing_key_is_refused(self):
        self.assertIsNone(community_messages.peer_for_messages(self.request_with(None)))

    def test_a_revoked_connection_is_refused(self):
        make_peer(status=Peer.REVOKED)
        self.assertIsNone(community_messages.peer_for_messages(self.request_with("inbound-key")))


class MessagesEndpointTests(TestCase):
    def setUp(self):
        self.peer = make_peer()
        self.url = reverse("inventory:api_community_messages")

    def post(self, payload, key="inbound-key"):
        return self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json", headers={"X-Api-Key": key}
        )

    def test_a_message_arrives(self):
        response = self.post({"remote_id": "abc", "body": "hello"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["new"])
        self.assertEqual(Message.objects.get().body, "hello")

    def test_a_repeated_message_answers_already_have_it(self):
        self.post({"remote_id": "abc", "body": "hello"})
        response = self.post({"remote_id": "abc", "body": "hello"})
        self.assertFalse(response.json()["new"])
        self.assertEqual(Message.objects.count(), 1)

    def test_a_request_without_a_key_is_refused(self):
        response = self.client.post(self.url, data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_nonsense_is_refused(self):
        response = self.client.post(
            self.url, data="not json", content_type="application/json", headers={"X-Api-Key": "inbound-key"}
        )
        self.assertEqual(response.status_code, 400)

    def test_it_is_post_only(self):
        self.assertEqual(self.client.get(self.url, headers={"X-Api-Key": "inbound-key"}).status_code, 405)


class SendTests(TestCase):
    def setUp(self):
        self.peer = make_peer()

    @mock.patch("requests.post")
    def test_sending_stores_and_pushes(self, post):
        post.return_value.status_code = 200
        ok, error = community_messages.send(self.peer, "hello")
        self.assertTrue(ok, error)
        message = Message.objects.get()
        self.assertEqual(message.direction, Message.OUTBOUND)
        self.assertTrue(message.delivered)
        self.assertTrue(post.call_args_list[0].args[0].endswith("/api/community/messages/"))
        self.assertEqual(post.call_args_list[0].kwargs["headers"]["X-Api-Key"], "outbound-key")

    @mock.patch("requests.post", side_effect=__import__("requests").ConnectionError("down"))
    def test_a_failed_send_is_stored_as_undelivered(self, _post):
        ok, error = community_messages.send(self.peer, "hello")
        self.assertFalse(ok)
        message = Message.objects.get()
        self.assertFalse(message.delivered)
        self.assertIn("down", error)

    @mock.patch("requests.post")
    def test_retrying_redelivers_the_same_message(self, post):
        post.side_effect = [__import__("requests").ConnectionError("down"), mock.Mock(status_code=200)]
        community_messages.send(self.peer, "hello")
        message = Message.objects.get()
        ok, error = community_messages.retry(message)
        self.assertTrue(ok, error)
        message.refresh_from_db()
        self.assertTrue(message.delivered)

    def test_an_empty_message_is_refused(self):
        ok, error = community_messages.send(self.peer, "   ")
        self.assertFalse(ok)
        self.assertFalse(Message.objects.exists())


class BlockTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner", password="x")
        self.client.force_login(self.user)
        self.peer = make_peer()

    def test_blocking_cuts_everything(self):
        self.client.post(reverse("inventory:community_block", args=[self.peer.pk]))
        self.peer.refresh_from_db()
        self.assertTrue(self.peer.blocked)
        self.assertEqual(self.peer.status, Peer.REVOKED)
        self.assertFalse(self.peer.shares_parts)
        self.assertFalse(self.peer.exchanges_pins)

    def test_a_blocked_peer_is_refused_by_the_messaging_endpoint(self):
        self.client.post(reverse("inventory:community_block", args=[self.peer.pk]))
        response = self.client.post(
            reverse("inventory:api_community_messages"),
            data=json.dumps({"remote_id": "x", "body": "hi"}),
            content_type="application/json",
            headers={"X-Api-Key": "inbound-key"},
        )
        self.assertEqual(response.status_code, 403)

    def test_unblocking_permits_but_does_not_reconnect(self):
        self.client.post(reverse("inventory:community_block", args=[self.peer.pk]))
        self.client.post(reverse("inventory:community_unblock", args=[self.peer.pk]))
        self.peer.refresh_from_db()
        self.assertFalse(self.peer.blocked)
        self.assertEqual(self.peer.status, Peer.REVOKED, "unblocking removes the block, not the disconnect")


class BlockReclaimTests(TestCase):
    """A blocked workshop must not walk back in with a fresh code."""

    def test_a_blocked_peer_cannot_reclaim_with_a_fresh_code(self):
        peer = make_peer(blocked=True, status=Peer.REVOKED)
        code = PairingCode.issue()
        result, error = community_api.claim(
            code.code, name="Dad", base_url="https://dad.example.test", public_key=peer.public_key, callback_key="newkey"
        )
        self.assertIsNone(result)
        self.assertIn("blocked", error)
        code.refresh_from_db()
        self.assertTrue(code.is_usable(), "a blocked workshop should not even burn the code")

    def test_an_unblocked_revoked_peer_can_reconnect(self):
        peer = make_peer(status=Peer.REVOKED, blocked=False)
        code = PairingCode.issue()
        result, error = community_api.claim(
            code.code, name="Dad", base_url="https://dad.example.test", public_key=peer.public_key, callback_key="newkey"
        )
        self.assertIsNotNone(result, error)
        peer.refresh_from_db()
        self.assertEqual(peer.status, Peer.ACTIVE)


class InboxTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.peer = make_peer()

    def test_it_needs_a_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("inventory:community_messages")).status_code, 302)

    def test_a_thread_lists_its_peer_and_unread_count(self):
        community_messages.receive(self.peer, "a", "hello")
        community_messages.receive(self.peer, "b", "again")
        response = self.client.get(reverse("inventory:community_messages"))
        self.assertContains(response, "Dad&#x27;s workshop")
        self.assertContains(response, "2 new")

    def test_opening_a_thread_marks_it_read(self):
        community_messages.receive(self.peer, "a", "hello")
        self.client.get(reverse("inventory:community_message_thread", args=[self.peer.pk]))
        self.assertEqual(Message.objects.get().read, True)
