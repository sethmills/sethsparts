"""Email notifications: SMTP config and the three events that fire them.

Two promises: nothing is sent until the owner both configures SMTP and turns a
notification on, and a failed send never breaks the inbound request that triggered it
(a message arriving, a connection being claimed, a search landing).
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .. import notifications
from ..models import Peer, SiteSettings


def make_peer(**overrides):
    defaults = {
        "name": "Dad's workshop",
        "base_url": "https://dad.example.test",
        "public_key": "aa" * 32,
        "inbound_api_key": "inbound-key",
        "outbound_api_key": "outbound-key",
        "status": Peer.ACTIVE,
        "exchanges_pins": True,
        "shares_parts": True,
    }
    defaults.update(overrides)
    return Peer.objects.create(**defaults)


def configure_email(**overrides):
    site = SiteSettings.load()
    site.email_enabled = True
    site.smtp_host = "smtp.example.test"
    site.smtp_port = 587
    site.smtp_user = "me@example.test"
    site.smtp_password = "app-password"
    site.smtp_use_tls = True
    site.email_from = "me@example.test"
    site.notify_email = "me@example.test"
    for key, value in overrides.items():
        setattr(site, key, value)
    site.save()
    return site


class IsConfiguredTests(TestCase):
    def test_nothing_is_configured_by_default(self):
        self.assertFalse(notifications.is_configured())

    def test_it_needs_the_password_too(self):
        site = SiteSettings.load()
        site.email_enabled = True
        site.smtp_host = "smtp.example.test"
        site.smtp_user = "me@example.test"
        site.save()
        self.assertFalse(notifications.is_configured())

    def test_enabled_plus_credentials_is_configured(self):
        configure_email()
        self.assertTrue(notifications.is_configured())


class SendTests(TestCase):
    @mock.patch("smtplib.SMTP")
    def test_send_logs_in_and_sends(self, SMTP):
        configure_email()
        server = SMTP.return_value.__enter__.return_value
        ok, error = notifications.send("Subject", "Body")
        self.assertTrue(ok, error)
        server.login.assert_called_once_with("me@example.test", "app-password")
        self.assertEqual(server.sendmail.call_args_list[0].args[0], "me@example.test")

    def test_send_reports_when_not_configured(self):
        ok, error = notifications.send("Subject", "Body")
        self.assertFalse(ok)
        self.assertIn("not configured", error)

    @mock.patch("smtplib.SMTP")
    def test_a_failed_login_is_reported_not_raised(self, SMTP):
        configure_email()
        server = SMTP.return_value.__enter__.return_value
        server.login.side_effect = __import__("smtplib").SMTPAuthenticationError(535, b"bad")
        ok, error = notifications.send("S", "B")
        self.assertFalse(ok)
        self.assertIn("SMTPAuthenticationError", error)


class DispatchTests(TestCase):
    def setUp(self):
        self.peer = make_peer()

    @mock.patch("smtplib.SMTP")
    def test_a_message_notification_sends_when_enabled(self, SMTP):
        configure_email(notify_on_message=True)
        notifications.on_message_received(self.peer)
        self.assertEqual(SMTP.call_count, 1)

    @mock.patch("smtplib.SMTP")
    def test_nothing_sends_while_every_flag_is_off(self, SMTP):
        configure_email()  # email on, but no notification flags ticked
        notifications.on_message_received(self.peer)
        notifications.on_connection(self.peer)
        notifications.on_peer_search(self.peer, "servo")
        SMTP.assert_not_called()

    @mock.patch("smtplib.SMTP", side_effect=__import__("smtplib").SMTPConnectError(421, b"down"))
    def test_a_failed_send_does_not_raise(self, _SMTP):
        configure_email(notify_on_message=True)
        notifications.on_message_received(self.peer)  # must not raise


class EndpointWiringTests(TestCase):
    """The inbound endpoints fire their notification, but only when enabled."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner", password="x")
        self.client.force_login(self.user)
        self.peer = make_peer()

    def post_message(self):
        return self.client.post(
            reverse("inventory:api_community_messages"),
            data='{"remote_id": "x", "body": "hi"}',
            content_type="application/json",
            headers={"X-Api-Key": "inbound-key"},
        )

    @mock.patch("smtplib.SMTP")
    def test_a_message_arrival_notifies_the_owner(self, SMTP):
        configure_email(notify_on_message=True)
        self.post_message()
        self.assertEqual(SMTP.call_count, 1)

    @mock.patch("smtplib.SMTP")
    def test_a_message_does_not_notify_while_disabled(self, SMTP):
        configure_email()  # email on, message flag off
        self.post_message()
        SMTP.assert_not_called()


class SettingsPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner", password="x")
        self.client.force_login(self.user)
        self.url = reverse("inventory:setup_email")

    def test_it_needs_a_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_email_is_offered_as_a_wizard_step(self):
        from .. import wizard

        self.assertEqual(wizard.EMAIL.key, "email")
        self.assertIn(wizard.EMAIL, wizard.visible_steps())

    def test_saving_moves_on_to_the_next_step(self):
        from .. import wizard

        response = self.client.post(self.url, {"action": "save", "smtp_host": "smtp.gmail.com", "smtp_port": "587"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse(wizard.next_step_after(wizard.EMAIL.key).url_name))

    def test_the_page_shows_the_gmail_instructions(self):
        response = self.client.get(self.url)
        self.assertContains(response, "app password")
        self.assertContains(response, "smtp.gmail.com")

    def test_saving_persists_the_choices(self):
        self.client.post(
            self.url,
            {
                "action": "save",
                "email_enabled": "1",
                "smtp_host": "smtp.gmail.com",
                "smtp_port": "587",
                "smtp_user": "me@gmail.com",
                "smtp_password": "pw",
                "notify_on_message": "1",
            },
        )
        site = SiteSettings.load()
        self.assertTrue(site.email_enabled)
        self.assertEqual(site.smtp_host, "smtp.gmail.com")
        self.assertTrue(site.notify_on_message)

    @mock.patch("smtplib.SMTP")
    def test_the_test_button_sends(self, SMTP):
        configure_email()
        SMTP.return_value.__enter__.return_value
        self.client.post(
            self.url,
            {
                "action": "test",
                "email_enabled": "1",
                "smtp_host": "smtp.example.test",
                "smtp_port": "587",
                "smtp_user": "me@example.test",
                "smtp_password": "app-password",
                "smtp_use_tls": "1",
                "notify_on_message": "1",
            },
        )
        SMTP.assert_called_once()
