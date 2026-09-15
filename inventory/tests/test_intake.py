"""Moving-day intake -- bulk notes, the review queue, and assignment.

IntakeNote deliberately stays unstructured free text (never auto-parsed into
Parts), so the value here is capturing a batch quickly and being able to sort
out where things live later.
"""
from django.test import TestCase
from django.urls import reverse

from inventory.models import Bin, Container, IntakeNote

from .factories import make_bin, make_container, make_drawer, make_user


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


class BulkIntakeLocationTests(TestCase):
    """The location field accepts a bin, a drawer, or a box/tote — one leaf per note."""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.container = make_container(number=1)
        cls.drawer = make_drawer(cls.container, label="drawer 1")
        cls.bin = make_bin(cls.drawer, bin_number=3)

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("inventory:bulk_intake")

    def test_note_can_be_assigned_to_a_drawer(self):
        self.client.post(self.url, {"text": "Thing", "location_drawer": self.drawer.pk})
        note = IntakeNote.objects.get()
        self.assertEqual(note.drawer, self.drawer)
        self.assertIsNone(note.bin)
        self.assertIsNone(note.container)

    def test_note_can_be_assigned_to_a_bin(self):
        self.client.post(self.url, {"text": "Thing", "location_bin": self.bin.pk})
        note = IntakeNote.objects.get()
        self.assertEqual(note.bin, self.bin)

    def test_bin_takes_precedence_over_drawer_and_container(self):
        self.client.post(
            self.url,
            {"text": "Thing", "location_bin": self.bin.pk, "location_drawer": self.drawer.pk, "container": self.container.pk},
        )
        note = IntakeNote.objects.get()
        self.assertEqual(note.bin, self.bin)
        self.assertIsNone(note.drawer)
        self.assertIsNone(note.container)

    def test_drawer_takes_precedence_over_container(self):
        self.client.post(self.url, {"text": "Thing", "location_drawer": self.drawer.pk, "container": self.container.pk})
        note = IntakeNote.objects.get()
        self.assertEqual(note.drawer, self.drawer)
        self.assertIsNone(note.container)

    def test_location_summary_reports_the_leaf(self):
        IntakeNote.objects.create(text="A", container=self.container)
        IntakeNote.objects.create(text="B", drawer=self.drawer)
        IntakeNote.objects.create(text="C", bin=self.bin)
        summaries = {n.text: n.location_summary() for n in IntakeNote.objects.all()}
        self.assertEqual(summaries["A"], str(self.container))
        self.assertEqual(summaries["B"], str(self.drawer))
        self.assertEqual(summaries["C"], str(self.bin))

    def test_unassigned_location_summary(self):
        note = IntakeNote.objects.create(text="Loose")
        self.assertEqual(note.location_summary(), "unassigned")


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

    def test_quick_add_captures_contents_as_notes_on_the_new_container(self):
        self.client.post(
            reverse("inventory:quick_add_container"), {"container_type": "black tote", "text": "One\nTwo\n\nThree"}
        )
        container = Container.objects.get(number=1)
        self.assertEqual(sorted(container.intake_notes.values_list("text", flat=True)), ["One", "Three", "Two"])

    def test_quick_add_accepts_dictated_contents(self):
        self.client.post(reverse("inventory:quick_add_container"), {"text": "Spoken", "source": IntakeNote.VOICE})
        self.assertEqual(IntakeNote.objects.get().source, IntakeNote.VOICE)


class AddIntakeLocationTests(TestCase):
    """Creating a location on the spot — cabinet, tote, or bin, each barcoded."""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user()
        cls.drawer = make_drawer(make_container(number=1), label="drawer 1")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("inventory:add_intake_location")

    def test_cabinet_is_created_and_printed(self):
        resp = self.client.post(self.url, {"has_bins": "on"})
        cabinet = Container.objects.order_by("-number").first()
        self.assertEqual(cabinet.container_type, "cabinets")
        self.assertEqual(cabinet.barcode_id, f"C{cabinet.number}")
        self.assertRedirects(resp, reverse("inventory:print_labels") + f"?ids=c{cabinet.pk}")

    def test_tote_is_created_and_printed(self):
        resp = self.client.post(self.url, {"kind": "tote", "tote_type": "blue tote"})
        tote = Container.objects.get(container_type="blue tote")
        self.assertEqual(tote.barcode_id, f"C{tote.number}")
        self.assertRedirects(resp, reverse("inventory:print_labels") + f"?ids=c{tote.pk}")

    def test_bin_generate_creates_and_prints(self):
        resp = self.client.post(
            self.url, {"kind": "bin", "drawer": self.drawer.pk, "bin_number": 5, "barcode_action": "generate"}
        )
        bin_obj = Bin.objects.get(drawer=self.drawer, bin_number=5)
        self.assertTrue(bin_obj.barcode_id)
        self.assertRedirects(resp, reverse("inventory:print_labels") + f"?ids=b{bin_obj.pk}")

    def test_bin_scan_links_an_existing_code(self):
        resp = self.client.post(
            self.url, {"kind": "bin", "drawer": self.drawer.pk, "bin_number": 2, "barcode_action": "scan", "code": "PHYS123"}
        )
        bin_obj = Bin.objects.get(drawer=self.drawer, bin_number=2)
        self.assertEqual(bin_obj.barcode_id, "PHYS123")
        self.assertRedirects(resp, reverse("inventory:bulk_intake"))

    def test_bin_number_is_clamped_to_the_16_bin_grid(self):
        self.client.post(
            self.url, {"kind": "bin", "drawer": self.drawer.pk, "bin_number": 99, "barcode_action": "generate"}
        )
        self.assertTrue(Bin.objects.filter(drawer=self.drawer, bin_number=16).exists())
        self.assertFalse(Bin.objects.filter(drawer=self.drawer, bin_number=99).exists())

    def test_scan_conflict_is_rejected(self):
        Bin.objects.create(drawer=self.drawer, bin_number=1, barcode_id="TAKEN")
        self.client.post(
            self.url, {"kind": "bin", "drawer": self.drawer.pk, "bin_number": 3, "barcode_action": "scan", "code": "TAKEN"}
        )
        self.assertIsNone(Bin.objects.get(drawer=self.drawer, bin_number=3).barcode_id)
