"""Project creation from the Projects page.

Projects used to be creatable only through /admin/, which sent an owner on an
unnecessary detour. The Projects page now has its own create form; these tests
pin the three ways it can go — created, blank name, and the status default.
"""
from django.test import TestCase
from django.urls import reverse

from inventory.models import Project

from .factories import make_user


class ProjectCreateTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_list_page_shows_the_create_form(self):
        resp = self.client.get(reverse("inventory:project_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "New project")

    def test_create_redirects_to_the_new_project(self):
        resp = self.client.post(
            reverse("inventory:create_project"),
            {"name": "Blinky", "description": "A blinking LED thing", "status": "active"},
        )
        project = Project.objects.get(name="Blinky")
        self.assertRedirects(resp, reverse("inventory:project_detail", args=[project.pk]))
        self.assertEqual(project.description, "A blinking LED thing")
        self.assertEqual(project.status, Project.ACTIVE)

    def test_blank_name_creates_nothing(self):
        resp = self.client.post(reverse("inventory:create_project"), {"name": "   "})
        self.assertEqual(Project.objects.count(), 0)
        self.assertRedirects(resp, reverse("inventory:project_list"))

    def test_status_defaults_to_active(self):
        self.client.post(reverse("inventory:create_project"), {"name": "Defaultish"})
        self.assertEqual(Project.objects.get(name="Defaultish").status, Project.ACTIVE)

    def test_an_unrecognised_status_falls_back_to_active(self):
        self.client.post(reverse("inventory:create_project"), {"name": "Weird", "status": "bogus"})
        self.assertEqual(Project.objects.get(name="Weird").status, Project.ACTIVE)
