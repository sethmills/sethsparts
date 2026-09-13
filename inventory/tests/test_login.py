"""The app's own login page.

Why this file exists: the app had no login page of its own. `LOGIN_URL` was
`/admin/login/`, so the first thing a visitor to someone else's installation saw was a
page branded "Django administration", and `/login/` -- the address a person actually
types -- was a 404. That is the wrong front door for a project other people are meant
to clone and run.

What the tests below protect:

* the login page belongs to this app and lives where people guess it does;
* the safe-`next` handling and POST-only logout come from Django's own views, not
  from something rewritten here -- an open redirect on a login page is a phishing
  primitive, and a GET logout can be fired by any image tag on any page;
* the admin keeps its own login at `/admin/login/`, untouched;
* and on an install with no account yet, the app's login is deliberately NOT exempt
  from the onboarding redirect, because the wizard is where that account gets made.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ..middleware import SetupRedirectMiddleware
from ..models import SiteSettings

LOGIN_PATH = "/login/"
PASSWORD = "correct-horse-battery-staple"


def make_user(username="owner"):
    return get_user_model().objects.create_user(username=username, password=PASSWORD)


class LoginPageTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_the_login_page_is_the_apps_own_not_the_admins(self):
        response = self.client.get(reverse("inventory:login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "inventory/login.html")
        self.assertContains(response, "Sign in to your workshop inventory")
        # The specific thing that used to greet visitors.
        self.assertNotContains(response, "Django administration")

    def test_the_login_page_is_reachable_where_people_look_for_it(self):
        """/login/ was a 404 while the root URL bounced to the admin's login."""
        self.assertEqual(reverse("inventory:login"), LOGIN_PATH)
        self.assertEqual(self.client.get(LOGIN_PATH).status_code, 200)

    def test_the_login_wall_sends_people_to_the_apps_own_login(self):
        self.client.logout()
        response = self.client.get(reverse("inventory:browse"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(LOGIN_PATH), response["Location"])

    def test_the_login_page_shows_the_owners_name_not_the_hostname(self):
        """Django's LoginView supplies `site_name` itself, from `get_current_site()`.
        Without django.contrib.sites that is a RequestSite, whose name is the bare
        host -- so an owner who called their install "Seth's Parts" was greeted by
        "testserver" (or their domain) instead of their own name."""
        SiteSettings.objects.create(site_name="Seth's Parts")
        response = self.client.get(LOGIN_PATH)
        self.assertContains(response, "Seth's Parts", html=True)
        self.assertNotContains(response, "testserver")

    def test_a_deep_link_survives_the_login_page(self):
        """Someone following a bookmarked page while signed out should end up on that
        page, not the front page."""
        target = reverse("inventory:help_index")
        response = self.client.get(f"{LOGIN_PATH}?next={target}")
        self.assertContains(response, f'value="{target}"')

    def test_signing_in_works(self):
        self.client.logout()
        response = self.client.post(LOGIN_PATH, {"username": "owner", "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("inventory:browse")).status_code, 200)

    def test_a_wrong_password_does_not_sign_anyone_in(self):
        self.client.logout()
        response = self.client.post(LOGIN_PATH, {"username": "owner", "password": "not-it"})
        self.assertEqual(response.status_code, 200, "a failed login re-renders the form")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_a_wrong_password_says_so_on_the_page(self):
        """Django's own wording is rendered rather than a message written by hand, so
        this asserts that an error is shown, not what it says."""
        self.client.logout()
        response = self.client.post(LOGIN_PATH, {"username": "owner", "password": "not-it"})
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertContains(response, 'class="msg-error"')

    def test_next_is_honoured(self):
        self.client.logout()
        target = reverse("inventory:help_index")
        response = self.client.post(
            f"{LOGIN_PATH}?next={target}", {"username": "owner", "password": PASSWORD}
        )
        self.assertRedirects(response, target)

    def test_next_cannot_send_someone_to_another_site(self):
        """Django's `url_has_allowed_host_and_scheme` does this. The test is here so a
        future rewrite to a hand-rolled view cannot quietly lose it -- an open
        redirect on a login page is how phishing links look trustworthy."""
        self.client.logout()
        response = self.client.post(
            f"{LOGIN_PATH}?next=https://evil.example.com/steal",
            {"username": "owner", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_an_already_signed_in_visitor_is_not_asked_again(self):
        """The Pi kiosk after a reboot follows a stale /login/ link. It must land in
        the app rather than on a form nobody is standing there to fill in."""
        self.client.force_login(self.user)
        response = self.client.get(LOGIN_PATH)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")


class LogoutTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_logging_out_works_and_lands_on_the_login_page(self):
        response = self.client.post(reverse("inventory:logout"))
        self.assertRedirects(response, LOGIN_PATH)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(self.client.get(reverse("inventory:browse"))["Location"].startswith(LOGIN_PATH))

    def test_logout_is_post_only(self):
        """Django's rule, kept on purpose: a GET logout can be triggered by an image
        tag or a link prefetch on any page, which is a silly way to lose a session."""
        self.assertEqual(self.client.get(reverse("inventory:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session, "a GET must not sign anyone out")

    def test_the_navigation_offers_a_way_out(self):
        """Before this there was no logout anywhere in the app at all -- it meant
        going to the admin and finding it there."""
        response = self.client.get(reverse("inventory:browse"))
        self.assertContains(response, reverse("inventory:logout"))
        self.assertContains(response, "Log out")


class AdminLoginTests(TestCase):
    """The admin keeps its own entrance. Nothing here changed it; these tests exist so
    that a future tidy-up of the app's login cannot quietly take the admin's away."""

    def test_the_admin_login_still_renders(self):
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)

    def test_the_admin_login_is_still_the_admins(self):
        """The admin's own template and styling, untouched. Note the header here says
        the site's name rather than "Django administration" -- the app renames that
        from its own settings -- so this asserts the template, not the wording."""
        response = self.client.get("/admin/login/")
        self.assertTemplateUsed(response, "admin/login.html")
        self.assertContains(response, "/static/admin/css/login.css")


class VirginInstallTests(TestCase):
    def test_the_apps_login_is_not_exempt_from_the_wizard_but_the_admins_is(self):
        """The deliberate difference between the two. On a fresh clone there is no
        account to log in with, so /login/ points at the wizard -- which is where the
        account gets created. The admin's login stays reachable for the admin itself.
        """
        self.assertFalse(SetupRedirectMiddleware._is_exempt(LOGIN_PATH))
        self.assertTrue(SetupRedirectMiddleware._is_exempt("/admin/login/"))

    def test_a_fresh_clone_sends_the_visitor_to_the_wizard(self):
        self.assertEqual(get_user_model().objects.count(), 0)
        response = self.client.get(LOGIN_PATH)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/setup", response["Location"])
