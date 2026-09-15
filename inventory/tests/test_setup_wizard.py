"""The setup wizard, which doubles as the settings pages.

Two things are being protected here. First, that a brand-new install can actually be
set up — including creating the account, which has to happen without a login because
there is nothing to log in with yet. Second, that none of it can lock anyone out, and
that every step stays reachable afterwards so an owner can change their mind.

The account step is the one with real teeth: it is the only unauthenticated write in
the whole app, so its closing condition is asserted from both directions.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory import wizard
from inventory.models import (
    CommunityProfile,
    DrawerLedSegment,
    ReferenceCategory,
    ReferenceDoc,
    SiteSettings,
)

from .factories import make_container, make_drawer, make_user

STRONG_PASSWORD = "Sh0pFull-0f-P4rts!"


class WizardFlowTestCase(TestCase):
    def create_account(self):
        return self.client.post(
            reverse("inventory:setup_account"),
            {"username": "eric", "password1": STRONG_PASSWORD, "password2": STRONG_PASSWORD},
        )


class VirginInstallTests(WizardFlowTestCase):
    def test_the_root_sends_a_first_timer_to_setup(self):
        """Not to a login page for an account that does not exist yet."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/setup", response["Location"])

    def test_the_hub_sends_you_to_the_account_step_first(self):
        """Nothing else is worth doing before there's a login."""
        response = self.client.get(reverse("inventory:setup_hub"))
        self.assertRedirects(response, reverse("inventory:setup_account"))

    def test_the_account_step_is_offered(self):
        response = self.client.get(reverse("inventory:setup_account"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your account")

    def test_the_account_step_is_the_only_required_thing_at_the_start(self):
        outstanding = [s.key for s in wizard.required_outstanding()]
        self.assertIn("account", outstanding)
        self.assertIn("site", outstanding)


class AccountStepTests(WizardFlowTestCase):
    def test_it_creates_a_superuser(self):
        self.create_account()
        user = get_user_model().objects.get(username="eric")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password(STRONG_PASSWORD))

    def test_it_logs_you_straight_in(self):
        """Making someone set a password and then immediately type it again on a login
        page is a pointless hurdle."""
        response = self.create_account()
        self.assertRedirects(response, reverse("inventory:setup_site"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_it_closes_the_moment_an_account_exists(self):
        """This is the only unauthenticated write in the app, so it has to shut."""
        self.create_account()
        self.client.logout()
        response = self.client.get(reverse("inventory:setup_account"))
        self.assertEqual(response.status_code, 404)

    def test_it_refuses_a_second_account_even_when_posted_at(self):
        """A 404 on GET is not enough — the POST has to be refused too, or the page is
        only cosmetically closed."""
        self.create_account()
        self.client.logout()
        response = self.client.post(
            reverse("inventory:setup_account"),
            {"username": "intruder", "password1": STRONG_PASSWORD, "password2": STRONG_PASSWORD},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(get_user_model().objects.filter(username="intruder").exists())

    def test_mismatched_passwords_are_refused(self):
        self.client.post(
            reverse("inventory:setup_account"),
            {"username": "eric", "password1": STRONG_PASSWORD, "password2": "something-else"},
        )
        self.assertFalse(get_user_model().objects.exists())

    def test_a_weak_password_is_refused(self):
        """The same validators the admin uses, so the wizard cannot be a weaker route
        into the app than any other."""
        self.client.post(
            reverse("inventory:setup_account"),
            {"username": "eric", "password1": "password", "password2": "password"},
        )
        self.assertFalse(get_user_model().objects.exists())

    def test_a_missing_username_is_refused(self):
        self.client.post(
            reverse("inventory:setup_account"),
            {"username": "  ", "password1": STRONG_PASSWORD, "password2": STRONG_PASSWORD},
        )
        self.assertFalse(get_user_model().objects.exists())

    def test_the_user_is_not_created_when_validation_fails(self):
        response = self.client.post(
            reverse("inventory:setup_account"),
            {"username": "eric", "password1": "short", "password2": "nope"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create my account")


class SiteStepTests(WizardFlowTestCase):
    def setUp(self):
        self.create_account()

    def test_it_saves_everything_the_step_asks_for(self):
        self.client.post(
            reverse("inventory:setup_site"),
            {"site_name": "Eric's Parts", "timezone": "America/New_York", "country": "us", "unit_system": "imperial"},
        )
        site = SiteSettings.load()
        self.assertEqual(site.site_name, "Eric's Parts")
        self.assertEqual(site.timezone, "America/New_York")
        self.assertEqual(site.country, "US", "country is normalised to upper case")
        self.assertEqual(site.unit_system, "imperial")

    def test_the_brand_toggle_is_saved(self):
        self.client.post(
            reverse("inventory:setup_site"),
            {"site_name": "X", "timezone": "UTC", "show_branding": "on"},
        )
        self.assertTrue(SiteSettings.load().show_branding)

        self.client.post(
            reverse("inventory:setup_site"),
            {"site_name": "X", "timezone": "UTC"},
        )
        self.assertFalse(SiteSettings.load().show_branding)

    def test_an_unknown_timezone_is_refused(self):
        """Saving "Mars/Olympus_Mons" would render every timestamp wrong with no clue
        why — and the middleware would simply fall back and hide the mistake."""
        self.client.post(
            reverse("inventory:setup_site"),
            {"site_name": "X", "timezone": "Mars/Olympus_Mons", "country": "GB"},
        )
        self.assertNotEqual(SiteSettings.load().timezone, "Mars/Olympus_Mons")

    def test_a_blank_name_is_refused(self):
        """The name is in the header of every page; an empty one looks broken."""
        SiteSettings.objects.create(site_name="Untouched")
        self.client.post(reverse("inventory:setup_site"), {"site_name": "   ", "timezone": "UTC"})
        self.assertEqual(SiteSettings.load().site_name, "Untouched")

    def test_an_unknown_unit_system_falls_back_to_metric(self):
        self.client.post(
            reverse("inventory:setup_site"),
            {"site_name": "X", "timezone": "UTC", "unit_system": "martian"},
        )
        self.assertEqual(SiteSettings.load().unit_system, "metric")

    def test_an_empty_country_is_allowed(self):
        self.client.post(reverse("inventory:setup_site"), {"site_name": "X", "timezone": "UTC", "country": ""})
        self.assertEqual(SiteSettings.load().country, "")

    def test_the_step_needs_a_login_once_an_account_exists(self):
        self.client.logout()
        response = self.client.get(reverse("inventory:setup_site"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"), response["Location"])

    def test_it_moves_on_to_the_next_step(self):
        response = self.client.post(
            reverse("inventory:setup_site"), {"site_name": "X", "timezone": "UTC", "country": "GB"}
        )
        self.assertRedirects(response, reverse("inventory:setup_lights"))


class LightsStepTests(WizardFlowTestCase):
    def setUp(self):
        self.create_account()

    def test_a_bare_host_gets_a_scheme(self):
        """“192.168.1.50:8080” is how a person writes an address on their own network.
        Demanding “http://” would be pedantic about something the app can fix."""
        self.client.post(reverse("inventory:setup_lights"), {"action": "save", "led_controller_url": "192.168.1.50:8080"})
        self.assertEqual(SiteSettings.load().led_controller_url, "http://192.168.1.50:8080")

    def test_a_trailing_slash_is_trimmed(self):
        self.client.post(reverse("inventory:setup_lights"), {"action": "save", "led_controller_url": "http://pi:8080/"})
        self.assertEqual(SiteSettings.load().led_controller_url, "http://pi:8080")

    def test_clearing_the_address_switches_the_feature_off(self):
        self.client.post(reverse("inventory:setup_lights"), {"action": "save", "led_controller_url": "http://pi:8080"})
        self.client.post(reverse("inventory:setup_lights"), {"action": "save", "led_controller_url": ""})
        self.assertEqual(SiteSettings.load().led_controller_url, "")

    def test_the_connection_test_reports_success_and_the_strips_it_found(self):
        class R:
            status_code = 200

            def json(self):
                return {"ok": True, "strips_configured": ["cabinet1-left", "cabinet1-right"]}

        with mock.patch("requests.get", return_value=R()):
            response = self.client.post(
                reverse("inventory:setup_lights"), {"action": "test", "led_controller_url": "http://pi:8080"},
                follow=True,
            )
        self.assertContains(response, "cabinet1-left")

    def test_the_connection_test_reports_a_failure_plainly(self):
        import requests

        with mock.patch("requests.get", side_effect=requests.ConnectionError("connection refused")):
            response = self.client.post(
                reverse("inventory:setup_lights"), {"action": "test", "led_controller_url": "http://pi:8080"},
                follow=True,
            )
        self.assertContains(response, "refused")

    def test_testing_with_no_address_set_says_so(self):
        response = self.client.post(reverse("inventory:setup_lights"), {"action": "test", "led_controller_url": ""}, follow=True)
        self.assertContains(response, "No LED controller address")

    def test_a_mapping_can_be_added(self):
        drawer = make_drawer(make_container())
        self.client.post(
            reverse("inventory:setup_lights"),
            {"action": "add_mapping", "drawer": drawer.pk, "led_strip": "cabinet1-left", "led_start_index": "12", "led_count": "4"},
        )
        segment = DrawerLedSegment.objects.get()
        self.assertEqual(segment.drawer, drawer)
        self.assertEqual(segment.led_strip, "cabinet1-left")
        self.assertEqual(segment.led_start_index, 12)
        self.assertEqual(segment.led_count, 4)

    def test_an_incomplete_mapping_is_refused(self):
        drawer = make_drawer(make_container())
        self.client.post(
            reverse("inventory:setup_lights"),
            {"action": "add_mapping", "drawer": drawer.pk, "led_strip": "", "led_start_index": "", "led_count": "1"},
        )
        self.assertEqual(DrawerLedSegment.objects.count(), 0)

    def test_a_non_numeric_led_index_is_refused(self):
        drawer = make_drawer(make_container())
        self.client.post(
            reverse("inventory:setup_lights"),
            {"action": "add_mapping", "drawer": drawer.pk, "led_strip": "s", "led_start_index": "twelve", "led_count": "1"},
        )
        self.assertEqual(DrawerLedSegment.objects.count(), 0)

    def test_a_zero_led_count_is_raised_to_one(self):
        """A mapping that lights nothing is indistinguishable from a broken one."""
        drawer = make_drawer(make_container())
        self.client.post(
            reverse("inventory:setup_lights"),
            {"action": "add_mapping", "drawer": drawer.pk, "led_strip": "s", "led_start_index": "0", "led_count": "0"},
        )
        self.assertEqual(DrawerLedSegment.objects.get().led_count, 1)

    def test_a_mapping_can_be_removed(self):
        drawer = make_drawer(make_container())
        segment = DrawerLedSegment.objects.create(drawer=drawer, led_strip="s", led_start_index=0, led_count=1)
        self.client.post(reverse("inventory:setup_lights"), {"action": "delete_mapping", "mapping": segment.pk})
        self.assertEqual(DrawerLedSegment.objects.count(), 0)

    def test_all_mappings_can_be_cleared(self):
        drawer = make_drawer(make_container())
        DrawerLedSegment.objects.create(drawer=drawer, led_strip="a", led_start_index=0, led_count=1)
        self.client.post(reverse("inventory:setup_lights"), {"action": "clear_mappings"})
        self.assertEqual(DrawerLedSegment.objects.count(), 0)

    def test_saving_moves_on_to_the_next_step(self):
        """The next step is Flashing, which sits between telling the app about the
        controller and configuring a printer — the order the physical job happens in."""
        response = self.client.post(reverse("inventory:setup_lights"), {"action": "save", "led_controller_url": ""})
        self.assertRedirects(response, reverse("inventory:setup_flash"))


class FlashStepTests(WizardFlowTestCase):
    """The flashing walkthrough.

    The page's two jobs are instructions and verification, and only the second one can be
    tested mechanically — so what is pinned here is that the instructions name the things
    someone actually needs (the script, the button, the modes) and that the verification
    tells the truth in every direction, including the one that matters most: a board that
    isn't there must never come back as a pass.
    """

    def setUp(self):
        self.create_account()
        site = SiteSettings.load()
        site.led_controller_url = "http://pi:8080"
        site.led_controller_key = "shared-secret"
        site.save()
        # Rendering once drains the "account created" message that create_account left in
        # the session. Without this, every later assertion about message *tags* would be
        # reading that message rather than the one the check produced.
        self.client.get(reverse("inventory:setup_flash"))

    def health(self, status=200, body=None):
        class R:
            status_code = status
            text = ""

            def json(self):
                return body if body is not None else {"ok": True, "strips_configured": ["cabinet1-left"]}

        return R()

    def demo(self, status=200):
        class R:
            status_code = status
            text = '{"ok": true}'

            def json(self):
                return {}

        return R()

    # --- what the page says, and what it does not do ----------------------

    def test_it_walks_through_the_physical_part(self):
        response = self.client.get(reverse("inventory:setup_flash"))
        self.assertContains(response, "BOOTSEL")
        self.assertContains(response, "RPI-RP2")
        self.assertContains(response, "CIRCUITPY")

    def test_it_names_the_script_to_run_and_where(self):
        response = self.client.get(reverse("inventory:setup_flash"))
        self.assertContains(response, "flash-scorpio.py")

    def test_it_is_honest_that_the_app_cannot_do_the_flashing(self):
        """Literal template text, so the apostrophe is not escaped — unlike a value
        rendered from context, which would come back as &#x27;."""
        response = self.client.get(reverse("inventory:setup_flash"))
        self.assertContains(response, "This app can't flash it for you")

    def test_it_warns_about_the_hardware_reset_trap(self):
        """The one that cost an evening: a soft reset leaves the data channel missing."""
        response = self.client.get(reverse("inventory:setup_flash"))
        self.assertContains(response, "hardware reset")
        self.assertContains(response, "microcontroller.reset()")

    def test_the_page_makes_no_request_to_the_hardware(self):
        """A sibling rule in this app: nothing external during a render. Checking is a
        button somebody presses, not something a page load does behind their back."""
        with mock.patch("requests.get", side_effect=AssertionError("no request during a render")):
            response = self.client.get(reverse("inventory:setup_flash"))
        self.assertEqual(response.status_code, 200)

    def test_skipping_is_a_link_to_the_next_step(self):
        response = self.client.get(reverse("inventory:setup_flash"))
        self.assertContains(response, reverse("inventory:setup_printer"))

    def test_it_says_so_when_there_is_no_controller_to_check(self):
        site = SiteSettings.load()
        site.led_controller_url = ""
        site.save()
        response = self.client.get(reverse("inventory:setup_flash"))
        self.assertContains(response, "No LED controller set up yet")

    def test_it_needs_a_login(self):
        from django.test import Client

        response = Client().get(reverse("inventory:setup_flash"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    # --- the check itself -------------------------------------------------

    def test_check_with_no_address_configured_says_so(self):
        site = SiteSettings.load()
        site.led_controller_url = ""
        site.save()
        response = self.client.post(reverse("inventory:setup_flash"), {"action": "check"}, follow=True)
        self.assertContains(response, "No LED controller address")

    def test_check_with_an_unreachable_service_says_flashing_is_not_the_problem(self):
        import requests

        with mock.patch("requests.get", side_effect=requests.ConnectionError("connection refused")):
            response = self.client.post(reverse("inventory:setup_flash"), {"action": "check"}, follow=True)
        self.assertContains(response, "refused")
        self.assertContains(response, "Flashing is not the problem")

    def test_check_reports_a_service_whose_health_check_fails(self):
        with mock.patch("requests.get", return_value=self.health(status=500)):
            response = self.client.post(reverse("inventory:setup_flash"), {"action": "check"}, follow=True)
        self.assertContains(response, "HTTP 500")

    def test_a_board_that_is_not_there_is_never_reported_as_a_pass(self):
        """The whole point of the check. The Pi answers, the board does not, and the person
        is told which of the two is broken."""
        with mock.patch("requests.get", return_value=self.health()), \
             mock.patch("requests.post", return_value=self.demo(status=502)) as demo_call:
            response = self.client.post(reverse("inventory:setup_flash"), {"action": "check"}, follow=True)
        self.assertContains(response, "couldn&#x27;t reach the board", html=False)
        self.assertContains(response, "serial channel")
        self.assertEqual(demo_call.call_count, 1)
        tags = [message.tags for message in response.context["messages"]]
        self.assertEqual(tags, ["error"])
        self.assertNotContains(response, "ran the demo")

    def test_check_passes_when_the_board_answers_and_turns_the_demo_off_after(self):
        """The demo is a toggle that stays on until told otherwise, so the check has to
        undo it — a workshop left lit up by a browser button is not a feature."""
        with mock.patch("requests.get", return_value=self.health()), \
             mock.patch("requests.post", return_value=self.demo()) as demo_call, \
             mock.patch("inventory.views.setup.time.sleep"):
            response = self.client.post(reverse("inventory:setup_flash"), {"action": "check"}, follow=True)
        self.assertContains(response, "ran the demo")
        self.assertEqual(demo_call.call_count, 2)
        first, second = demo_call.call_args_list
        self.assertEqual(first.kwargs["json"], {"on": True})
        self.assertEqual(second.kwargs["json"], {"on": False})

    def test_the_check_sends_the_shared_secret(self):
        """Both calls, not just the health check. The demo is the request that actually
        reaches the board, and the one the Pi refuses without the key — asserting only the
        first would leave the important one unguarded."""
        with mock.patch("requests.get", return_value=self.health()) as health_call, \
             mock.patch("requests.post", return_value=self.demo()) as demo_call, \
             mock.patch("inventory.views.setup.time.sleep"):
            self.client.post(reverse("inventory:setup_flash"), {"action": "check"})
        self.assertEqual(health_call.call_args.kwargs["headers"]["X-Api-Key"], "shared-secret")
        self.assertEqual(demo_call.call_count, 2)
        for call in demo_call.call_args_list:
            self.assertEqual(call.kwargs["headers"]["X-Api-Key"], "shared-secret")

    def test_a_demo_that_errors_is_reported_with_its_status(self):
        with mock.patch("requests.get", return_value=self.health()), \
             mock.patch("requests.post", return_value=self.demo(status=403)):
            response = self.client.post(reverse("inventory:setup_flash"), {"action": "check"}, follow=True)
        self.assertContains(response, "HTTP 403")

    def test_the_demo_request_failing_outright_is_reported(self):
        import requests

        with mock.patch("requests.get", return_value=self.health()), \
             mock.patch("requests.post", side_effect=requests.Timeout("timed out")):
            response = self.client.post(reverse("inventory:setup_flash"), {"action": "check"}, follow=True)
        self.assertContains(response, "timed out")

    def test_a_bare_post_moves_on_without_claiming_anything_was_saved(self):
        """There is nothing to save here, so it must not say "Saved" — it moves on."""
        response = self.client.post(reverse("inventory:setup_flash"), {}, follow=True)
        self.assertNotContains(response, "Saved")
        self.assertEqual(response.redirect_chain, [(reverse("inventory:setup_printer"), 302)])

    def test_it_sits_between_lights_and_printer_in_the_wizard(self):
        keys = [step.key for step in wizard.visible_steps()]
        self.assertEqual(keys.index("flash"), keys.index("lights") + 1)
        self.assertEqual(keys.index("printer"), keys.index("flash") + 1)

    def test_it_is_skippable(self):
        """Seth's requirement, and the app's own rule: nothing here may be compulsory.
        A step that is `required` shows up in the "you haven't finished" nudge, and a
        workshop with no LED strips should never be nagged about flashing a board."""
        step = wizard.step_by_key("flash")
        self.assertFalse(step.required)
        self.assertEqual(wizard.required_outstanding(), [])

    def test_it_appears_on_the_setup_hub_so_it_can_be_reached_later(self):
        response = self.client.get(reverse("inventory:setup_hub"))
        self.assertContains(response, reverse("inventory:setup_flash"))


class PrinterStepTests(WizardFlowTestCase):
    def setUp(self):
        self.create_account()

    def test_it_saves_the_address_and_the_driver(self):
        self.client.post(
            reverse("inventory:setup_printer"),
            {"action": "save", "label_printer_url": "pi:9100", "label_printer_key": "k", "label_driver": "brother_ql"},
        )
        site = SiteSettings.load()
        self.assertEqual(site.label_printer_url, "http://pi:9100")
        self.assertEqual(site.label_printer_key, "k")
        self.assertEqual(site.label_driver, "brother_ql")

    def test_an_unknown_driver_falls_back_to_zpl(self):
        """A driver name the renderer does not know would produce bytes no printer
        understands, which looks like broken hardware."""
        self.client.post(
            reverse("inventory:setup_printer"),
            {"action": "save", "label_printer_url": "pi:9100", "label_driver": "made_up"},
        )
        self.assertEqual(SiteSettings.load().label_driver, "zpl")

    def test_it_saves_the_dots_per_inch(self):
        self.client.post(
            reverse("inventory:setup_printer"),
            {"action": "save", "label_printer_url": "pi:9100", "label_dpi": "300"},
        )
        self.assertEqual(SiteSettings.load().label_dpi, "300")

    def test_blank_dots_per_inch_stays_blank(self):
        """Blank means "use the resolution that goes with the printer type". Storing a
        zero instead would render a zero-pixel label with nothing to explain it."""
        self.client.post(
            reverse("inventory:setup_printer"),
            {"action": "save", "label_printer_url": "pi:9100", "label_dpi": ""},
        )
        self.assertEqual(SiteSettings.load().label_dpi, "")

    def test_a_nonsense_dots_per_inch_is_refused_and_the_old_value_kept(self):
        """Rather than stored and then ignored by the renderer, which leaves the owner
        unable to tell which of the two happened."""
        site = SiteSettings.load()
        site.label_dpi = "203"
        site.save()

        response = self.client.post(
            reverse("inventory:setup_printer"),
            {"action": "save", "label_printer_url": "pi:9100", "label_dpi": "12000"},
            follow=True,
        )

        self.assertContains(response, "between 50 and 2400")
        self.assertEqual(SiteSettings.load().label_dpi, "203")

    def test_the_test_button_actually_prints(self):
        """A printer that answers a health check but prints nothing is the common
        failure, so the test sends a real label."""
        with mock.patch("inventory.label_printing.print_label", return_value=(True, None)) as sent:
            response = self.client.post(
                reverse("inventory:setup_printer"),
                {"action": "test", "label_printer_url": "pi:9100", "label_driver": "zpl"},
                follow=True,
            )
        sent.assert_called_once()
        self.assertContains(response, "check the printer")

    def test_a_failed_print_is_reported(self):
        with mock.patch("inventory.label_printing.print_label", return_value=(False, "connection refused")):
            response = self.client.post(
                reverse("inventory:setup_printer"),
                {"action": "test", "label_printer_url": "pi:9100", "label_driver": "zpl"},
                follow=True,
            )
        self.assertContains(response, "connection refused")

    def test_testing_with_no_printer_set_says_so(self):
        response = self.client.post(reverse("inventory:setup_printer"), {"action": "test", "label_printer_url": ""}, follow=True)
        self.assertContains(response, "No label printer address")


class ReferenceStepTests(WizardFlowTestCase):
    def setUp(self):
        self.create_account()

    def test_the_starter_set_can_be_loaded_from_the_wizard(self):
        with override_settings(ARCHIVE_ON_SAVE=False):
            self.client.post(reverse("inventory:setup_reference"), {"action": "load"})
        self.assertGreater(ReferenceDoc.objects.count(), 0)

    def test_archiving_from_the_wizard_is_bounded(self):
        """A setup page must not sit there fetching twenty-seven documents."""
        category = ReferenceCategory.objects.first()
        for i in range(9):
            ReferenceDoc.objects.create(title=f"D{i}", category=category, external_url="https://x.test/d.pdf")

        with mock.patch("inventory.archiving.archive_reference_doc") as archive:
            from inventory.archiving import ArchiveResult

            archive.return_value = ArchiveResult(ok=True)
            self.client.post(reverse("inventory:setup_reference"), {"action": "archive"})
        self.assertLessEqual(archive.call_count, 5)

    def test_a_failed_archive_is_reported_not_raised(self):
        category = ReferenceCategory.objects.first()
        ReferenceDoc.objects.create(title="D", category=category, external_url="https://x.test/d.pdf")

        from inventory.archiving import ArchiveResult

        with mock.patch("inventory.archiving.archive_reference_doc", return_value=ArchiveResult(ok=False, error="nope")):
            response = self.client.post(reverse("inventory:setup_reference"), {"action": "archive"})
        self.assertEqual(response.status_code, 302)


class CommunityStepTests(WizardFlowTestCase):
    def setUp(self):
        self.create_account()

    def test_a_lookup_saves_the_district_point(self):
        from inventory.geocoding import GeoResult

        with mock.patch("inventory.geocoding.lookup", return_value=GeoResult(ok=True, lat=51.501, lon=-0.141, label="SW1A", source="outcode")):
            self.client.post(reverse("inventory:setup_community"), {"action": "lookup", "where": "SW1A 1AA", "country": "GB"})

        profile = CommunityProfile.load()
        self.assertTrue(profile.has_location)
        self.assertEqual(profile.location_source, "outcode")

    def test_a_failed_lookup_leaves_the_previous_point_alone(self):
        """A typo must not wipe a location that was working."""
        from inventory.geocoding import GeoResult

        profile = CommunityProfile.load()
        profile.location_lat, profile.location_lon = 51.5, -0.14
        profile.save()

        with mock.patch("inventory.geocoding.lookup", return_value=GeoResult(ok=False, error="not found")):
            self.client.post(reverse("inventory:setup_community"), {"action": "lookup", "where": "nonsense"})

        profile.refresh_from_db()
        self.assertEqual(profile.location_lat, 51.5, "a typo must not wipe a working location")

    def test_the_country_is_kept_alongside_the_opt_in(self):
        """The country decides whether postcodes or ZIP codes get expected, so it is
        saved whichever button was pressed."""
        self.client.post(reverse("inventory:setup_community"), {"action": "save", "country": "gb"})
        self.assertEqual(SiteSettings.load().country, "GB")

    def test_the_opt_in_is_off_unless_ticked(self):
        self.client.post(reverse("inventory:setup_community"), {"action": "save"})
        self.assertFalse(CommunityProfile.load().discoverable)

    def test_the_opt_in_is_saved_when_ticked(self):
        self.client.post(reverse("inventory:setup_community"), {"action": "save", "discoverable": "1"})
        self.assertTrue(CommunityProfile.load().discoverable)

    def test_the_opt_in_can_be_turned_back_off(self):
        """The revocable part, which is the whole point of it being a checkbox."""
        self.client.post(reverse("inventory:setup_community"), {"action": "save", "discoverable": "1"})
        self.client.post(reverse("inventory:setup_community"), {"action": "save"})
        self.assertFalse(CommunityProfile.load().discoverable)


class AccessStepTests(WizardFlowTestCase):
    def setUp(self):
        self.create_account()

    def test_the_address_is_saved(self):
        self.client.post(reverse("inventory:setup_access"), {"action": "save", "public_url": "parts.example.com"})
        self.assertEqual(SiteSettings.load().public_url, "http://parts.example.com")

    def test_the_check_reports_a_healthy_site(self):
        class R:
            status_code = 302

        with mock.patch("requests.get", return_value=R()):
            response = self.client.post(
                reverse("inventory:setup_access"), {"action": "check", "public_url": "https://parts.example.com"},
                follow=True,
            )
        self.assertContains(response, "reachable")

    def test_the_check_reports_a_server_error(self):
        class R:
            status_code = 502

        with mock.patch("requests.get", return_value=R()):
            response = self.client.post(
                reverse("inventory:setup_access"), {"action": "check", "public_url": "https://parts.example.com"},
                follow=True,
            )
        self.assertContains(response, "502")

    def test_the_check_refuses_something_that_is_not_a_web_address(self):
        # Asserted on a fragment: Django autoescapes the apostrophe in the real
        # message, so the full sentence never appears literally in the HTML.
        response = self.client.post(
            reverse("inventory:setup_access"), {"action": "check", "public_url": "not a url"}, follow=True
        )
        self.assertContains(response, "look like a web address")

    def test_the_check_says_so_when_nothing_is_pasted(self):
        response = self.client.post(reverse("inventory:setup_access"), {"action": "check", "public_url": ""}, follow=True)
        self.assertContains(response, "Paste the address")


class FinishTests(WizardFlowTestCase):
    def setUp(self):
        self.create_account()

    def test_finishing_marks_setup_complete(self):
        self.client.post(reverse("inventory:setup_finish"))
        self.assertTrue(SiteSettings.load().setup_complete)

    def test_finishing_takes_you_into_the_app(self):
        response = self.client.post(reverse("inventory:setup_finish"))
        self.assertRedirects(response, reverse("inventory:browse"))

    def test_the_app_still_works_afterwards(self):
        self.client.post(reverse("inventory:setup_finish"))
        self.assertEqual(self.client.get(reverse("inventory:browse")).status_code, 200)


class SettingsAfterwardsTests(WizardFlowTestCase):
    """The pages are settings, not a one-shot wizard — that's the design."""

    def setUp(self):
        self.create_account()
        self.client.post(reverse("inventory:setup_finish"))

    def test_every_step_stays_reachable(self):
        for step in wizard.visible_steps():
            with self.subTest(step=step.key):
                self.assertEqual(self.client.get(reverse(step.url_name)).status_code, 200)

    def test_the_finish_page_stays_reachable(self):
        self.assertEqual(self.client.get(reverse("inventory:setup_finish")).status_code, 200)

    def test_the_name_can_be_changed_afterwards(self):
        """The reason these aren't one-shot: renaming shouldn't need a rebuild."""
        self.client.post(reverse("inventory:setup_site"), {"site_name": "Renamed", "timezone": "UTC", "country": "GB"})
        self.assertEqual(SiteSettings.load().site_name, "Renamed")

    def test_the_account_step_is_gone_once_set_up(self):
        self.assertNotIn("account", [s.key for s in wizard.visible_steps()])

    def test_an_unknown_step_url_is_a_404_not_a_crash(self):
        self.assertEqual(self.client.get("/setup/nonsense/").status_code, 404)


class StepRegistryTests(TestCase):
    def test_every_step_has_a_url_that_resolves(self):
        for step in wizard.visible_steps() + [wizard.FINISH]:
            with self.subTest(step=step.key):
                self.assertTrue(reverse(step.url_name))

    def test_the_next_step_walks_the_visible_order(self):
        steps = wizard.visible_steps()
        self.assertEqual(wizard.next_step_after(steps[0].key), steps[1])

    def test_the_last_step_leads_to_finish(self):
        self.assertEqual(wizard.next_step_after(wizard.ACCESS.key), wizard.FINISH)

    def test_next_step_from_an_unknown_key_is_finish(self):
        self.assertEqual(wizard.next_step_after("nonsense"), wizard.FINISH)
