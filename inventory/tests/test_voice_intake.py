from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import IntakeNote
from .factories import make_container


@override_settings(VOICE_SEARCH_API_KEY="secret")
class VoiceIntakeApiTests(TestCase):
    def test_no_key_is_unauthorized(self):
        resp = self.client.post(reverse("inventory:api_add_intake_note"), {"text": "M3 bolts"})
        self.assertEqual(resp.status_code, 403)

    def test_wrong_key_is_unauthorized(self):
        resp = self.client.post(
            reverse("inventory:api_add_intake_note"), {"text": "M3 bolts", "key": "wrong"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_correct_key_creates_note(self):
        resp = self.client.post(
            reverse("inventory:api_add_intake_note"), {"text": "M3 bolts", "key": "secret"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        note = IntakeNote.objects.get()
        self.assertEqual(note.text, "M3 bolts")
        self.assertEqual(note.source, IntakeNote.VOICE)

    def test_correct_key_with_container(self):
        container = make_container(number=5)
        resp = self.client.post(
            reverse("inventory:api_add_intake_note"),
            {"text": "M3 bolts", "key": "secret", "container": "5"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(IntakeNote.objects.get().container, container)

    def test_missing_text_is_400(self):
        resp = self.client.post(reverse("inventory:api_add_intake_note"), {"key": "secret"})
        self.assertEqual(resp.status_code, 400)

    def test_get_also_works(self):
        resp = self.client.get(reverse("inventory:api_add_intake_note"), {"text": "LEDs", "key": "secret"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(IntakeNote.objects.get().text, "LEDs")

    def test_unknown_container_is_404(self):
        resp = self.client.post(
            reverse("inventory:api_add_intake_note"), {"text": "LEDs", "key": "secret", "container": "99"}
        )
        self.assertEqual(resp.status_code, 404)
