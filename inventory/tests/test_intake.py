"""Moving-day intake -- bulk notes, the review queue, and assignment.

IntakeNote deliberately stays unstructured free text (never auto-parsed into
Parts), so the value here is capturing a batch quickly and being able to sort
out where things live later.
"""
from django.test import TestCase
from django.urls import reverse

from inventory.models import Container, IntakeNote

from .factories import make_container, make_user


class BulkIntakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.container = make_container(number=1)

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("inventory:bulk_intake")

    def test_each_line_becomes_its_own_note(self):
        self.client.post(self.url, {"text": "Resistor 10k\nCapacitor 100uF\nLED red"})
        self.assertEqual(IntakeNote.objects.count(), 3)
        self.assertEqual(
            sorted(IntakeNote.objects.values_list("text", flat=True)),
            ["Capacitor 100uF", "LED red", "Resistor 10k"],
        )

    def test_blank_lines_are_dropped(self):
        self.client.post(self.url, {"text": "One\n\n\n   \nTwo\n"})
        self.assertEqual(IntakeNote.objects.count(), 2)

    def test_lines_are_trimmed(self):
        self.client.post(self.url, {"text": "   padded   "})
        self.assertEqual(IntakeNote.objects.get().text, "padded")

    def test_notes_can_be_created_unassigned(self):
        """'Add now, assign a space later' is the whole point of the bulk flow."""
        self.client.post(self.url, {"text": "Mystery box contents"})
        self.assertIsNone(IntakeNote.objects.get().container)

    def test_notes_can_be_assigned_to_a_container_up_front(self):
        self.client.post(self.url, {"text": "Screws", "container": self.container.pk})
        self.assertEqual(IntakeNote.objects.get().container, self.container)

    def test_a_successful_bulk_add_redirects_to_the_queue(self):
        resp = self.client.post(self.url, {"text": "One"})
        self.assertRedirects(resp, reverse("inventory:intake_queue"))

    def test_empty_submission_creates_nothing_and_stays_on_the_page(self):
        resp = self.client.post(self.url, {"text": ""})
        self.assertEqual(IntakeNote.objects.count(), 0)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No items received")

    def test_whitespace_only_submission_creates_nothing(self):
        self.client.post(self.url, {"text": "  \n \n  "})
        self.assertEqual(IntakeNote.objects.count(), 0)

    def test_source_defaults_to_typed(self):
        self.client.post(self.url, {"text": "One"})
        self.assertEqual(IntakeNote.objects.get().source, IntakeNote.TYPED)

    def test_voice_source_is_accepted(self):
        self.client.post(self.url, {"text": "One", "source": IntakeNote.VOICE})
        self.assertEqual(IntakeNote.objects.get().source, IntakeNote.VOICE)

    def test_an_invalid_source_falls_back_to_typed(self):
        """The field has choices, so a crafted POST must not store a bad value."""
        self.client.post(self.url, {"text": "One", "source": "telepathy"})
        self.assertEqual(IntakeNote.objects.get().source, IntakeNote.TYPED)

    def test_notes_start_unreviewed(self):
        self.client.post(self.url, {"text": "One"})
        self.assertFalse(IntakeNote.objects.get().reviewed)


class IntakeQueueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.container = make_container(number=1)

    def setUp(self):
        self.client.force_login(self.user)

    def test_queue_lists_only_unreviewed_notes(self):
        pending = IntakeNote.objects.create(text="Pending")
        IntakeNote.objects.create(text="Already done", reviewed=True)

        resp = self.client.get(reverse("inventory:intake_queue"))
        self.assertEqual(list(resp.context["notes"]), [pending])

    def test_queue_includes_unassigned_notes(self):
        loose = IntakeNote.objects.create(text="Nowhere yet")
        resp = self.client.get(reverse("inventory:intake_queue"))
        self.assertIn(loose, resp.context["notes"])

    def test_a_note_can_be_assigned_from_the_queue(self):
        note = IntakeNote.objects.create(text="Thing")
        self.client.post(reverse("inventory:assign_intake_note_container", args=[note.pk]), {"container": self.container.pk})
        note.refresh_from_db()
        self.assertEqual(note.container, self.container)

    def test_a_note_can_be_reassigned(self):
        other = make_container(number=2)
        note = IntakeNote.objects.create(text="Thing", container=self.container)
        self.client.post(reverse("inventory:assign_intake_note_container", args=[note.pk]), {"container": other.pk})
        note.refresh_from_db()
        self.assertEqual(note.container, other)

    def test_an_assignment_can_be_cleared(self):
        note = IntakeNote.objects.create(text="Thing", container=self.container)
        self.client.post(reverse("inventory:assign_intake_note_container", args=[note.pk]), {"container": ""})
        note.refresh_from_db()
        self.assertIsNone(note.container)

    def test_marking_reviewed_removes_it_from_the_queue(self):
        note = IntakeNote.objects.create(text="Thing")
        self.client.post(reverse("inventory:mark_intake_note_reviewed", args=[note.pk]))

        note.refresh_from_db()
        self.assertTrue(note.reviewed)
        resp = self.client.get(reverse("inventory:intake_queue"))
        self.assertEqual(list(resp.context["notes"]), [])

    def test_notes_are_not_deleted_when_marked_reviewed(self):
        """Review is a state change, not a delete -- the capture is still the
        record of what was in the box."""
        note = IntakeNote.objects.create(text="Thing")
        self.client.post(reverse("inventory:mark_intake_note_reviewed", args=[note.pk]))
        self.assertTrue(IntakeNote.objects.filter(pk=note.pk).exists())

    def test_assigning_a_note_does_not_parse_it_into_parts(self):
        """Explicit non-goal: intake notes stay unstructured until Seth works
        them. If someone later adds auto-parsing, this should fail loudly."""
        from inventory.models import Part

        note = IntakeNote.objects.create(text="Resistor 10k x50")
        self.client.post(reverse("inventory:assign_intake_note_container", args=[note.pk]), {"container": self.container.pk})
        self.assertEqual(Part.objects.count(), 0)


class IntakeNoteContainerDeletionTests(TestCase):
    def test_deleting_a_container_removes_its_notes(self):
        """container is a required-FK-with-null semantics on an on_delete=CASCADE
        field: notes belong to the box they were captured against."""
        container = make_container(number=1)
        IntakeNote.objects.create(text="Thing", container=container)
        container.delete()
        self.assertEqual(IntakeNote.objects.count(), 0)

    def test_unassigned_notes_survive_a_container_deletion(self):
        container = make_container(number=1)
        loose = IntakeNote.objects.create(text="No home")
        IntakeNote.objects.create(text="Homed", container=container)
        container.delete()
        self.assertEqual(list(IntakeNote.objects.all()), [loose])


class QuickAddContainerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()

    def setUp(self):
        self.client.force_login(self.user)

    def test_quick_add_assigns_the_next_free_number(self):
        make_container(number=1)
        make_container(number=2)
        self.client.post(reverse("inventory:quick_add_container"), {"container_type": "black tote"})
        self.assertTrue(Container.objects.filter(number=3).exists())

    def test_quick_add_does_not_reuse_a_gap(self):
        """Numbers must stay monotonic -- reusing #2 after deleting it would
        collide with a label already stuck on a physical box."""
        make_container(number=1)
        make_container(number=5)
        self.client.post(reverse("inventory:quick_add_container"), {"container_type": "black tote"})
        self.assertTrue(Container.objects.filter(number=6).exists())

    def test_quick_add_defaults_the_type_to_black_tote(self):
        self.client.post(reverse("inventory:quick_add_container"), {})
        self.assertEqual(Container.objects.get(number=1).container_type, "black tote")

    def test_quick_add_accepts_a_free_text_type(self):
        self.client.post(reverse("inventory:quick_add_container"), {"container_type": "garage shelf"})
        self.assertEqual(Container.objects.get(number=1).container_type, "garage shelf")
