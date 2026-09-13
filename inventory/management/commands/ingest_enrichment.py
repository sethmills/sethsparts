import json
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Attachment, Part

USER_AGENT = "Mozilla/5.0 (compatible; SethsParts/1.0; personal workshop catalog)"

MANUFACTURER_BY_DOMAIN = {
    "adafruit.com": "Adafruit",
    "raspberrypi.com": "Raspberry Pi Foundation",
    "raspberrypi.org": "Raspberry Pi Foundation",
    "sparkfun.com": "SparkFun",
    "pjrc.com": "PJRC",
    "nvidia.com": "NVIDIA",
    "fluke.com": "Fluke",
    "uugear.com": "UUGear",
    "arduino.cc": "Arduino",
    "beagleboard.org": "BeagleBoard.org Foundation",
}


GENERIC_MARKERS = ("generic", "commodity", "unspecified")


def _manufacturer_for(entry):
    """Infer manufacturer from the product/learn-guide domain — but not for entries the
    research explicitly flagged as a generic/commodity item, where the linked domain is
    just a reference/tutorial source, not the actual maker."""
    name = (entry.get("matched_product_name") or "").lower()
    if any(marker in name for marker in GENERIC_MARKERS):
        return ""
    for url in (entry.get("product_url"), entry.get("learn_guide_url")):
        if not url:
            continue
        host = urlparse(url).netloc.lower().removeprefix("www.")
        for domain, manufacturer in MANUFACTURER_BY_DOMAIN.items():
            if host == domain or host.endswith("." + domain):
                return manufacturer
    return ""


class Command(BaseCommand):
    help = "Ingest enrichment research (JSON) into Part records + downloaded Attachments."

    def add_arguments(self, parser):
        parser.add_argument("json_path", type=str)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = options["json_path"]
        try:
            with open(path, encoding="utf-8") as f:
                entries = json.load(f)
        except FileNotFoundError as exc:
            raise CommandError(f"File not found: {path}") from exc

        dry_run = options["dry_run"]
        stats = {"parts_updated": 0, "attachments_created": 0, "downloads_failed": 0, "parts_missing": 0}

        for entry in entries:
            try:
                part = Part.objects.get(pk=entry["id"])
            except Part.DoesNotExist:
                self.stderr.write(f"No Part with id={entry.get('id')} — skipping")
                stats["parts_missing"] += 1
                continue

            confidence = (entry.get("confidence") or "").lower()
            self.stdout.write(f"\n{part.id} {part.name!r} -> {entry.get('matched_product_name')} ({confidence})")

            if dry_run:
                continue

            manufacturer = _manufacturer_for(entry)
            if manufacturer:
                part.manufacturer = manufacturer
            if entry.get("description"):
                part.description = entry["description"]
            if entry.get("product_url"):
                part.reorder_url = entry["product_url"]
            notes_parts = [entry.get("matched_product_name", ""), entry.get("notes", "")]
            part.enrichment_status = (
                Part.ENRICHMENT_DONE if confidence == "high" else Part.ENRICHMENT_NEEDS_REVIEW
            )
            part.save()
            stats["parts_updated"] += 1

            downloads = [
                ("image_url", Attachment.IMAGE, "product photo"),
                ("pinout_image_url", Attachment.PINOUT, "pinout diagram"),
                ("datasheet_url", Attachment.DATASHEET, "datasheet"),
                ("product_url", Attachment.PRODUCT_PAGE, "product page (archived)"),
                ("learn_guide_url", Attachment.PRODUCT_PAGE, "learn guide (archived)"),
            ]
            for key, doc_type, title in downloads:
                url = entry.get(key)
                if not url:
                    continue
                content = self._fetch(url)
                if content is None:
                    stats["downloads_failed"] += 1
                    continue
                attachment = Attachment(part=part, doc_type=doc_type, source_url=url, title=title)
                filename = self._filename_for(url, doc_type)
                attachment.file.save(filename, ContentFile(content), save=True)
                stats["attachments_created"] += 1

        self.stdout.write(self.style.SUCCESS("\nDone:"))
        for k, v in stats.items():
            self.stdout.write(f"  {k}: {v}")

    def _fetch(self, url):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            self.stderr.write(f"  failed to fetch {url}: {exc}")
            return None

    def _filename_for(self, url, doc_type):
        parsed = urlparse(url)
        base = parsed.path.rsplit("/", 1)[-1] or "file"
        if doc_type == Attachment.PRODUCT_PAGE and "." not in base:
            base += ".html"
        return base
