"""Pushing LED configuration to the Pi.

The app knows which LEDs belong to which drawer. It cannot know which strip is
plugged into which output on the Scorpio board — that is physical wiring, visible
only to the person holding the cable. So the owner records it, and the wizard sends
it to the Pi, because /locate runs there and reads strip_map.json from disk.

The failure modes worth guarding are the quiet ones: a channel saved when the box
was left blank (which would light the wrong strip, since 0 is a real output), and a
Pi still running old code, which answers 404 and would otherwise look like the push
worked.
"""

import importlib.util
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from ..models import Container, Drawer, DrawerLedSegment, LedStrip
from ..views.setup import _push_strip_map, _strip_rows

PI_SERVER = Path(__file__).resolve().parent.parent.parent / "led-controller" / "pi" / "server.py"


def load_pi_server():
    """Import the Pi's server module without needing pyserial or a serial port.

    `import serial` is wrapped in a try/except in that file for exactly this reason:
    the strip-map logic is most likely to be edited on a machine that isn't a Pi.
    """
    spec = importlib.util.spec_from_file_location("led_pi_server", PI_SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LedStripModelTests(TestCase):
    def test_it_reads_back_as_name_and_channel(self):
        strip = LedStrip.objects.create(name="cabinet1-left", channel=3)
        self.assertEqual(str(strip), "cabinet1-left (channel 3)")

    def test_a_recorded_channel_counts_as_wired(self):
        self.assertTrue(LedStrip.objects.create(name="a", channel=3).is_wired)

    def test_a_strip_named_but_not_yet_plugged_in_is_not_wired(self):
        # "Named but not plugged in" is a normal halfway state while wiring a cabinet,
        # so it has to be representable rather than forced to a number.
        self.assertFalse(LedStrip.objects.create(name="a", channel=None).is_wired)

    def test_names_are_unique(self):
        from django.db import IntegrityError

        LedStrip.objects.create(name="dup", channel=1)
        with self.assertRaises(IntegrityError):
            LedStrip.objects.create(name="dup", channel=2)


class StripRowTests(TestCase):
    def _drawer(self, label="D1"):
        # Drawer hangs off a Container, not a Location -- the location lives on the
        # container. Built here rather than with a factory because this test needs the
        # drawer and nothing else about the workshop.
        container = Container.objects.create(number=1, container_type="cabinets")
        return Drawer.objects.create(container=container, label=label)

    def test_it_lists_strips_that_only_appear_in_drawer_mappings(self):
        # The name first shows up in a drawer's mapping, before anyone has said which
        # channel it is on. The owner still needs to see it, or it can never be set.
        DrawerLedSegment.objects.create(drawer=self._drawer(), led_strip="cabinet1-left", led_start_index=0, led_count=30)
        rows = _strip_rows()
        self.assertEqual([r["name"] for r in rows], ["cabinet1-left"])
        self.assertFalse(rows[0]["recorded"])

    def test_it_lists_recorded_strips_with_their_channel(self):
        LedStrip.objects.create(name="cabinet1-left", channel=4)
        rows = _strip_rows()
        self.assertEqual(rows[0]["channel"], 4)
        self.assertTrue(rows[0]["recorded"])

    def test_a_strip_in_both_places_appears_once(self):
        # The union is the point: one row per strip, whatever it is known from.
        DrawerLedSegment.objects.create(drawer=self._drawer(), led_strip="cabinet1-left", led_start_index=0, led_count=30)
        LedStrip.objects.create(name="cabinet1-left", channel=4)
        rows = _strip_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], 4)

    def test_it_is_sorted_by_name(self):
        for name in ("zebra", "alpha", "mike"):
            LedStrip.objects.create(name=name, channel=0)
        self.assertEqual([r["name"] for r in _strip_rows()], ["alpha", "mike", "zebra"])


class SaveChannelsTests(TestCase):
    def setUp(self):
        self.user = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model().objects.create_user(
            username="owner", password="x"
        )
        self.client.force_login(self.user)
        self.url = reverse("inventory:setup_lights")

    def test_it_records_a_channel(self):
        response = self.client.post(
            self.url,
            {"action": "save_channels", "strip_name": ["cabinet1-left"], "channel_cabinet1-left": "3"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LedStrip.objects.get(name="cabinet1-left").channel, 3)

    def test_a_blank_box_clears_the_channel_rather_than_saving_zero(self):
        # Channel 0 is a real output. Saving a blank as 0 would light up a strip the
        # owner has not wired yet, which is the kind of bug that only shows up when
        # someone presses the button and the wrong drawer glows.
        LedStrip.objects.create(name="cabinet1-left", channel=3)
        self.client.post(
            self.url,
            {"action": "save_channels", "strip_name": ["cabinet1-left"], "channel_cabinet1-left": ""},
            follow=True,
        )
        self.assertFalse(LedStrip.objects.filter(name="cabinet1-left").exists())

    def test_it_rejects_a_channel_outside_the_scorpio_range(self):
        self.client.post(
            self.url,
            {"action": "save_channels", "strip_name": ["s"], "channel_s": "9"},
            follow=True,
        )
        self.assertFalse(LedStrip.objects.filter(name="s").exists())

    def test_it_rejects_a_channel_that_is_not_a_number(self):
        self.client.post(
            self.url,
            {"action": "save_channels", "strip_name": ["s"], "channel_s": "left"},
            follow=True,
        )
        self.assertFalse(LedStrip.objects.filter(name="s").exists())

    def test_it_accepts_channel_zero(self):
        # The boundary that a falsy-check would get wrong.
        self.client.post(
            self.url,
            {"action": "save_channels", "strip_name": ["s"], "channel_s": "0"},
            follow=True,
        )
        self.assertEqual(LedStrip.objects.get(name="s").channel, 0)

    def test_it_handles_several_strips_at_once(self):
        self.client.post(
            self.url,
            {
                "action": "save_channels",
                "strip_name": ["a", "b"],
                "channel_a": "0",
                "channel_b": "7",
            },
            follow=True,
        )
        self.assertEqual(LedStrip.objects.get(name="a").channel, 0)
        self.assertEqual(LedStrip.objects.get(name="b").channel, 7)


class PushStripMapTests(TestCase):
    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="http://pi:5000")
    def test_it_refuses_to_push_with_no_channels_recorded(self, _url):
        ok, detail = _push_strip_map()
        self.assertFalse(ok)
        self.assertIn("No strip channels recorded", detail)

    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="")
    def test_it_says_so_when_no_controller_is_configured(self, _url):
        LedStrip.objects.create(name="a", channel=0)
        ok, detail = _push_strip_map()
        self.assertFalse(ok)
        self.assertIn("No LED controller address", detail)

    @mock.patch("inventory.views.setup.hardware_config.led_key", return_value="")
    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="http://pi:5000")
    @mock.patch("requests.post")
    def test_it_posts_the_mapping(self, post, _url, _key):
        post.return_value.status_code = 200
        LedStrip.objects.create(name="a", channel=0)
        LedStrip.objects.create(name="b", channel=7)
        ok, detail = _push_strip_map()
        self.assertTrue(ok, detail)
        self.assertEqual(post.call_args.kwargs["json"], {"strips": {"a": 0, "b": 7}})
        self.assertTrue(post.call_args.args[0].endswith("/strips"))

    @mock.patch("inventory.views.setup.hardware_config.led_key", return_value="")
    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="http://pi:5000")
    @mock.patch("requests.post")
    def test_a_strip_with_no_channel_recorded_is_left_out(self, post, _url, _key):
        # The Pi has no way to represent "light nothing", so an unwired strip must not
        # be sent as a null -- it would be rejected, and the whole push would fail
        # because of a strip the owner deliberately hasn't plugged in yet.
        post.return_value.status_code = 200
        LedStrip.objects.create(name="wired", channel=0)
        LedStrip.objects.create(name="unwired", channel=None)
        ok, detail = _push_strip_map()
        self.assertTrue(ok, detail)
        self.assertEqual(post.call_args.kwargs["json"], {"strips": {"wired": 0}})

    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="http://pi:5000")
    @mock.patch("requests.post")
    def test_all_strips_unwired_reads_as_nothing_recorded(self, post, _url):
        LedStrip.objects.create(name="a", channel=None)
        ok, detail = _push_strip_map()
        self.assertFalse(ok)
        self.assertIn("No strip channels recorded", detail)
        post.assert_not_called()

    @mock.patch("inventory.views.setup.hardware_config.led_key", return_value="secret")
    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="http://pi:5000")
    @mock.patch("requests.post")
    def test_it_sends_the_shared_key_when_one_is_set(self, post, _url, _key):
        post.return_value.status_code = 200
        LedStrip.objects.create(name="a", channel=0)
        _push_strip_map()
        self.assertEqual(post.call_args.kwargs["headers"], {"X-Api-Key": "secret"})

    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="http://pi:5000")
    @mock.patch("requests.post")
    def test_a_404_says_the_pi_is_running_old_code(self, post, _url):
        # Without this the owner sees a bare failure and has no way to know the fix is
        # to update and restart the Pi, which is the single most likely cause.
        post.return_value.status_code = 404
        LedStrip.objects.create(name="a", channel=0)
        ok, detail = _push_strip_map()
        self.assertFalse(ok)
        self.assertIn("404", detail)
        self.assertIn("older version", detail)

    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="http://pi:5000")
    @mock.patch("requests.post")
    def test_the_pis_own_error_message_is_passed_through(self, post, _url):
        post.return_value.status_code = 400
        post.return_value.json.return_value = {"error": "channel for 'a' must be 0-7"}
        LedStrip.objects.create(name="a", channel=0)
        ok, detail = _push_strip_map()
        self.assertFalse(ok)
        self.assertIn("must be 0-7", detail)

    @mock.patch("inventory.views.setup.hardware_config.led_url", return_value="http://pi:5000")
    @mock.patch("requests.post", side_effect=__import__("requests").RequestException("no route"))
    def test_an_unreachable_pi_is_reported_not_raised(self, _post, _url):
        LedStrip.objects.create(name="a", channel=0)
        ok, detail = _push_strip_map()
        self.assertFalse(ok)
        self.assertIn("no route", detail)


class PiStripMapTests(TestCase):
    """The Pi side, loaded as a module so its logic is testable off-Pi."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pi = load_pi_server()

    def test_the_module_imports_without_pyserial(self):
        # This is what makes the rest of this class possible, and it is why the serial
        # import is optional rather than at the top level.
        self.assertTrue(hasattr(self.pi, "validate_strip_map"))

    def test_it_accepts_a_sensible_mapping(self):
        cleaned, error = self.pi.validate_strip_map({"cabinet1-left": 0, "cabinet1-right": 7})
        self.assertEqual(error, "")
        self.assertEqual(cleaned, {"cabinet1-left": 0, "cabinet1-right": 7})

    def test_it_accepts_an_empty_mapping(self):
        cleaned, error = self.pi.validate_strip_map({})
        self.assertEqual((cleaned, error), ({}, ""))

    def test_it_rejects_a_channel_above_the_scorpio_range(self):
        cleaned, error = self.pi.validate_strip_map({"a": 8})
        self.assertIsNone(cleaned)
        self.assertIn("0-7", error)

    def test_it_rejects_a_negative_channel(self):
        cleaned, error = self.pi.validate_strip_map({"a": -1})
        self.assertIsNone(cleaned)
        self.assertIn("0-7", error)

    def test_it_rejects_a_channel_that_is_not_a_number(self):
        cleaned, error = self.pi.validate_strip_map({"a": "left"})
        self.assertIsNone(cleaned)
        self.assertIn("whole number", error)

    def test_it_rejects_a_boolean_channel(self):
        # bool is a subclass of int, so True would sail through a naive check and
        # become channel 1.
        cleaned, error = self.pi.validate_strip_map({"a": True})
        self.assertIsNone(cleaned)
        self.assertIn("whole number", error)

    def test_it_rejects_an_empty_strip_name(self):
        cleaned, error = self.pi.validate_strip_map({"   ": 1})
        self.assertIsNone(cleaned)
        self.assertIn("cannot be empty", error)

    def test_it_rejects_something_that_is_not_an_object(self):
        cleaned, error = self.pi.validate_strip_map(["a"])
        self.assertIsNone(cleaned)
        self.assertIn("object", error)

    def test_writing_replaces_the_file_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "strip_map.json")
            with mock.patch.object(self.pi, "STRIP_MAP_PATH", target):
                self.pi._write_strip_map({"b": 1, "a": 0})
                with open(target, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle), {"a": 0, "b": 1})

    def test_writing_leaves_no_temporary_file_behind(self):
        # The temp file is the whole point of the write-rename dance, but it must not
        # be left on the Pi afterwards.
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "strip_map.json")
            with mock.patch.object(self.pi, "STRIP_MAP_PATH", target):
                self.pi._write_strip_map({"a": 0})
                leftovers = [f for f in Path(tmp).iterdir() if f.name != "strip_map.json"]
                self.assertEqual(leftovers, [])

    def test_reading_a_missing_file_gives_an_empty_map_not_an_error(self):
        # A Pi that has never been configured should answer /locate with a clear
        # "not mapped" message, not crash on startup.
        with mock.patch.object(self.pi, "STRIP_MAP_PATH", "/nonexistent/strip_map.json"):
            self.assertEqual(self.pi._load_strip_map(), {})

    def test_reading_a_corrupt_file_gives_an_empty_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "strip_map.json")
            Path(target).write_text("{not json", encoding="utf-8")
            with mock.patch.object(self.pi, "STRIP_MAP_PATH", target):
                self.assertEqual(self.pi._load_strip_map(), {})
