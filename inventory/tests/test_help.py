"""In-app help.

Mostly a guard against the boring failure: a topic listed in the registry with no
template behind it, which is a 500 on a page a confused new user is most likely to
click. The registry is the source of truth, so the test walks it.
"""
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from inventory.views.help import TOPICS

from .factories import make_user

HELP_DIR = Path(__file__).resolve().parent.parent / "templates" / "inventory" / "help"


class HelpPageTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user())

    def test_the_index_lists_every_topic(self):
        response = self.client.get(reverse("inventory:help_index"))
        for topic in TOPICS:
            with self.subTest(topic=topic.slug):
                self.assertContains(response, topic.title)

    def test_every_registered_topic_renders(self):
        """A topic with no template is a 500 on the page a stuck user is most likely
        to open."""
        for topic in TOPICS:
            with self.subTest(topic=topic.slug):
                response = self.client.get(reverse("inventory:help_topic", args=[topic.slug]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, topic.title)

    def test_every_topic_template_has_a_registry_entry(self):
        """The other direction: a template nobody links to is dead weight."""
        on_disk = {p.stem for p in HELP_DIR.glob("*.html")} - {"index"}
        self.assertEqual(on_disk, {t.slug for t in TOPICS})

    def test_an_unknown_topic_is_a_404(self):
        """A stale bookmark should be visibly stale, not quietly redirected."""
        self.assertEqual(self.client.get(reverse("inventory:help_topic", args=["nonsense"])).status_code, 404)

    def test_help_needs_a_login(self):
        self.client.logout()
        response = self.client.get(reverse("inventory:help_index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_topics_are_reachable_from_the_index(self):
        response = self.client.get(reverse("inventory:help_index"))
        for topic in TOPICS:
            with self.subTest(topic=topic.slug):
                self.assertContains(response, reverse("inventory:help_topic", args=[topic.slug]))

    def test_every_topic_summarises_itself(self):
        """An empty blurb renders as a blank line on the index, which looks broken."""
        for topic in TOPICS:
            with self.subTest(topic=topic.slug):
                self.assertTrue(topic.summary.strip())

    def test_there_is_a_page_about_organising(self):
        """The advice about layout is the part that is genuinely hard to work out from
        the interface, so it isn't allowed to quietly disappear."""
        self.assertIn("organising", {t.slug for t in TOPICS})
