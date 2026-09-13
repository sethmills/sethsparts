"""Kiosk auto-login -- the Pi establishes a real session on every boot.

Design constraint worth pinning: this mints a genuine Django session using a
long-lived shared secret, and never touches Seth's account password. A
regression that logged in the wrong user, or that logged anyone in when the
token was unset, would be a real security problem rather than a cosmetic bug.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .factories import make_user

TOKEN = "kiosk-shared-secret"
ON = override_settings(KIOSK_AUTOLOGIN_TOKEN=TOKEN, KIOSK_AUTOLOGIN_USERNAME="seth")


class KioskAutologinTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seth = make_user(username="seth")
        cls.other = make_user(username="someone-else")

    def url(self):
        return reverse("inventory:kiosk_autologin")

    @ON
    def test_a_correct_token_logs_the_kiosk_user_in(self):
        resp = self.client.get(self.url(), {"token": TOKEN})
        self.assertRedirects(resp, reverse("inventory:browse"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.seth.pk)

    @ON
    def test_it_logs_in_the_configured_user_only(self):
        resp = self.client.get(self.url(), {"token": TOKEN})
        self.assertRedirects(resp, reverse("inventory:browse"))
        self.assertNotEqual(int(self.client.session["_auth_user_id"]), self.other.pk)

    @ON
    def test_a_wrong_token_does_not_log_anyone_in(self):
        self.client.get(self.url(), {"token": "wrong"})
        self.assertNotIn("_auth_user_id", self.client.session)

    @ON
    def test_a_missing_token_does_not_log_anyone_in(self):
        self.client.get(self.url())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_an_unset_token_configuration_rejects_everything(self):
        """Empty must mean 'disabled', not 'any token matches' -- a naive
        implementation comparing against an empty string would let anyone in."""
        with override_settings(KIOSK_AUTOLOGIN_TOKEN="", KIOSK_AUTOLOGIN_USERNAME="seth"):
            self.client.get(self.url(), {"token": ""})
            self.assertNotIn("_auth_user_id", self.client.session)

            self.client.get(self.url(), {"token": "anything"})
            self.assertNotIn("_auth_user_id", self.client.session)

    @ON
    def test_a_failed_attempt_lands_on_the_normal_login_walled_site(self):
        """fetch_redirect_response=False because the target (browse) is itself
        login-walled -- following it would correctly 302 again, which isn't what
        this test is about."""
        resp = self.client.get(self.url(), {"token": "wrong"})
        self.assertRedirects(resp, reverse("inventory:browse"), fetch_redirect_response=False)

    @ON
    def test_a_redirect_target_is_honoured(self):
        target = reverse("inventory:parts_search")
        resp = self.client.get(self.url(), {"token": TOKEN, "next": target})
        self.assertRedirects(resp, target, fetch_redirect_response=False)

    @ON
    def test_the_redirect_target_is_ignored_on_a_bad_token(self):
        resp = self.client.get(self.url(), {"token": "wrong", "next": "https://evil.example.com"})
        self.assertRedirects(resp, reverse("inventory:browse"), fetch_redirect_response=False)

    @ON
    def test_it_cannot_log_in_a_username_that_does_not_exist(self):
        with override_settings(KIOSK_AUTOLOGIN_TOKEN=TOKEN, KIOSK_AUTOLOGIN_USERNAME="ghost"):
            self.client.get(self.url(), {"token": TOKEN})
            self.assertNotIn("_auth_user_id", self.client.session)

    @ON
    def test_the_session_still_grants_access_to_a_protected_page(self):
        """The point of the whole feature: one request, then a working session."""
        self.client.get(self.url(), {"token": TOKEN})
        resp = self.client.get(reverse("inventory:browse"))
        self.assertEqual(resp.status_code, 200)

    @ON
    def test_a_prefix_of_the_token_is_not_enough(self):
        self.client.get(self.url(), {"token": TOKEN[:-1]})
        self.assertNotIn("_auth_user_id", self.client.session)

    @ON
    def test_the_token_is_matched_exactly_including_case(self):
        self.client.get(self.url(), {"token": TOKEN.upper()})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_login_still_works_independently(self):
        """The kiosk path must not have replaced normal auth."""
        self.assertTrue(self.client.login(username="seth", password="test-pass-123"))
