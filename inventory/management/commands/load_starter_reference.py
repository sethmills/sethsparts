"""Load the starter reference library.

The shipped set is Seth's own reference library — pinout charts, wire gauge tables,
soldering guides, 3D printing troubleshooting. It is deliberately generic rather than
personal, which is what makes it a reasonable starting point for someone else's
workshop.

There is nothing special about these entries. They are ordinary ReferenceDoc rows that
the owner can edit, reorder, move between categories or delete — including deleting
every single one to start from a blank library. This command exists so that choice is
available, not so the content is privileged in any way.

**Safe to re-run.** Categories match on their key and documents on their title within
a category, so running it twice does not duplicate anything. It also will not
resurrect something that was deliberately deleted: if you removed "Breadboard Basics",
running this again leaves it removed.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventory.models import ReferenceCategory, ReferenceDoc, SiteSettings

STARTER_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "starter_reference.json"


class Command(BaseCommand):
    help = "Load the starter reference library (idempotent; never duplicates or resurrects deleted entries)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be added without writing anything.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-add missing documents even though the set was loaded before.",
        )

    def handle(self, *args, **options):
        # One-shot by default. Without this the command would quietly resurrect
        # documents the owner had deleted — which would make the library
        # impossible to prune, and turn a convenience into a nag.
        site = SiteSettings.load()
        if site.starter_reference_loaded_at and not options['force']:
            self.stdout.write(
                "The starter set was already loaded on "
                f"{site.starter_reference_loaded_at:%Y-%m-%d}. Nothing to do — pass --force to "
                "re-add anything currently missing (including things you removed)."
            )
            return

        if not STARTER_FILE.exists():
            raise CommandError(f"Starter reference file not found: {STARTER_FILE}")

        with open(STARTER_FILE, encoding="utf-8") as f:
            data = json.load(f)

        dry_run = options["dry_run"]
        categories_added = 0
        docs_added = 0
        docs_skipped = 0

        with transaction.atomic():
            by_key = {}
            for entry in data.get("categories", []):
                category, created = ReferenceCategory.objects.get_or_create(
                    key=entry["key"],
                    defaults={"name": entry["name"], "order": entry.get("order", 100)},
                )
                by_key[entry["key"]] = category
                categories_added += int(created)

            for entry in data.get("documents", []):
                category = by_key.get(entry["category"])
                if category is None:
                    # A document referencing a category that isn't in the file is a
                    # broken starter set, not a user error — say so rather than
                    # quietly skipping it.
                    raise CommandError(f"Starter file references unknown category {entry['category']!r}")

                exists = ReferenceDoc.objects.filter(category=category, title=entry["title"]).exists()
                if exists:
                    docs_skipped += 1
                    continue
                ReferenceDoc.objects.create(
                    category=category,
                    title=entry["title"],
                    description=entry.get("description", ""),
                    external_url=entry.get("external_url", ""),
                    order=entry.get("order", 100),
                )
                docs_added += 1

            if dry_run:
                transaction.set_rollback(True)

        if not dry_run:
            site.starter_reference_loaded_at = site.starter_reference_loaded_at or timezone.now()
            site.save(update_fields=["starter_reference_loaded_at"])

        prefix = "Would add" if dry_run else "Added"
        self.stdout.write(
            f"{prefix} {categories_added} category(ies) and {docs_added} reference(s); "
            f"{docs_skipped} already present."
        )
        if dry_run:
            self.stdout.write("Dry run — nothing was written.")
