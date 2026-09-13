"""LED "find the part" behaviour.

Everything here is driven through the Pi's controller over HTTP, so these tests
mock `requests.post` rather than reaching the network. Two things matter most:

1. The row/column split -- a drawer's `-left` strip shows the ROW and its
   `-right` strip shows the COLUMN, never both on one strip. This went through
   three rounds of live correction (see HANDOFF item 19), so it is worth
   pinning hard.
2. Every failure path degrades to a friendly message rather than a 500.
"""
from unittest import mock

import requests
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.models import DrawerLedSegment
from inventory.views import _locate_drawer

from .factories import make_container, make_drawer, make_part, make_stock, make_user

LED_ON = override_settings(LED_CONTROLLER_URL="https://led.example.test", LED_CONTROLLER_KEY="secret")


def segment(drawer, strip, start=0, count=10):
    return DrawerLedSegment.objects.create(
        drawer=drawer, led_strip=strip, led_start_index=start, led_count=count
    )


class LocateDrawerPayloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.container = make_container(number=38, container_type="cabinets")
        cls.drawer = make_drawer(cls.container, label="drawer 5")

    @LED_ON
    @mock.patch("requests.post")
    def test_row_goes_only_to_the_left_strip(self, post):
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left", start=20)
        segment(self.drawer, "cabinet1-right", start=20)

        _locate_drawer(self.drawer, row=3, col=1)

        payloads = {c.kwargs["json"]["strip"]: c.kwargs["json"] for c in post.call_args_list}
        self.assertEqual(payloads["cabinet1-left"]["row"], 3)
        self.assertNotIn("col", payloads["cabinet1-left"])
        self.assertEqual(payloads["cabinet1-right"]["col"], 1)
        self.assertNotIn("row", payloads["cabinet1-right"])

    @LED_ON
    @mock.patch("requests.post")
    def test_a_drawer_only_locate_sends_no_row_or_col(self, post):
        """Clicking Locate on the drawer itself should just breathe -- no bin
        row/column detail, since no bin was specified."""
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left")
        segment(self.drawer, "cabinet1-right")

        _locate_drawer(self.drawer)

        for call in post.call_args_list:
            self.assertNotIn("row", call.kwargs["json"])
            self.assertNotIn("col", call.kwargs["json"])

    @LED_ON
    @mock.patch("requests.post")
    def test_start_index_and_count_are_passed_through(self, post):
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left", start=37, count=9)

        _locate_drawer(self.drawer)

        payload = post.call_args_list[0].kwargs["json"]
        self.assertEqual(payload["start_index"], 37)
        self.assertEqual(payload["count"], 9)

    @LED_ON
    @mock.patch("requests.post")
    def test_the_api_key_header_is_sent(self, post):
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left")

        _locate_drawer(self.drawer)

        self.assertEqual(post.call_args_list[0].kwargs["headers"], {"X-Api-Key": "secret"})

    @LED_ON
    @mock.patch("requests.post")
    def test_it_posts_to_the_locate_endpoint(self, post):
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left")

        _locate_drawer(self.drawer)

        self.assertEqual(post.call_args_list[0].args[0], "https://led.example.test/locate")

    @LED_ON
    @mock.patch("requests.post")
    def test_lit_count_reflects_successful_posts(self, post):
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left")
        segment(self.drawer, "cabinet1-right")

        lit, errors, reason = _locate_drawer(self.drawer)
        self.assertEqual(lit, 2)
        self.assertEqual(errors, [])
        self.assertIsNone(reason)

    @LED_ON
    @mock.patch("requests.post", side_effect=requests.ConnectionError("refused"))
    def test_a_failing_strip_is_reported_but_does_not_raise(self, post):
        segment(self.drawer, "cabinet1-left")
        segment(self.drawer, "cabinet1-right")

        lit, errors, reason = _locate_drawer(self.drawer)
        self.assertEqual(lit, 0)
        self.assertEqual(len(errors), 2)
        self.assertIn("cabinet1-left", errors[0])
        self.assertIsNone(reason)

    @LED_ON
    @mock.patch("requests.post")
    def test_one_failing_strip_does_not_stop_the_other(self, post):
        segment(self.drawer, "cabinet1-left")
        segment(self.drawer, "cabinet1-right")
        healthy = mock.Mock()
        healthy.raise_for_status.return_value = None
        post.side_effect = [healthy, requests.ConnectionError("refused")]

        lit, errors, _ = _locate_drawer(self.drawer)
        self.assertEqual(lit, 1)
        self.assertEqual(len(errors), 1)

    def test_no_segments_reports_the_mapping_gap(self):
        lit, errors, reason = _locate_drawer(self.drawer)
        self.assertEqual(lit, 0)
        self.assertEqual(errors, [])
        self.assertIn("no LED mapping configured", reason)

    def test_no_controller_configured_reports_that_separately(self):
        """'not configured' and 'not mapped' are different problems and the user
        is told which one they have."""
        segment(self.drawer, "cabinet1-left")
        with override_settings(LED_CONTROLLER_URL=""):
            lit, errors, reason = _locate_drawer(self.drawer)
        self.assertEqual(lit, 0)
        self.assertIn("No LED controller configured", reason)


class LocateViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.container = make_container(number=38, container_type="cabinets")
        cls.drawer = make_drawer(cls.container, label="drawer 5")

    def setUp(self):
        self.client.force_login(self.user)

    def test_drawer_locate_reports_the_missing_mapping(self):
        resp = self.client.post(reverse("inventory:locate_drawer_led", args=[self.drawer.pk]), follow=True)
        self.assertContains(resp, "no LED mapping configured")

    @LED_ON
    @mock.patch("requests.post")
    def test_drawer_locate_succeeds_and_redirects_back(self, post):
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left")

        resp = self.client.post(reverse("inventory:locate_drawer_led", args=[self.drawer.pk]))
        self.assertRedirects(resp, reverse("inventory:drawer_detail", args=[self.drawer.pk]))

    @LED_ON
    @mock.patch("requests.post")
    def test_stock_item_locate_passes_its_bin_row(self, post):
        """A part with a known bin conveys row detail to the animation."""
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left")
        segment(self.drawer, "cabinet1-right")
        stock = make_stock(make_part(), self.container, drawer=self.drawer, quantity=1, bin_number=13)

        self.client.post(reverse("inventory:locate_stock_item", args=[stock.pk]))

        payloads = {c.kwargs["json"]["strip"]: c.kwargs["json"] for c in post.call_args_list}
        self.assertEqual(payloads["cabinet1-left"]["row"], 4)   # bin 13 -> row 4
        self.assertEqual(payloads["cabinet1-right"]["col"], 1)  # bin 13 -> column 1

    @LED_ON
    @mock.patch("requests.post")
    def test_stock_item_locate_without_a_bin_sends_no_row(self, post):
        post.return_value.raise_for_status.return_value = None
        segment(self.drawer, "cabinet1-left")
        stock = make_stock(make_part(), self.container, drawer=self.drawer, quantity=1)

        self.client.post(reverse("inventory:locate_stock_item", args=[stock.pk]))

        self.assertNotIn("row", post.call_args_list[0].kwargs["json"])


class LightControlsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()

    def setUp(self):
        self.client.force_login(self.user)

    def test_light_controls_page_renders(self):
        resp = self.client.get(reverse("inventory:light_controls"))
        self.assertEqual(resp.status_code, 200)

    @override_settings(LED_CONTROLLER_URL="")
    def test_room_light_reports_not_configured_rather_than_erroring(self):
        """Explicitly blanks the URL instead of relying on the ambient default.

        This test originally assumed LED_CONTROLLER_URL was unset -- true on a
        dev machine with no .env, false inside the production container, where it
        points at the real Pi. That made it fire a genuine POST and switch the
        workshop cabinet lights on during a test run. Never depend on ambient
        settings for anything that can reach hardware.
        """
        resp = self.client.post(reverse("inventory:led_room_light"), {"on": "1"}, follow=True)
        self.assertContains(resp, "No LED controller configured")

    @LED_ON
    @mock.patch("requests.post")
    def test_room_light_on_posts_on_true(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_room_light"), {"on": "1"})

        self.assertEqual(post.call_args_list[0].args[0], "https://led.example.test/room_light")
        self.assertTrue(post.call_args_list[0].kwargs["json"]["on"])

    @LED_ON
    @mock.patch("requests.post")
    def test_room_light_off_posts_on_false(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_room_light"), {"on": "0"})
        self.assertFalse(post.call_args_list[0].kwargs["json"]["on"])

    @LED_ON
    @mock.patch("requests.post")
    def test_room_light_converts_hex_colour_to_an_rgb_triple(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_room_light"), {"on": "1", "color": "#ff8000"})
        self.assertEqual(post.call_args_list[0].kwargs["json"]["color"], [255, 128, 0])

    @LED_ON
    @mock.patch("requests.post")
    def test_colour_is_ignored_when_turning_the_light_off(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_room_light"), {"on": "0", "color": "#ff8000"})
        self.assertNotIn("color", post.call_args_list[0].kwargs["json"])

    @LED_ON
    @mock.patch("requests.post")
    def test_a_malformed_colour_is_dropped_rather_than_crashing(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_room_light"), {"on": "1", "color": "banana"})
        self.assertNotIn("color", post.call_args_list[0].kwargs["json"])

    @LED_ON
    @mock.patch("requests.post")
    def test_demo_on_and_off(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_demo"), {"on": "1"})
        self.assertTrue(post.call_args_list[0].kwargs["json"]["on"])

        self.client.post(reverse("inventory:led_demo"), {"on": "0"})
        self.assertFalse(post.call_args_list[1].kwargs["json"]["on"])

    @LED_ON
    @mock.patch("requests.post")
    def test_brightness_percentage_is_normalised_to_zero_to_one(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_set_defaults"), {"brightness": "50"})
        self.assertAlmostEqual(post.call_args_list[0].kwargs["json"]["brightness"], 0.5)

    @LED_ON
    @mock.patch("requests.post")
    def test_brightness_is_clamped_to_the_valid_range(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_set_defaults"), {"brightness": "500"})
        self.assertEqual(post.call_args_list[0].kwargs["json"]["brightness"], 1.0)

    @LED_ON
    @mock.patch("requests.post")
    def test_nonsense_brightness_is_skipped_not_fatal(self, post):
        post.return_value.raise_for_status.return_value = None
        self.client.post(reverse("inventory:led_set_defaults"), {"brightness": "bright"})
        self.assertNotIn("brightness", post.call_args_list[0].kwargs["json"])

    @LED_ON
    @mock.patch("requests.post", side_effect=requests.ConnectionError("refused"))
    def test_unreachable_controller_surfaces_an_error_message(self, post):
        """Asserted on a fragment without the apostrophe: the message is
        HTML-escaped in the rendered page (Couldn&#x27;t), so matching the raw
        Python string would fail on the escaping rather than the behaviour."""
        resp = self.client.post(reverse("inventory:led_demo"), {"on": "1"}, follow=True)
        self.assertContains(resp, "reach the LED controller")
