"""The public-repo audit script's pattern matching.

`scripts/audit_public_repo.py` answers "is anything secret-shaped in this repository's
history, and would publishing it expose something?". It is only worth running if it is both
**sensitive** (catches a real key) and **quiet** on a repository that is already clean —
a scanner that cries wolf gets ignored, which is worse than no scanner at all. Both halves
are tested here.

The script itself walks git plumbing; the part worth testing is the pure pattern matching,
so nothing here needs a repository, a database, or a process.
"""
import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "audit_public_repo.py"


def load_audit():
    """Loaded by path: `scripts/` is not a package, and this is a tool rather than app code."""
    spec = importlib.util.spec_from_file_location("audit_public_repo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load_audit()


class SensitiveEnoughTests(SimpleTestCase):
    """It has to notice a real credential, whatever shape it arrives in."""

    def labels(self, text):
        return [label for label, _snippet in audit.findings_in(text)]

    def test_a_private_key_block_is_caught(self):
        self.assertIn("private key", self.labels("-----BEGIN RSA PRIVATE KEY-----\nMIIEow…"))

    def test_an_aws_access_key_is_caught(self):
        self.assertIn("AWS access key", self.labels("aws_access_key_id = AKIA3XJ7QZ2LMNBV4C6D"))

    def test_a_documentation_example_key_is_deliberately_ignored(self):
        """AWS's own docs use `AKIAIOSFODNN7EXAMPLE`, and so does every tutorial.

        The placeholder filter drops it, which is the right trade: the value contains
        `EXAMPLE`, and a scanner that reports every tutorial's sample key is one people stop
        reading. Worth pinning so nobody "fixes" it into noise.
        """
        self.assertEqual(self.labels("aws_access_key_id = AKIAIOSFODNN7EXAMPLE"), [])

    def test_a_github_token_is_caught(self):
        self.assertIn("GitHub token", self.labels("https://x:ghp_" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8@github.com"))

    def test_a_secret_assigned_to_a_variable_is_caught(self):
        self.assertIn("assigned secret", self.labels('DJANGO_SECRET_KEY = "9f2a7c1e4b8d3f6a0c5e2b9d")'))

    def test_a_long_hex_string_is_caught(self):
        self.assertIn("64-char hex string", self.labels("token=" + "a1" * 32))

    def test_the_snippet_is_short_enough_to_print(self):
        for _label, snippet in audit.findings_in("PASSWORD = " + "x" * 200):
            self.assertLessEqual(len(snippet), 80)


class QuietEnoughTests(SimpleTestCase):
    """And it has to stay quiet on the things that are not credentials, or nobody reads it."""

    def labels(self, text):
        return [label for label, _snippet in audit.findings_in(text)]

    def test_placeholders_are_ignored(self):
        for text in (
            "SECRET_KEY=your-key-goes-here",
            "TUNNEL_TOKEN=example-token-value",
            "API_KEY={{ api_key }}",
            "SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(50))')",
            "PASSWORD=os.environ['DB_PASSWORD']",
            "TOKEN=getenv('TOKEN')",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.labels(text), [], text)

    def test_an_empty_assignment_is_ignored(self):
        """The whole of `.env.example`: names with nothing after them."""
        self.assertEqual(self.labels("DJANGO_SECRET_KEY=\nTUNNEL_TOKEN=\nLABEL_PRINTER_KEY=\n"), [])

    def test_an_assignment_does_not_match_across_lines(self):
        """`_KEY=` followed by a newline and an unrelated value is not an assignment.

        This is a false positive the script shipped with: matching whitespace let the value
        on the *next* line be read as the secret, in a file documenting variable names.
        """
        self.assertEqual(self.labels("LABEL_PRINTER_KEY=\nLABEL_PRINTER_DRIVER=zpl"), [])

    def test_test_fixtures_in_this_suite_are_the_known_findings(self):
        """Spelled out, because the audit reports these on every run and they must stay boring."""
        self.assertIn("assigned secret", self.labels('TOKEN = "kiosk-shared-secret"'))


class PathTests(SimpleTestCase):
    def test_the_env_example_is_deliberate_not_an_accident(self):
        self.assertIn(".env.example", audit.DELIBERATE)
        self.assertEqual(audit.path_findings({".env.example"}), [])

    def test_files_that_should_never_be_tracked_are_flagged(self):
        for path in (".env", "deploy_key", ".deploy_key", "id_rsa", "keys/server.pem",
                     "db.sqlite3", "data/db.sqlite3.pre-deploy-20260101-000000.bak", "media/photo.jpg"):
            with self.subTest(path=path):
                self.assertEqual(audit.path_findings({path}), [path])

    def test_ordinary_source_files_are_not_flagged(self):
        self.assertEqual(audit.path_findings({"inventory/models.py", "README.md", "docs/RUNNING.md"}), [])


class AllowlistTests(SimpleTestCase):
    def test_every_allowed_finding_says_why(self):
        """Both entry forms. A list entry explains each needle it excuses, not just the file."""
        for path, reason in audit.KNOWN_BENIGN.items():
            with self.subTest(path=path):
                if isinstance(reason, str):
                    self.assertTrue(reason.strip(), f"{path} has no explanation")
                else:
                    self.assertTrue(reason, f"{path} has an empty needle list")
                    for needle, needle_reason in reason:
                        self.assertTrue(needle.strip(), f"{path} has a blank needle")
                        self.assertTrue(needle_reason.strip(), f"{path} needle {needle!r} has no explanation")

    def test_the_allowlist_only_names_files_that_exist(self):
        """A stale entry would silently excuse a path that has been renamed."""
        root = Path(__file__).resolve().parent.parent.parent
        for path in audit.KNOWN_BENIGN:
            with self.subTest(path=path):
                self.assertTrue((root / path).exists(), f"{path} is in the allowlist but not in the repo")

    def test_a_needle_scoped_entry_excuses_only_that_needle(self):
        """The reason the two forms exist.

        `scripts/audit_public_repo.py` is allowed to name the test fixtures in its
        explanations — but a *different* secret committed to that same file must still fail
        the run. A whole-file exemption here would be a blind spot in a security tool, which
        is the one place it would never be noticed.
        """
        excused = audit.benign_reason("scripts/audit_public_repo.py", 'TOKEN = "kiosk-shared-secret"')
        self.assertTrue(excused)
        self.assertIsNone(audit.benign_reason("scripts/audit_public_repo.py", 'aws = "AKIA3XJ7QZ2LMNBV4C6D"'))

    def test_a_whole_file_entry_excuses_anything_in_that_file(self):
        """The other form, for files that are deliberately nothing but fixtures."""
        self.assertTrue(audit.benign_reason("inventory/tests/test_login.py", "anything at all"))

    def test_an_unlisted_file_is_never_excused(self):
        self.assertIsNone(audit.benign_reason("inventory/views/setup.py", 'TOKEN = "kiosk-shared-secret"'))

    def test_the_scanner_is_not_exempt_from_scanning_itself(self):
        """It must stay sensitive in its own source: only the three known fixture names are
        excused there, so the file is still read rather than skipped."""
        needles = [needle for needle, _reason in audit.KNOWN_BENIGN["scripts/audit_public_repo.py"]]
        self.assertEqual(sorted(needles), sorted(["Sh0pFull-0f-P4rts", "correct-horse-battery-", "kiosk-shared-secret"]))
