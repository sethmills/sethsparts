from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Container, Drawer, DrawerLedSegment

# Seth's measured LED-per-drawer counts (2026-08-31), 1-based LED numbers as he gave them,
# converted here to (0-based start_index, count). Same pattern applies to every left/right
# strip for cabinets 1-3; cabinet 4's single (left-only, by design -- no right-side strip)
# strip has its own measured pattern.
STANDARD_PATTERN = [(0, 10), (10, 10), (20, 10), (30, 10), (40, 10), (50, 10), (60, 10), (70, 9), (79, 10)]
CABINET4_LEFT_PATTERN = [(0, 6), (6, 7), (13, 6), (19, 6), (25, 6), (31, 10), (41, 9), (50, 9), (59, 9)]

# (container number, first drawer number in that cabinet, [(logical strip name, pattern), ...])
# Strip names must match led-controller/pi/strip_map.json.example's keys on the Pi side.
CABINETS = [
    (38, 1, [("cabinet1-left", STANDARD_PATTERN), ("cabinet1-right", STANDARD_PATTERN)]),
    (39, 10, [("cabinet2-left", STANDARD_PATTERN), ("cabinet2-right", STANDARD_PATTERN)]),
    (40, 19, [("cabinet3-left", STANDARD_PATTERN), ("cabinet3-right", STANDARD_PATTERN)]),
    (119, 28, [("cabinet4-left", CABINET4_LEFT_PATTERN)]),
]


class Command(BaseCommand):
    help = "Seed DrawerLedSegment rows from Seth's measured LED-per-drawer counts. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        created, updated = 0, 0

        with transaction.atomic():
            for container_number, first_drawer, strips in CABINETS:
                container = Container.objects.get(number=container_number)
                for strip_name, pattern in strips:
                    for position, (start, count) in enumerate(pattern, start=1):
                        drawer_number = first_drawer + position - 1
                        drawer = Drawer.objects.get(container=container, label=f"Drawer {drawer_number}")
                        self.stdout.write(f"{drawer} : {strip_name} [{start}:{start + count}]")
                        if not dry_run:
                            _, was_created = DrawerLedSegment.objects.update_or_create(
                                drawer=drawer,
                                led_strip=strip_name,
                                defaults={"led_start_index": start, "led_count": count},
                            )
                            created += was_created
                            updated += not was_created

            if dry_run:
                self.stdout.write(self.style.WARNING("Dry run — no changes written."))
                transaction.set_rollback(True)
            else:
                self.stdout.write(self.style.SUCCESS(f"Created {created}, updated {updated} DrawerLedSegment rows."))
