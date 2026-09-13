"""Site settings, branding, and the two per-request middlewares.

The theme running through this module is the difference between a *fresh clone* and
an *install in use*, because that distinction is what decides whether someone is sent
to the setup wizard or to their inventory. Getting it wrong in one direction nags a
working install; in the other it walls off a database full of good parts.
"""


from django.contrib import admin
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from inventory import site_config
from inventory.middleware import SetupRedirectMiddleware, SiteTimezoneMiddleware
from inventory.models import SiteSettings

from .factories import make_part, make_user


class SiteSettingsModelTests(TestCase):
    def test_load_is_a_singleton(self):
        self.assertEqual(SiteSettings.load().pk, SiteSettings.load().pk)
        self.assertEqual(SiteSettings.objects.count(), 1)

    def test_sensible_defaults(self):
        s = SiteSettings.load()
        self.assertEqual(s.site_name, "My Parts")
        self.assertEqual(s.timezone, "UTC")
        self.assertEqual(s.unit_system, "metric")
        self.assertEqual(s.country, "")

    def test_a_new_row_is_not_set_up(self):
        """The default has to be "not set up", because that is what sends a
        first-time user to the wizard."""
        self.assertFalse(SiteSettings.load().setup_complete)

    def test_marking_setup_complete_flips_the_flag(self):
        s = SiteSettings.load()
        s.setup_completed_at = timezone.now()
        s.save()
        self.assertTrue(s.setup_complete)
        self.assertTrue(SiteSettings.objects.get(pk=s.pk).setup_complete)


class SiteConfigAccessorTests(TestCase):
    """Every accessor has to work when the row doesn't exist — a fresh clone asks
    these questions before anything is configured."""

    def test_defaults_when_there_is_no_row(self):
        self.assertIsNone(site_config.get_site_settings())
        self.assertEqual(site_config.site_name(), "My Parts")
        self.assertEqual(site_config.timezone_name(), "UTC")
        self.assertEqual(site_config.unit_system(), "metric")
        self.assertEqual(site_config.country(), "")
        self.assertFalse(site_config.setup_is_complete())

    def test_values_come_from_the_row_once_it_exists(self):
        SiteSettings.objects.create(
            site_name="Eric's Parts",
            timezone="America/New_York",
            country="us",
            unit_system="imperial",
            setup_completed_at=timezone.now(),
        )
        self.assertEqual(site_config.site_name(), "Eric's Parts")
        self.assertEqual(site_config.timezone_name(), "America/New_York")
        self.assertEqual(site_config.country(), "US", "country is normalised to upper case")
        self.assertEqual(site_config.unit_system(), "imperial")
        self.assertTrue(site_config.setup_is_complete())

    def test_an_empty_name_falls_back_rather_than_rendering_blank(self):
        """A blank site name would leave the header and every page title empty."""
        SiteSettings.objects.create(site_name="")
        self.assertEqual(site_config.site_name(), "My Parts")


class BrandingTests(TestCase):
    def test_the_admin_header_follows_the_site_name(self):
        SiteSettings.objects.create(site_name="Eric's Parts", setup_completed_at=timezone.now())
        self.assertEqual(site_config.apply_site_branding(), "Eric's Parts")
        self.assertEqual(admin.site.site_header, "Eric's Parts")
        self.assertEqual(admin.site.site_title, "Eric's Parts")
        self.assertIn("Eric's Parts", admin.site.index_title)

    def test_renaming_updates_the_admin_immediately(self):
        """Otherwise the admin keeps showing the old name until the process happens
        to restart, which for a long-running container could be days."""
        s = SiteSettings.load()
        s.site_name = "Workshop One"
        s.save()
        self.assertEqual(admin.site.site_header, "Workshop One")

    def test_it_accepts_an_already_loaded_row(self):
        """The per-request caller passes the row it has already read so the site name
        does not cost a second query on every page."""
        s = SiteSettings.objects.create(site_name="Passed In")
        self.assertEqual(site_config.apply_site_branding(s), "Passed In")

    def test_it_never_raises_without_a_row(self):
        self.assertEqual(site_config.apply_site_branding(), "My Parts")


class TimezoneMiddlewareTests(TestCase):
    def run_request(self, path="/"):
        seen = {}

        def get_response(request):
            seen["tz"] = timezone.get_current_timezone_name()
            return HttpResponse("ok")

        SiteTimezoneMiddleware(get_response)(RequestFactory().get(path))
        return seen

    def test_renders_in_the_configured_zone(self):
        """This is the bug that made the timezone a middleware: an install in the US
        was displaying every timestamp in the container's zone."""
        SiteSettings.objects.create(timezone="America/New_York", setup_completed_at=timezone.now())
        self.assertEqual(self.run_request()["tz"], "America/New_York")

    def test_the_zone_is_released_afterwards(self):
        """Workers are reused between requests, so leaving a zone active would leak
        it into the next request on the same thread."""
        SiteSettings.objects.create(timezone="America/New_York", setup_completed_at=timezone.now())
        self.run_request()
        self.assertNotEqual(timezone.get_current_timezone_name(), "America/New_York")

    def test_an_unknown_zone_does_not_take_the_site_down(self):
        SiteSettings.objects.create(timezone="Mars/Olympus_Mons", setup_completed_at=timezone.now())
        self.run_request()  # must not raise

    def test_falls_back_to_utc_without_a_row(self):
        self.assertEqual(self.run_request()["tz"], "UTC")


class SetupRedirectTests(TestCase):
    """The narrow condition that keeps a working install reachable."""

    def test_a_virgin_install_is_sent_to_setup(self):
        """No account exists, so there is literally nothing to log in with."""
        self.assertEqual(get_user_model().objects.count(), 0)
        resp = self.client.get(reverse("inventory:browse"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/setup", resp["Location"])

    def test_an_install_with_an_account_is_never_redirected(self):
        """The important one. Once an account exists the app must be usable, even if
        setup was never finished — otherwise closing the tab mid-wizard locks the
        owner out of their own inventory."""
        make_user()
        resp = self.client.get(reverse("inventory:browse"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"], "should hit the normal login wall")

    def test_a_finished_install_is_not_redirected(self):
        make_user()
        SiteSettings.objects.create(setup_completed_at=timezone.now())
        resp = self.client.get(reverse("inventory:browse"))
        self.assertIn("/admin/login/", resp["Location"])

    def test_the_wizard_itself_is_exempt(self):
        """Otherwise the redirect would point at a page that redirects to itself."""
        self.assertTrue(SetupRedirectMiddleware._is_exempt("/setup/"))
        self.assertTrue(SetupRedirectMiddleware._is_exempt("/setup/account/"))

    def test_login_is_reachable_on_a_virgin_install(self):
        self.assertTrue(SetupRedirectMiddleware._is_exempt("/admin/login/"))

    def test_machine_endpoints_are_exempt(self):
        """Home Assistant calls /api/locate/ with a shared secret and no browser, so
        a human onboarding redirect there would silently break voice search."""
        self.assertTrue(SetupRedirectMiddleware._is_exempt("/api/locate/"))

    def test_static_files_are_exempt(self):
        """The wizard cannot render without its stylesheet."""
        self.assertTrue(SetupRedirectMiddleware._is_exempt("/static/inventory/style.css"))
        self.assertTrue(SetupRedirectMiddleware._is_exempt("/media/attachments/x.pdf"))

    def test_virgin_detection_returns_a_bool(self):
        """If auth can't be read at all, the safe answer is "not virgin" — showing a
        login page beats making the site unreachable."""
        self.assertIsInstance(SetupRedirectMiddleware._is_virgin_install(), bool)


class ApiEndpointAccessTests(TestCase):
    def test_the_voice_api_is_reachable_on_a_virgin_install(self):
        """It should answer 403 (no key configured), not redirect to the wizard."""
        resp = self.client.get("/api/locate/", {"q": "servo"})
        self.assertEqual(resp.status_code, 403)


class ContextProcessorTests(TestCase):
    def render(self):
        from inventory.context_processors import site_context

        return site_context(RequestFactory().get("/"))

    def test_exposes_the_site_name(self):
        SiteSettings.objects.create(site_name="Eric's Parts", setup_completed_at=timezone.now())
        self.assertEqual(self.render()["site_name"], "Eric's Parts")

    def test_reports_capabilities_as_absent_by_default(self):
        """Which is what lets a template hide a Lights button on an install with no
        LED controller, instead of showing one that always fails."""
        ctx = self.render()
        self.assertFalse(ctx["has_leds"])
        self.assertFalse(ctx["has_printer"])

    def test_reports_capabilities_when_configured(self):
        with self.settings(LED_CONTROLLER_URL="http://pi:8080", LABEL_PRINTER_URL="http://pi:9100"):
            ctx = self.render()
            self.assertTrue(ctx["has_leds"])
            self.assertTrue(ctx["has_printer"])

    def test_reports_setup_state(self):
        self.assertFalse(self.render()["setup_complete"])
        s = SiteSettings.load()
        s.setup_completed_at = timezone.now()
        s.save()
        self.assertTrue(self.render()["setup_complete"])


class WizardGateTests(TestCase):
    """What the wizard is allowed to gate on.

    A full migration run is deliberately NOT re-enacted here — rolling migrations
    back and forth inside the test database leaves it in a state later tests can trip
    over. The two paths (`0016`) were verified directly instead, against real
    throwaway databases: an empty one is left unconfigured with no SiteSettings row,
    and one seeded with a part gets the row and is marked complete. What is asserted
    here is the part the rest of the app depends on.
    """

    def test_an_account_is_what_makes_the_app_reachable(self):
        """Not `setup_completed_at`. That distinction is the whole reason a user who
        abandons the wizard halfway can still get to their inventory."""
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertIn("/setup", self.client.get(reverse("inventory:browse"))["Location"])

        make_user(username="eric")
        self.assertIn("/admin/login/", self.client.get(reverse("inventory:browse"))["Location"])

    def test_setup_state_is_separate_from_reachability(self):
        make_user(username="eric")
        make_part(name="anything")
        # No SiteSettings row at all, yet the app is perfectly usable.
        self.assertFalse(site_config.setup_is_complete())
        self.assertFalse(SetupRedirectMiddleware._is_virgin_install())
        self.assertIn("/admin/login/", self.client.get(reverse("inventory:browse"))["Location"])
