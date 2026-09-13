"""Archiving external documents.

The feature exists because links rot, so the tests are mostly about the inglorious
cases: a 404, a bot wall, a file too big, a URL that isn't http at all. A happy-path
test would prove almost nothing here.

Nothing in this module touches the network. `inventory/tests/__init__.py` blocks real
outbound GETs outright, so a test that forgot to patch would fail loudly rather than
quietly depending on someone's website still being up.
"""
import tempfile
from unittest import mock

from django.test import TestCase, override_settings

from inventory import archiving
from inventory.models import ReferenceCategory, ReferenceDoc

from .factories import make_part


class FakeResponse:
    """Just enough of a requests response for archiving to work with."""

    def __init__(self, *, status_code=200, content=b"%PDF-1.4 fake", content_type="application/pdf", url=None):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type else {}
        self._content = content
        self.url = url or "https://example.test/doc.pdf"
        self.closed = False

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    def close(self):
        self.closed = True


class FilenameTests(TestCase):
    def test_uses_the_urls_own_name(self):
        self.assertEqual(
            archiving.filename_for("https://example.test/docs/DS18B20-datasheet.pdf", "application/pdf"),
            "DS18B20-datasheet.pdf",
        )

    def test_strips_path_traversal_and_odd_characters(self):
        """The name comes from a remote server, so it is not trusted to be a filename."""
        got = archiving.filename_for("https://example.test/../../etc/passwd.pdf", "application/pdf")
        self.assertNotIn("/", got)
        self.assertNotIn("..", got)

    def test_strips_a_leading_dot_so_it_cannot_be_hidden(self):
        self.assertFalse(archiving.filename_for("https://example.test/.hidden.pdf", "application/pdf").startswith("."))

    def test_url_decodes_percent_escapes(self):
        got = archiving.filename_for("https://example.test/My%20Data%20Sheet.pdf", "application/pdf")
        self.assertEqual(got, "My_Data_Sheet.pdf")

    def test_falls_back_to_the_content_type_when_the_url_has_no_name(self):
        self.assertEqual(archiving.filename_for("https://example.test/", "application/pdf"), "document.pdf")
        self.assertEqual(archiving.filename_for("https://example.test/", "image/png"), "document.png")

    def test_falls_back_to_a_generic_extension_for_an_unknown_type(self):
        self.assertEqual(archiving.filename_for("https://example.test/", "application/x-weird"), "document.bin")

    def test_a_url_with_no_extension_is_not_treated_as_a_name(self):
        self.assertEqual(archiving.filename_for("https://example.test/datasheet", "application/pdf"), "document.pdf")


class FetchGuardTests(TestCase):
    """Rejections that must happen before any network call is made."""

    def test_non_http_schemes_are_refused(self):
        for url in ("ftp://example.test/x.pdf", "file:///etc/passwd", "javascript:alert(1)"):
            with self.subTest(url=url):
                result = archiving.fetch(url)
                self.assertFalse(result.ok)
                self.assertIn("http", result.error)

    def test_a_url_with_no_host_is_refused(self):
        result = archiving.fetch("http:///nohost.pdf")
        self.assertFalse(result.ok)

    def test_an_empty_url_is_refused(self):
        self.assertFalse(archiving.fetch("").ok)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FetchOutcomeTests(TestCase):
    def get(self, response=None, exc=None):
        patcher = mock.patch("requests.get")
        fake = patcher.start()
        self.addCleanup(patcher.stop)
        if exc is not None:
            fake.side_effect = exc
            return archiving.fetch("https://example.test/doc.pdf")
        fake.return_value = response
        return archiving.fetch("https://example.test/doc.pdf")

    def test_a_good_response_is_returned(self):
        result = self.get(FakeResponse())
        self.assertTrue(result.ok)
        self.assertEqual(result.content, b"%PDF-1.4 fake")
        self.assertEqual(result.content_type, "application/pdf")
        self.assertEqual(result.filename, "doc.pdf")

    def test_a_404_is_reported_in_plain_words(self):
        result = self.get(FakeResponse(status_code=404))
        self.assertFalse(result.ok)
        self.assertIn("404", result.error)

    def test_a_500_is_reported_too(self):
        result = self.get(FakeResponse(status_code=500))
        self.assertFalse(result.ok)
        self.assertIn("500", result.error)

    def test_a_connection_error_does_not_raise(self):
        import requests

        result = self.get(exc=requests.ConnectionError("connection refused"))
        self.assertFalse(result.ok)
        self.assertIn("refused", result.error)

    def test_a_timeout_does_not_raise(self):
        import requests

        result = self.get(exc=requests.Timeout("timed out"))
        self.assertFalse(result.ok)
        self.assertIn("timed out", result.error)

    def test_an_oversized_file_is_refused_rather_than_stored(self):
        """One bad URL must not be able to fill the disk."""
        big = FakeResponse(content=b"x" * (2 * 1024 * 1024))
        patcher = mock.patch("requests.get", return_value=big)
        patcher.start()
        self.addCleanup(patcher.stop)
        result = archiving.fetch("https://example.test/big.pdf", max_bytes=1024)
        self.assertFalse(result.ok)
        self.assertIn("larger than", result.error)

    def test_an_empty_response_is_refused(self):
        """A 200 with no body is not a document, and storing a zero-byte file would
        look like a successful archive in the UI."""
        result = self.get(FakeResponse(content=b""))
        self.assertFalse(result.ok)
        self.assertIn("empty", result.error)

    def test_the_connection_is_always_closed(self):
        response = FakeResponse()
        self.get(response)
        self.assertTrue(response.closed)

    def test_octet_stream_with_a_pdf_url_is_treated_as_a_pdf(self):
        """Many servers serve PDFs as application/octet-stream; the URL is better
        evidence of what the file actually is."""
        result = self.get(FakeResponse(content_type="application/octet-stream"))
        self.assertEqual(result.content_type, "application/pdf")

    def test_html_is_recorded_as_html_not_disguised(self):
        result = self.get(FakeResponse(content=b"<html>login</html>", content_type="text/html; charset=utf-8"))
        self.assertEqual(result.content_type, "text/html")
        self.assertTrue(result.is_html)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ArchiveReferenceDocTests(TestCase):
    def setUp(self):
        self.category = ReferenceCategory.objects.create(name="Test shelf", key="test-shelf", order=10)
        self.doc = ReferenceDoc.objects.create(
            title="DS18B20 datasheet", category=self.category, external_url="https://example.test/ds18b20.pdf"
        )

    def patch_get(self, response):
        patcher = mock.patch("requests.get", return_value=response)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_successful_fetch_stores_the_file_and_records_it(self):
        self.patch_get(FakeResponse())
        result = archiving.archive_reference_doc(self.doc)
        self.assertTrue(result.ok)

        self.doc.refresh_from_db()
        self.assertTrue(self.doc.file)
        self.assertIsNotNone(self.doc.archived_at)
        self.assertEqual(self.doc.archive_content_type, "application/pdf")
        self.assertEqual(self.doc.archive_error, "")
        self.assertTrue(self.doc.is_archived)
        self.assertFalse(self.doc.needs_archiving)

    def test_a_failed_fetch_records_the_reason_and_keeps_the_link(self):
        """A login wall is still worth keeping as a link — it just has to say so
        rather than looking like a cached document that isn't there."""
        self.patch_get(FakeResponse(status_code=403))
        result = archiving.archive_reference_doc(self.doc)
        self.assertFalse(result.ok)

        self.doc.refresh_from_db()
        self.assertFalse(self.doc.file)
        self.assertIsNone(self.doc.archived_at)
        self.assertIn("403", self.doc.archive_error)
        self.assertTrue(self.doc.archive_failed)
        self.assertEqual(self.doc.external_url, "https://example.test/ds18b20.pdf")

    def test_a_later_failure_does_not_discard_an_earlier_good_copy(self):
        """The already-archived copy is the whole point of the feature, so a failed
        refresh must not throw it away."""
        self.patch_get(FakeResponse())
        archiving.archive_reference_doc(self.doc)
        self.doc.refresh_from_db()
        good_file = self.doc.file.name

        self.patch_get(FakeResponse(status_code=500))
        archiving.archive_reference_doc(self.doc)

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.file.name, good_file)
        self.assertTrue(self.doc.is_archived)

    def test_the_attempt_is_timestamped_even_when_it_fails(self):
        self.patch_get(FakeResponse(status_code=404))
        archiving.archive_reference_doc(self.doc)
        self.doc.refresh_from_db()
        self.assertIsNotNone(self.doc.archive_attempted_at)

    def test_a_document_with_no_link_reports_that_rather_than_fetching(self):
        doc = ReferenceDoc.objects.create(title="Handwritten note", category=self.category)
        result = archiving.archive_reference_doc(doc)
        self.assertFalse(result.ok)
        self.assertIn("No source link", result.error)


class ArchiveStateTests(TestCase):
    def setUp(self):
        self.category = ReferenceCategory.objects.create(name="Test shelf", key="test-shelf")

    def test_a_linked_document_with_no_copy_needs_archiving(self):
        doc = ReferenceDoc.objects.create(title="Chart", category=self.category, external_url="https://x.test/a.pdf")
        self.assertTrue(doc.needs_archiving)

    def test_a_document_with_no_link_does_not_need_archiving(self):
        """Nothing to fetch is not the same as something outstanding."""
        doc = ReferenceDoc.objects.create(title="Note", category=self.category)
        self.assertFalse(doc.needs_archiving)

    def test_never_tried_is_not_the_same_as_failed(self):
        doc = ReferenceDoc.objects.create(title="Chart", category=self.category, external_url="https://x.test/a.pdf")
        self.assertFalse(doc.archive_failed, "not attempted yet")
        doc.archive_error = "HTTP 500"
        self.assertTrue(doc.archive_failed, "attempted and failed")

    def test_a_document_with_a_copy_is_archived(self):
        doc = ReferenceDoc.objects.create(title="Chart", category=self.category, external_url="https://x.test/a.pdf")
        doc.file = "reference/2026/a.pdf"
        doc.archived_at = doc.archive_attempted_at = None
        from django.utils import timezone

        doc.archived_at = timezone.now()
        self.assertTrue(doc.is_archived)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ArchiveOnSaveSettingTests(TestCase):
    def test_archiving_can_be_switched_off_entirely(self):
        """For an owner who does not want the app making outbound requests — turning
        it off must leave links working and simply not fetch anything."""
        with self.settings(ARCHIVE_ON_SAVE=False):
            self.assertFalse(archiving.archive_on_save_enabled())

    def test_it_is_on_by_default(self):
        self.assertTrue(archiving.archive_on_save_enabled())

    def test_the_timeout_is_configurable(self):
        with self.settings(ARCHIVE_TIMEOUT=5):
            self.assertEqual(archiving.archive_timeout(), 5)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AttachmentArchivingTests(TestCase):
    def test_a_part_attachment_can_be_archived_from_its_source_url(self):
        """Attachments are the other half of the same problem — a part datasheet is
        exactly the document most likely to vanish."""
        from inventory.models import Attachment

        part = make_part(name="DS18B20 sensor")
        attachment = Attachment.objects.create(
            part=part, doc_type=Attachment.DATASHEET, source_url="https://example.test/ds18b20.pdf"
        )

        patcher = mock.patch("requests.get", return_value=FakeResponse())
        patcher.start()
        self.addCleanup(patcher.stop)

        result = archiving.archive_attachment(attachment)
        self.assertTrue(result.ok)
        attachment.refresh_from_db()
        self.assertTrue(attachment.file)
        self.assertIsNotNone(attachment.archived_at)

    def test_an_attachment_with_no_source_link_is_reported(self):
        from inventory.models import Attachment

        part = make_part(name="Something")
        attachment = Attachment.objects.create(part=part, doc_type=Attachment.IMAGE)
        # No source_url, no file content supplied, so this is the "nothing to do" case.
        result = archiving.archive_attachment(attachment)
        self.assertFalse(result.ok)
        self.assertIn("No source link", result.error)
