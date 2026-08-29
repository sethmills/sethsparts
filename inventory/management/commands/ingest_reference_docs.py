import json
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from inventory.models import ReferenceDoc

USER_AGENT = "Mozilla/5.0 (compatible; SethsParts/1.0; personal workshop reference library)"


class Command(BaseCommand):
    help = "Ingest curated reference-doc research (JSON) into ReferenceDoc records + downloaded files."

    def add_arguments(self, parser):
        parser.add_argument("json_path", type=str)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = options["json_path"]
        try:
            with open(path) as f:
                entries = json.load(f)
        except FileNotFoundError as exc:
            raise CommandError(f"File not found: {path}") from exc

        dry_run = options["dry_run"]
        stats = {"created": 0, "download_failed": 0}

        for entry in entries:
            self.stdout.write(f"{entry['title']} [{entry['category']}]")
            if dry_run:
                continue

            doc, _ = ReferenceDoc.objects.update_or_create(
                title=entry["title"],
                defaults={
                    "category": entry["category"],
                    "description": entry.get("description", ""),
                    "external_url": entry.get("external_url") or entry.get("source_url") or "",
                    "order": entry.get("order", 100),
                },
            )
            stats["created"] += 1

            file_url = entry.get("file_url") or entry.get("image_url") or entry.get("pdf_url")
            if file_url:
                content = self._fetch(file_url)
                if content is None:
                    stats["download_failed"] += 1
                else:
                    filename = urlparse(file_url).path.rsplit("/", 1)[-1] or f"{doc.pk}.bin"
                    doc.file.save(filename, ContentFile(content), save=True)

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
