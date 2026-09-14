"""The update check.

Two things matter here. The version comparison has to be numeric, because string
comparison gets 0.10.0 vs 0.9.0 backwards and would tell people to "upgrade" to an
older release. And the check must never happen during a page render — a settings page
that silently phones GitHub on every load is a surprise to the person looking at it,
and it makes the page depend on the internet to draw itself.
"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory import updates
from inventory.version import __version__

from .factories import make_user


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class VersionComparisonTests(TestCase):
    def test_a_higher_version_is_recognised(self):
        info = updates.UpdateInfo(ok=True, current="1.0.0", latest="1.0.1")
        self.assertTrue(info.update_available)

    def test_the_same_version_is_not_an_update(self):
        self.assertFalse(updates.UpdateInfo(ok=True, current="1.0.0", latest="1.0.0").update_available)

    def test_an_older_version_is_not_an_update(self):
        self.assertFalse(updates.UpdateInfo(ok=True, current="2.0.0", latest="1.9.9").update_available)

    def test_minor_versions_compare_numerically_not_as_strings(self):
        """'0.10.0' < '0.9.0' as strings, which would report a downgrade as an update."""
        self.assertTrue(updates.UpdateInfo(ok=True, current="0.9.0", latest="0.10.0").update_available)
        self.assertFalse(updates.UpdateInfo(ok=True, current="0.10.0", latest="0.9.0").update_available)

    def test_a_leading_v_is_ignored(self):
        self.assertTrue(updates.UpdateInfo(ok=True, current="1.0.0", latest="v1.2.0").update_available)

    def test_a_failed_check_is_never_an_update(self):
        self.assertFalse(updates.UpdateInfo(ok=False, latest="9.9.9").update_available)

    def test_an_unparseable_version_does_not_claim_an_update(self):
        self.assertFalse(updates.UpdateInfo(ok=True, current="unknown", latest="also-unknown").update_available)

    def test_the_current_version_is_reported(self):
        self.assertEqual(updates.UpdateInfo(ok=True).current, __version__)


class FetchTests(TestCase):
    def setUp(self):
        cache.clear()

    def fetch(self, response=None, exc=None):
        patcher = mock.patch("requests.get")
        fake = patcher.start()
        self.addCleanup(patcher.stop)
        if exc is not None:
            fake.side_effect = exc
            return updates.check_for_update()
        fake.return_value = response
        return updates.check_for_update()

    def test_a_release_is_recognised(self):
        info = self.fetch(FakeResponse({"tag_name": "v0.4.0", "html_url": "https://github.com/x/y", "name": "Faster search"}))
        self.assertTrue(info.ok)
        self.assertEqual(info.latest, "v0.4.0")
        self.assertEqual(info.notes, "Faster search")

    def test_a_repository_with_no_releases_falls_back_to_tags(self):
        """A project with tags and no releases is normal, not an error."""
        calls = []

        def respond(url, **kwargs):
            calls.append(url)
            if url.endswith("releases/latest"):
                return FakeResponse(status_code=404)
            return FakeResponse([{"name": "v0.3.0"}])

        with mock.patch("requests.get", side_effect=respond):
            info = updates.check_for_update()

        self.assertTrue(info.ok)
        self.assertEqual(info.latest, "v0.3.0")
        self.assertEqual(len(calls), 2)

    def test_a_repository_it_cannot_see_is_explained(self):
        """GitHub answers 404 to an anonymous request for a private repository — on purpose,
        so that "private" and "does not exist" look identical from outside. This check sends
        no token, so a private repo lands here, and "HTTP 404" alone sends the owner looking
        for a typo in the repo name.

        The load-bearing half is that it stays `ok=False`: a check that could not run must
        never be reported as "you are up to date".
        """
        with mock.patch("requests.get", return_value=FakeResponse(status_code=404)):
            info = updates.check_for_update()

        self.assertFalse(info.ok)
        self.assertFalse(info.update_available)
        self.assertIn("private", info.error)
        self.assertIn(updates.repo(), info.error)

    def test_being_rate_limited_says_so(self):
        info = self.fetch(FakeResponse(status_code=403))
        self.assertFalse(info.ok)
        self.assertIn("rate-limiting", info.error)

    def test_a_server_error_is_reported(self):
        info = self.fetch(FakeResponse(status_code=500))
        self.assertFalse(info.ok)
        self.assertIn("500", info.error)

    def test_being_offline_does_not_raise(self):
        import requests

        info = self.fetch(exc=requests.ConnectionError("no route to host"))
        self.assertFalse(info.ok)
        self.assertIn("Couldn't reach GitHub", info.error)

    def test_a_non_json_response_is_handled(self):
        info = self.fetch(FakeResponse(payload=None))
        self.assertFalse(info.ok)

    def test_nothing_published_yet_is_not_an_error_state_the_owner_must_fix(self):
        def respond(url, **kwargs):
            if url.endswith("releases/latest"):
                return FakeResponse(status_code=404)
            return FakeResponse([])

        with mock.patch("requests.get", side_effect=respond):
            info = updates.check_for_update()
        self.assertFalse(info.ok)
        self.assertIn("No releases", info.error)

    @override_settings(UPDATE_CHECK_ENABLED=False)
    def test_turning_it_off_makes_no_request_at_all(self):
        """Not "checks and ignores" — makes no call, which is what the setting claims."""
        with mock.patch("requests.get") as fake:
            info = updates.check_for_update()
        fake.assert_not_called()
        self.assertFalse(info.ok)

    def test_the_repository_is_configurable_so_a_fork_follows_itself(self):
        with override_settings(UPDATE_REPO="someone/their-fork"):
            with mock.patch("requests.get", return_value=FakeResponse({"tag_name": "v1.0.0"})) as fake:
                updates.check_for_update()
        self.assertIn("someone/their-fork", fake.call_args[0][0])


class CachingTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_nothing_is_known_before_the_first_check(self):
        self.assertIsNone(updates.cached_info())

    def test_a_result_is_remembered(self):
        with mock.patch("requests.get", return_value=FakeResponse({"tag_name": "v9.9.9"})):
            updates.check_for_update()
        self.assertEqual(updates.cached_info().latest, "v9.9.9")

    def test_a_second_check_uses_the_cache_until_cleared(self):
        """A request per page load would be rude to GitHub and tell nobody anything new."""
        with mock.patch("requests.get", return_value=FakeResponse({"tag_name": "v1.0.0"})):
            updates.check_for_update()

        with mock.patch("requests.get") as fake:
            self.assertEqual(updates.cached_info().latest, "v1.0.0")
        fake.assert_not_called()

    def test_the_cache_can_be_cleared(self):
        with mock.patch("requests.get", return_value=FakeResponse({"tag_name": "v1.0.0"})):
            updates.check_for_update()
        updates.clear_cache()
        self.assertIsNone(updates.cached_info())


class DescribeTests(TestCase):
    def test_an_available_update_reads_plainly(self):
        line = updates.describe(updates.UpdateInfo(ok=True, current="0.1.0", latest="0.2.0"))
        self.assertIn("newer version", line)
        self.assertIn("0.2.0", line)

    def test_being_current_reads_plainly(self):
        self.assertIn("up to date", updates.describe(updates.UpdateInfo(ok=True, current="0.1.0", latest="0.1.0")))

    def test_a_failure_reports_its_reason(self):
        self.assertEqual(updates.describe(updates.UpdateInfo(ok=False, error="GitHub said no")), "GitHub said no")


class SettingsPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(make_user())

    def test_opening_settings_makes_no_network_call(self):
        """The design guarantee. A settings page that phones out on every load is a
        surprise, and it would fail offline."""
        with mock.patch("requests.get") as fake:
            response = self.client.get(reverse("inventory:setup_hub"))
        self.assertEqual(response.status_code, 200)
        fake.assert_not_called()

    def test_the_page_offers_the_check(self):
        self.assertContains(self.client.get(reverse("inventory:setup_hub")), "Check for updates")

    def test_pressing_the_button_checks_and_reports(self):
        with mock.patch("requests.get", return_value=FakeResponse({"tag_name": "v9.9.9"})):
            response = self.client.post(reverse("inventory:setup_hub"), {"action": "check_updates"}, follow=True)
        self.assertContains(response, "9.9.9")

    def test_a_failed_check_reports_rather_than_crashing_the_page(self):
        import requests

        with mock.patch("requests.get", side_effect=requests.ConnectionError("offline")):
            response = self.client.post(reverse("inventory:setup_hub"), {"action": "check_updates"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GitHub")

    def test_the_page_shows_the_last_result_without_checking_again(self):
        with mock.patch("requests.get", return_value=FakeResponse({"tag_name": "v5.0.0"})):
            self.client.post(reverse("inventory:setup_hub"), {"action": "check_updates"})

        with mock.patch("requests.get") as fake:
            response = self.client.get(reverse("inventory:setup_hub"))
        self.assertContains(response, "5.0.0")
        fake.assert_not_called()
