from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Container, Drawer

# Physical reality (per Seth): the 3 existing parts-cabinet containers hold one
# continuous drawer numbering 1-27 (a=1-9, b=10-18, c=19-27), not per-container
# "drawer a1"-style labels. Two new cabinets continue that same numbering.
LETTER_TO_CONTAINER_NUMBER = {"a": 38, "b": 39, "c": 40}
NEW_CABINETS = [
    {"drawer_count": 9, "start": 28, "name": "Cabinet 4"},
    {"drawer_count": 5, "start": 37, "name": "Cabinet 5"},
]


class Command(BaseCommand):
    help = "Relabel the 3 existing parts-cabinet drawers to the real 1-27 numbering and add 2 new cabinets (28-41)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        with transaction.atomic():
            for letter, container_number in LETTER_TO_CONTAINER_NUMBER.items():
                container = Container.objects.get(number=container_number)
                old_type = container.container_type
                container.container_type = "cabinet"
                offset = {"a": 0, "b": 9, "c": 18}[letter]
                for i in range(1, 10):
                    drawer = Drawer.objects.get(container=container, label=f"drawer {letter}{i}")
                    new_number = offset + i
                    new_label = f"Drawer {new_number}"
                    self.stdout.write(f"{container} : {drawer.label!r} -> {new_label!r}")
                    drawer.label = new_label
                    if not dry_run:
                        drawer.save(update_fields=["label"])
                container.notes = f"Parts cabinet — drawers {offset + 1}-{offset + 9} of 41"
                self.stdout.write(f"{container} container_type: {old_type!r} -> 'cabinet'")
                if not dry_run:
                    container.save(update_fields=["container_type", "notes"])

            next_number = (Container.objects.order_by("-number").first().number or 0) + 1
            for spec in NEW_CABINETS:
                start, count, name = spec["start"], spec["drawer_count"], spec["name"]
                end = start + count - 1
                self.stdout.write(f"New container #{next_number} ({name}): drawers {start}-{end}")
                if not dry_run:
                    container = Container.objects.create(
                        number=next_number,
                        name=name,
                        container_type="cabinet",
                        notes=f"Parts cabinet — drawers {start}-{end} of 41",
                    )
                    for n in range(start, end + 1):
                        Drawer.objects.create(container=container, label=f"Drawer {n}")
                next_number += 1

            if dry_run:
                self.stdout.write(self.style.WARNING("Dry run — no changes written."))
