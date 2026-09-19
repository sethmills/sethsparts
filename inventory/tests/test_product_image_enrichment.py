"""Web research can attach a product image to a part automatically."""
import tempfile
from unittest import mock

from django.test import TestCase, override_settings

from ..archiving import ArchiveResult
from ..models import Attachment
from ..views.enrichment import _apply_research, _attach_product_image
from .factories import make_part


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProductImageEnrichmentTests(TestCase):
    def test_research_attaches_product_image(self):
        part = make_part(name="DS18B20")
        data = {
            "category": "Sensors",
            "manufacturer": "Maxim",
            "product_url": "https://example.com/ds18b20",
            "image_url": "https://example.com/ds18b20.jpg",
            "confidence": "high",
        }
        fake = ArchiveResult(
            ok=True, content=b"\xff\xd8\xff\xe0 fake-jpeg", content_type="image/jpeg", filename="ds18b20.jpg"
        )
        with mock.patch("inventory.archiving.fetch", return_value=fake):
            _apply_research(part, data)
        image = Attachment.objects.get(part=part, doc_type=Attachment.IMAGE)
        self.assertEqual(image.source_url, "https://example.com/ds18b20.jpg")

    def test_non_image_content_is_skipped(self):
        part = make_part(name="DS18B20")
        fake = ArchiveResult(ok=True, content=b"<html>", content_type="text/html", filename="page.html")
        with mock.patch("inventory.archiving.fetch", return_value=fake):
            attached = _attach_product_image(part, "https://example.com/page.html")
        self.assertFalse(attached)
        self.assertFalse(Attachment.objects.filter(part=part).exists())

    def test_dead_image_link_is_ignored(self):
        part = make_part(name="DS18B20")
        fake = ArchiveResult(ok=False, error="HTTP 404")
        with mock.patch("inventory.archiving.fetch", return_value=fake):
            attached = _attach_product_image(part, "https://example.com/nope.jpg")
        self.assertFalse(attached)
        self.assertFalse(Attachment.objects.filter(part=part).exists())
