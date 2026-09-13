"""Refresh the map's pins from connected workshops, and expire anything stale.

Meant for cron or a systemd timer. Pin exchange should not depend on somebody opening a
page — and, just as importantly, it should not *happen* because somebody opened one: a
page that quietly talks to other people's servers is a surprise, and it makes the page
dependent on several strangers being up.

Safe to run as often as you like. Each peer is asked once, entries that are not newer
than what we hold are ignored, and nothing is forwarded beyond the hop limit.
"""
from django.core.management.base import BaseCommand

from ... import community_pins


class Command(BaseCommand):
    help = "Ask connected workshops for their map pins, merge anything new, and expire stale entries."

    def handle(self, *args, **options):
        learned, notes = community_pins.sync_from_peers()
        pruned = community_pins.prune_stale_pins()

        entries = "entry" if learned == 1 else "entries"
        self.stdout.write(f"Learned {learned} new pin {entries}.")

        if pruned:
            expired = "entry" if pruned == 1 else "entries"
            self.stdout.write(f"Expired {pruned} stale pin {expired}.")

        # Per-peer failures go to stderr and do not fail the command: one workshop being
        # offline is normal, and cron mail for it would be noise nobody reads.
        for note in notes:
            self.stderr.write(note)
