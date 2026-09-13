"""Check whether a newer version exists, from the command line.

Useful for a cron job that emails you when there's something new — which suits this
app better than a badge nobody looks at, since an install can go months between
visits to the settings page.

Exits non-zero when an update is available, so it composes with whatever you already
use to get notified:

    python manage.py check_updates || echo "update available" | mail -s ... you@example.com
"""
from django.core.management.base import BaseCommand

from inventory import updates


class Command(BaseCommand):
    help = "Check GitHub for a newer version. Exits 1 when one is available."

    def add_arguments(self, parser):
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Only report when an update exists — for cron.",
        )

    def handle(self, *args, **options):
        if not updates.enabled():
            if not options["quiet"]:
                self.stdout.write("Update checking is switched off (UPDATE_CHECK_ENABLED=false).")
            return

        info = updates.check_for_update()

        if info.update_available:
            self.stdout.write(
                self.style.WARNING(f"A newer version is available: {info.latest} (you have {info.current}).")
            )
            if info.url:
                self.stdout.write(f"  {info.url}")
            if info.notes:
                self.stdout.write(f"  {info.notes}")
            # Exit 1 so this can drive a notification directly.
            raise SystemExit(1)

        if info.ok:
            if not options["quiet"]:
                self.stdout.write(self.style.SUCCESS(f"You're up to date ({info.current})."))
            return

        # A failed check is not worth failing a cron job over — it would email on every
        # blip in connectivity, and people stop reading notifications that cry wolf.
        if not options["quiet"]:
            self.stdout.write(self.style.WARNING(f"Couldn't check: {info.error}"))
