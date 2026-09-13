"""Fetch local copies for anything linked but not yet archived.

This is the command that makes the archiving promise true in bulk. It matters most
right after loading the starter reference set, which ships as **links only** — the
repository deliberately contains no third-party files, so each install fetches its
own copies of what it chooses to keep.

Polite by default: a pause between requests, because these are other people's servers
and none of this is urgent. Failed fetches leave their reason on the row rather than
retrying forever — some links are behind a login wall or simply gone, and the answer
is to be told that, not to keep asking.
"""
import time

from django.core.management.base import BaseCommand

from inventory import archiving
from inventory.models import Attachment, ReferenceDoc


class Command(BaseCommand):
    help = "Archive local copies of linked documents that don't have one yet."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many fetches (0 = no limit).")
        parser.add_argument("--pause", type=float, default=1.0, help="Seconds to wait between requests.")
        parser.add_argument(
            "--include-attachments",
            action="store_true",
            help="Also re-check part attachments whose source link has no stored file.",
        )
        parser.add_argument("--dry-run", action="store_true", help="List what would be fetched, and stop.")

    def handle(self, *args, **options):
        limit = options["limit"]
        pause = options["pause"]
        dry_run = options["dry_run"]

        docs = list(ReferenceDoc.objects.filter(external_url__gt="", file=""))
        attachments = []
        if options["include_attachments"]:
            attachments = list(Attachment.objects.filter(source_url__gt="", file=""))

        total = len(docs) + len(attachments)
        if not total:
            self.stdout.write("Nothing to archive — every linked document already has a local copy.")
            return

        self.stdout.write(f"{total} linked document(s) with no local copy.")
        if dry_run:
            for doc in docs:
                self.stdout.write(f"  [reference] {doc.title} <- {doc.external_url}")
            for att in attachments:
                self.stdout.write(f"  [attachment] {att} <- {att.source_url}")
            self.stdout.write("Dry run — nothing was fetched.")
            return

        archived = failed = 0
        for doc in docs:
            if limit and archived + failed >= limit:
                break
            result = archiving.archive_reference_doc(doc)
            if result.ok:
                archived += 1
                self.stdout.write(self.style.SUCCESS(f"  archived  {doc.title}  ({result.content_type})"))
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"  failed    {doc.title}  — {result.error}"))
            time.sleep(pause)

        for att in attachments:
            if limit and archived + failed >= limit:
                break
            result = archiving.archive_attachment(att)
            if result.ok:
                archived += 1
                self.stdout.write(self.style.SUCCESS(f"  archived  {att}"))
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"  failed    {att} — {result.error}"))
            time.sleep(pause)

        self.stdout.write(f"\n{archived} archived, {failed} failed.")
        if failed:
            self.stdout.write(
                "Failures are recorded on each document; re-run this, or use the Archive button, to retry."
            )
