"""Archive every reference document that has a source link but no local copy.

The setup page archives five at a time as a demonstration; this is the bulk run the
comment there refers to. Each fetch is independent and never raises — a dead link is
expected input — so one bad URL cannot stop the pass. The outcome is recorded on the
row either way (a stored copy, or an `archive_error` explaining why), which is what
the reference pages already show.
"""
from django.core.management.base import BaseCommand

from inventory import archiving
from inventory.models import ReferenceDoc


class Command(BaseCommand):
    help = "Fetch and store local copies of every reference document still linking out."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would be archived without fetching anything."
        )

    def handle(self, *args, **options):
        docs = ReferenceDoc.objects.filter(external_url__gt="", file="").order_by("title")

        if options["dry_run"]:
            self.stdout.write(f"{docs.count()} reference document(s) would be archived:")
            for doc in docs:
                self.stdout.write(f"  - {doc.title} ({doc.external_url})")
            return

        archived = failed = 0
        for doc in docs:
            result = archiving.archive_reference_doc(doc)
            if result.ok:
                archived += 1
                self.stdout.write(self.style.SUCCESS(f"Archived: {doc.title}"))
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(f"Failed: {doc.title} — {result.error}"))

        self.stdout.write(f"\nDone: {archived} archived, {failed} failed, {docs.count()} total.")
