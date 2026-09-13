"""Owning the reference library: categories, documents, ordering, archiving.

The feature being protected here is *control*. The library used to have four
categories baked into the source, so an owner could add a document but never the shelf
it belonged on. These tests assert that every part of it is theirs to change —
including the right to delete the entire shipped starter set.
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.models import ReferenceCategory, ReferenceDoc

from .factories import make_user


class ReferenceViewTestCase(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.category = ReferenceCategory.objects.create(name="Test shelf", key="test-shelf", order=10)


class LoginWallTests(ReferenceViewTestCase):
    def test_the_library_needs_a_login(self):
        self.client.logout()
        location = self.client.get(reverse("inventory:reference_list"))["Location"]
        self.assertTrue(location.startswith("/login/"), location)

    def test_the_manage_page_needs_a_login(self):
        self.client.logout()
        location = self.client.get(reverse("inventory:reference_manage"))["Location"]
        self.assertTrue(location.startswith("/login/"), location)


class CategoryEditingTests(ReferenceViewTestCase):
    def test_a_category_can_be_created_from_the_ui(self):
        """The core of the change: shelves are the owner's, not the source code's."""
        self.client.post(reverse("inventory:reference_category_add"), {"name": "Woodworking", "order": "50"})
        self.assertTrue(ReferenceCategory.objects.filter(name="Woodworking").exists())

    def test_the_key_is_derived_from_the_name(self):
        self.client.post(reverse("inventory:reference_category_add"), {"name": "Leather Working"})
        self.assertEqual(ReferenceCategory.objects.get(name="Leather Working").key, "leather-working")

    def test_a_duplicate_name_gets_a_distinct_key(self):
        """Keys are unique, and two people will eventually create two similar shelves."""
        self.client.post(reverse("inventory:reference_category_add"), {"name": "Electronics"})
        keys = set(ReferenceCategory.objects.values_list("key", flat=True))
        self.assertEqual(len(keys), ReferenceCategory.objects.count())

    def test_a_category_can_be_renamed(self):
        self.client.post(reverse("inventory:reference_category_edit", args=[self.category.pk]), {"name": "Electronics & PCBs"})
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, "Electronics & PCBs")

    def test_renaming_does_not_change_the_key(self):
        """The key is what links point at, so renaming must not break saved URLs."""
        self.client.post(reverse("inventory:reference_category_edit", args=[self.category.pk]), {"name": "Something Else"})
        self.category.refresh_from_db()
        self.assertEqual(self.category.key, "test-shelf", "the key must survive a rename")

    def test_the_order_can_be_changed(self):
        self.client.post(reverse("inventory:reference_category_edit", args=[self.category.pk]), {"name": "Electronics", "order": "5"})
        self.category.refresh_from_db()
        self.assertEqual(self.category.order, 5)

    def test_an_empty_category_can_be_deleted(self):
        self.client.post(reverse("inventory:reference_category_delete", args=[self.category.pk]))
        self.assertFalse(ReferenceCategory.objects.filter(pk=self.category.pk).exists())

    def test_a_category_with_documents_cannot_be_deleted(self):
        """Deleting a shelf must not silently shred what is on it."""
        ReferenceDoc.objects.create(title="Chart", category=self.category)
        self.client.post(reverse("inventory:reference_category_delete", args=[self.category.pk]))
        self.assertTrue(ReferenceCategory.objects.filter(pk=self.category.pk).exists())
        self.assertEqual(ReferenceDoc.objects.count(), 1)

    def test_an_empty_name_is_rejected(self):
        before = ReferenceCategory.objects.count()
        self.client.post(reverse("inventory:reference_category_add"), {"name": "   "})
        self.assertEqual(ReferenceCategory.objects.count(), before)


class DocumentEditingTests(ReferenceViewTestCase):
    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_a_document_can_be_added(self):
        self.client.post(
            reverse("inventory:reference_add"),
            {"title": "Resistor chart", "category": self.category.pk, "description": "Colour bands", "order": "10"},
        )
        doc = ReferenceDoc.objects.get(title="Resistor chart")
        self.assertEqual(doc.category, self.category)
        self.assertEqual(doc.description, "Colour bands")

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_a_document_needs_a_title(self):
        self.client.post(reverse("inventory:reference_add"), {"title": "  ", "category": self.category.pk})
        self.assertFalse(ReferenceDoc.objects.exists())

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_a_document_needs_a_category(self):
        """Otherwise it would be filed invisibly — every list groups by category."""
        self.client.post(reverse("inventory:reference_add"), {"title": "Orphan"})
        self.assertFalse(ReferenceDoc.objects.exists())

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_a_document_can_be_edited(self):
        doc = ReferenceDoc.objects.create(title="Old", category=self.category)
        self.client.post(
            reverse("inventory:reference_edit", args=[doc.pk]),
            {"title": "New", "category": self.category.pk, "description": "updated"},
        )
        doc.refresh_from_db()
        self.assertEqual(doc.title, "New")
        self.assertEqual(doc.description, "updated")

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_a_document_can_be_deleted(self):
        doc = ReferenceDoc.objects.create(title="Chart", category=self.category)
        self.client.post(reverse("inventory:reference_delete", args=[doc.pk]))
        self.assertFalse(ReferenceDoc.objects.filter(pk=doc.pk).exists())

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_deleting_needs_a_post(self):
        """A GET must not be able to delete something — links get prefetched by
        browsers and scanners, and this one is destructive."""
        doc = ReferenceDoc.objects.create(title="Chart", category=self.category)
        self.client.get(reverse("inventory:reference_delete", args=[doc.pk]))
        self.assertTrue(ReferenceDoc.objects.filter(pk=doc.pk).exists())

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_the_whole_starter_set_can_be_emptied(self):
        """It is a starting point, not a fixture. Someone who wants a blank library
        must be able to have one."""
        docs = [ReferenceDoc.objects.create(title=f"Doc {i}", category=self.category) for i in range(3)]
        for doc in docs:
            self.client.post(reverse("inventory:reference_delete", args=[doc.pk]))
        self.assertEqual(ReferenceDoc.objects.count(), 0)


class OrderingTests(ReferenceViewTestCase):
    def make(self, title, order):
        return ReferenceDoc.objects.create(title=title, category=self.category, order=order)

    def order(self):
        return list(ReferenceDoc.objects.filter(category=self.category).values_list("title", flat=True))

    def test_moving_down_swaps_with_the_next_document(self):
        self.make("A", 10)
        b = self.make("B", 20)
        self.client.post(reverse("inventory:reference_move", args=[b.pk]), {"direction": "up"})
        self.assertEqual(self.order(), ["B", "A"])

    def test_moving_up_swaps_with_the_previous_document(self):
        a = self.make("A", 10)
        self.make("B", 20)
        self.client.post(reverse("inventory:reference_move", args=[a.pk]), {"direction": "down"})
        self.assertEqual(self.order(), ["B", "A"])

    def test_moving_the_first_item_up_does_nothing(self):
        a = self.make("A", 10)
        self.make("B", 20)
        self.client.post(reverse("inventory:reference_move", args=[a.pk]), {"direction": "up"})
        self.assertEqual(self.order(), ["A", "B"])

    def test_moving_the_last_item_down_does_nothing(self):
        self.make("A", 10)
        b = self.make("B", 20)
        self.client.post(reverse("inventory:reference_move", args=[b.pk]), {"direction": "down"})
        self.assertEqual(self.order(), ["A", "B"])

    def test_equal_order_values_still_move(self):
        """The starter set ships with everything at order 100, so a swap that relies
        on the values differing would appear to do nothing at all."""
        a = self.make("A", 100)
        self.make("B", 100)
        self.client.post(reverse("inventory:reference_move", args=[a.pk]), {"direction": "down"})
        self.assertEqual(self.order(), ["B", "A"])


class ListGroupingTests(ReferenceViewTestCase):
    def test_documents_are_grouped_under_their_own_category(self):
        other = ReferenceCategory.objects.create(name="Woodwork", key="woodwork", order=20)
        ReferenceDoc.objects.create(title="Resistor chart", category=self.category)
        ReferenceDoc.objects.create(title="Saw blades", category=other)

        response = self.client.get(reverse("inventory:reference_list"))
        self.assertContains(response, "Test shelf")
        self.assertContains(response, "Woodwork")
        self.assertContains(response, "Resistor chart")
        self.assertContains(response, "Saw blades")

    def test_an_empty_category_is_hidden_while_browsing(self):
        ReferenceCategory.objects.create(name="Empty shelf", key="empty", order=30)
        response = self.client.get(reverse("inventory:reference_list"))
        # It appears in the filter dropdown on purpose — only the *section* is skipped.
        self.assertNotContains(response, "<h2>Empty shelf</h2>", html=False)

    def test_an_empty_category_is_shown_when_asked_for(self):
        """So an owner who just created a shelf can see it and add to it."""
        ReferenceCategory.objects.create(name="Empty shelf", key="empty", order=30)
        response = self.client.get(reverse("inventory:reference_list"), {"category": "empty"})
        self.assertContains(response, "<h2>Empty shelf</h2>", html=False)

    def test_an_unknown_category_filter_shows_nothing_rather_than_everything(self):
        ReferenceDoc.objects.create(title="Resistor chart", category=self.category)
        response = self.client.get(reverse("inventory:reference_list"), {"category": "nope"})
        self.assertNotContains(response, "Resistor chart")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ArchiveIntegrationTests(ReferenceViewTestCase):
    def fake_pdf(self):
        class R:
            status_code = 200
            headers = {"Content-Type": "application/pdf"}
            url = "https://example.test/ds.pdf"

            def iter_content(self, chunk_size=1):
                yield b"%PDF-1.4"

            def close(self):
                pass

        return R()

    def test_adding_a_linked_document_archives_it_automatically(self):
        """The point of the feature: you paste a link and end up owning the file,
        because the link will not last."""
        patcher = mock.patch("requests.get", return_value=self.fake_pdf())
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client.post(
            reverse("inventory:reference_add"),
            {"title": "DS18B20 datasheet", "category": self.category.pk, "external_url": "https://example.test/ds.pdf"},
        )
        doc = ReferenceDoc.objects.get(title="DS18B20 datasheet")
        self.assertTrue(doc.file)
        self.assertTrue(doc.is_archived)
        self.assertEqual(doc.archive_content_type, "application/pdf")

    def test_a_failed_automatic_archive_still_saves_the_document(self):
        """A dead link must not stop someone filing the reference — it just has to be
        visible that the copy didn't happen."""
        class R:
            status_code = 403
            headers = {}
            url = "https://example.test/ds.pdf"

            def iter_content(self, chunk_size=1):
                yield b""

            def close(self):
                pass

        patcher = mock.patch("requests.get", return_value=R())
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client.post(
            reverse("inventory:reference_add"),
            {"title": "Locked datasheet", "category": self.category.pk, "external_url": "https://example.test/ds.pdf"},
        )
        doc = ReferenceDoc.objects.get(title="Locked datasheet")
        self.assertEqual(doc.external_url, "https://example.test/ds.pdf")
        self.assertFalse(doc.file)
        self.assertIn("403", doc.archive_error)
        self.assertTrue(doc.archive_failed)

    def test_archiving_can_be_retried_from_the_manage_page(self):
        doc = ReferenceDoc.objects.create(
            title="Retry me", category=self.category, external_url="https://example.test/ds.pdf"
        )
        doc.archive_error = "The source returned HTTP 500."
        doc.save()

        patcher = mock.patch("requests.get", return_value=self.fake_pdf())
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client.post(reverse("inventory:reference_archive", args=[doc.pk]))
        doc.refresh_from_db()
        self.assertTrue(doc.file)
        self.assertEqual(doc.archive_error, "")

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_archiving_can_be_switched_off(self):
        patcher = mock.patch("requests.get")
        fake = patcher.start()
        self.addCleanup(patcher.stop)

        self.client.post(
            reverse("inventory:reference_add"),
            {"title": "Link only", "category": self.category.pk, "external_url": "https://example.test/ds.pdf"},
        )
        self.assertFalse(ReferenceDoc.objects.get(title="Link only").file)
        fake.assert_not_called()

    def test_the_retry_redirect_cannot_be_pointed_at_another_site(self):
        """`?next=` is attacker-controlled, and an unvalidated redirect would let a
        link to this app bounce someone elsewhere carrying its apparent authority."""
        doc = ReferenceDoc.objects.create(
            title="Retry me", category=self.category, external_url="https://example.test/ds.pdf"
        )
        patcher = mock.patch("requests.get", return_value=self.fake_pdf())
        patcher.start()
        self.addCleanup(patcher.stop)

        response = self.client.post(
            reverse("inventory:reference_archive", args=[doc.pk]), {"next": "https://evil.test/steal"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.test", response["Location"])

    def test_a_same_site_redirect_is_honoured(self):
        doc = ReferenceDoc.objects.create(
            title="Retry me", category=self.category, external_url="https://example.test/ds.pdf"
        )
        patcher = mock.patch("requests.get", return_value=self.fake_pdf())
        patcher.start()
        self.addCleanup(patcher.stop)

        response = self.client.post(
            reverse("inventory:reference_archive", args=[doc.pk]), {"next": "/reference/"}
        )
        self.assertEqual(response["Location"], "/reference/")


class ShippedCategoryTests(TestCase):
    """Migration 0018 seeds the four shelves the hardcoded choices used to provide.

    Worth pinning because it is easy to lose: if those rows stopped being created, a
    fresh install would open the reference section to no categories at all, and there
    would be nowhere to file a document until the owner made one by hand.
    """

    def test_a_fresh_database_already_has_shelves(self):
        self.assertEqual(ReferenceCategory.objects.count(), 4)

    def test_the_original_four_are_present_under_their_old_keys(self):
        keys = set(ReferenceCategory.objects.values_list("key", flat=True))
        self.assertEqual(keys, {"raspberry_pi", "arduino", "electronics", "3d_printing"})

    def test_they_keep_their_original_names_and_order(self):
        names = [c.name for c in ReferenceCategory.objects.all()]
        self.assertEqual(names, ["Raspberry Pi", "Arduino", "Electronics reference", "3D printing"])

    def test_they_start_empty(self):
        """Shelves yes, documents no — the starter documents are a separate, explicit
        choice the owner makes."""
        self.assertEqual(ReferenceDoc.objects.count(), 0)


class StarterFileTests(TestCase):
    """The shipped starter set is data, so it can rot like data."""

    def setUp(self):
        self.data = json.loads(
            (Path(__file__).resolve().parent.parent / "data" / "starter_reference.json").read_text(encoding="utf-8")
        )

    def test_the_file_is_present_and_well_formed(self):
        self.assertIn("categories", self.data)
        self.assertIn("documents", self.data)

    def test_every_category_has_the_fields_the_loader_needs(self):
        for entry in self.data["categories"]:
            with self.subTest(key=entry.get("key")):
                self.assertTrue(entry["key"])
                self.assertTrue(entry["name"])

    def test_category_keys_are_unique(self):
        keys = [c["key"] for c in self.data["categories"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_document_points_at_a_category_that_exists(self):
        """The loader raises on this, so a typo here would break a fresh install."""
        known = {c["key"] for c in self.data["categories"]}
        for entry in self.data["documents"]:
            with self.subTest(title=entry.get("title")):
                self.assertIn(entry["category"], known)

    def test_no_starter_document_ships_a_file(self):
        """The repository ships links only, so it never redistributes anyone's PDF;
        each install fetches its own copies of what it chooses to keep."""
        for entry in self.data["documents"]:
            with self.subTest(title=entry.get("title")):
                self.assertNotIn("file", entry)

    def test_every_document_has_a_title_and_an_http_link(self):
        for entry in self.data["documents"]:
            with self.subTest(title=entry.get("title")):
                self.assertTrue(entry["title"])
                self.assertTrue(entry["external_url"].startswith("http"))


class StarterLoaderTests(TestCase):
    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_the_starter_set_loads(self):
        from django.core.management import call_command

        call_command("load_starter_reference", verbosity=0)
        self.assertGreater(ReferenceCategory.objects.count(), 0)
        self.assertGreater(ReferenceDoc.objects.count(), 0)

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_loading_twice_does_not_duplicate(self):
        from django.core.management import call_command

        call_command("load_starter_reference", verbosity=0)
        docs = ReferenceDoc.objects.count()
        call_command("load_starter_reference", verbosity=0)
        self.assertEqual(ReferenceDoc.objects.count(), docs)

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_loading_does_not_resurrect_a_deleted_document(self):
        """Deleting something must mean deleted — a command that quietly puts it back
        would make the library impossible to prune."""
        from django.core.management import call_command

        call_command("load_starter_reference", verbosity=0)
        victim = ReferenceDoc.objects.first()
        title = victim.title
        victim.delete()

        call_command("load_starter_reference", verbosity=0)
        self.assertFalse(ReferenceDoc.objects.filter(title=title).exists())

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_force_re_adds_what_is_missing(self):
        """The escape hatch, for someone who cleared the library and changed their
        mind. It also re-adds anything they deleted, which is why it is not the
        default."""
        from django.core.management import call_command

        call_command("load_starter_reference", verbosity=0)
        victim = ReferenceDoc.objects.first()
        title = victim.title
        victim.delete()

        call_command("load_starter_reference", "--force", verbosity=0)
        self.assertTrue(ReferenceDoc.objects.filter(title=title).exists())

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_the_load_is_recorded_so_the_guard_has_something_to_check(self):
        from django.core.management import call_command

        from inventory.models import SiteSettings

        self.assertIsNone(SiteSettings.load().starter_reference_loaded_at)
        call_command("load_starter_reference", verbosity=0)
        self.assertIsNotNone(SiteSettings.load().starter_reference_loaded_at)

    @override_settings(ARCHIVE_ON_SAVE=False)
    def test_a_dry_run_does_not_record_the_load(self):
        """Otherwise checking what would happen would stop it ever happening."""
        from django.core.management import call_command

        from inventory.models import SiteSettings

        call_command("load_starter_reference", "--dry-run", verbosity=0)
        self.assertIsNone(SiteSettings.load().starter_reference_loaded_at)
        self.assertEqual(ReferenceDoc.objects.count(), 0)
