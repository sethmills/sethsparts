from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Container, Drawer, DrawerLedSegment

# Seth's re-measured LED-per-drawer counts (2026-09-09), taken after confirming the real
# physical-strip <-> logical-strip-name mapping via the /locate test sequence (physical strips
# 1-7 right-to-left correspond to cabinet3-left, cabinet3-right, cabinet2-left, cabinet2-right,
# cabinet1-left, cabinet1-right, cabinet4-left, in that order). 1-based LED numbers as he gave
# them, converted here to (0-based start_index, count).
#
# cabinet1-left (physical strip 5) and cabinet2/cabinet3's strips (physical 1-4) all use a flat
# 10-LEDs-per-drawer spacing. cabinet1-right (physical strip 6) and cabinet4-left (physical
# strip 7) instead use an uneven 9/9/10/10/10/9/10/10/9 spacing -- different physical strip
# product/pitch, per Seth. cabinet2 and cabinet3 explicitly have matching left/right patterns;
# cabinet1 explicitly does not.
FLAT_10_PATTERN = [(0, 10), (10, 10), (20, 10), (30, 10), (40, 10), (50, 10), (60, 10), (70, 10), (80, 10)]
UNEVEN_9_10_PATTERN = [(0, 9), (9, 9), (18, 10), (28, 10), (38, 10), (48, 9), (57, 10), (67, 10), (77, 9)]

# (container number, first drawer number in that cabinet, [(logical strip name, pattern), ...])
# Strip names must match led-controller/pi/strip_map.json's keys on the Pi side.
CABINETS = [
    (38, 1, [("cabinet1-left", FLAT_10_PATTERN), ("cabinet1-right", UNEVEN_9_10_PATTERN)]),
    (39, 10, [("cabinet2-left", FLAT_10_PATTERN), ("cabinet2-right", FLAT_10_PATTERN)]),
    (40, 19, [("cabinet3-left", FLAT_10_PATTERN), ("cabinet3-right", FLAT_10_PATTERN)]),
    (119, 28, [("cabinet4-left", UNEVEN_9_10_PATTERN)]),
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
