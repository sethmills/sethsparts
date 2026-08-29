from django.core.management.base import BaseCommand

from inventory.models import Category, Part

# Words that indicate a specific, identifiable electronic product/module worth
# web research (product page, pinout, datasheet) — even if a generic-sounding
# word also appears in the name.
SPECIFIC_KEYWORDS = [
    "arduino", "raspberry", "raspi", "pi zero", "pi 4", "pi 400", "beaglebone",
    "esp32", "esp8266", "rp2040", "pico", "witty pi", "ftdi", "teensy", "stm32",
    "nodemcu", "wemos", "attiny", "atmega", "jetson", "nrf52", "nrf51", "cc3000",
    "cc3200", "mpr121", "neopixel", "sonos", "nixie", "oled", "tft", "lcd module",
    "stepper motor", "servo controller", "motor driver", "motor hat", "relay board",
    "relay module", "logic analyzer", "oscilloscope", "multimeter", "soldering station",
    "sensor module", "gps module", "lora", "bluetooth module", "wifi module",
    "camera module", "voltage regulator module", "breakout board", "shield", "hat",
    "bonnet", "featherwing", "feather", "microcontroller", "development board",
    "dev board", "amiga keyboard", "synth", "audio interface", "midi interface",
]

# Words that mean "generic bulk hardware/supply" — never worth an individual
# web lookup regardless of what else is in the name.
GENERIC_SKIP_KEYWORDS = [
    "assorted", "misc ", "spool", "guage", "gauge", " ft ", "feet", "screws",
    "screw ", "nuts", "bolts", "washer", "zip tie", "heat shrink", "tape", "glue",
    "probe", "alligator", "aligator", "jumper wire", "jumper cable", "hookup wire",
    "hook up wire", "ribbon cable", "standoff", "hardware kit", "fastener",
    "connectors", "connector ", "wago", "molex", "terminal", "header",
]


class Command(BaseCommand):
    help = (
        "Classify every not-yet-enriched Part into: pending (autonomous research candidate), "
        "needs_clarification (ambiguous label — needs Seth to disambiguate), or leaves it "
        "not_needed (generic bulk hardware)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--output", type=str, help="Write the needs_clarification list to this text file")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        electronics = Category.objects.filter(name="Electronics").first()

        candidates = Part.objects.filter(enrichment_status=Part.ENRICHMENT_NOT_NEEDED).filter(
            category=electronics
        ) | Part.objects.filter(enrichment_status=Part.ENRICHMENT_NOT_NEEDED, category__isnull=True)

        pending, needs_clarification, left_alone = [], [], []

        for part in candidates.distinct():
            name = part.name.lower()
            if any(kw in name for kw in SPECIFIC_KEYWORDS):
                pending.append(part)
            elif any(kw in name for kw in GENERIC_SKIP_KEYWORDS):
                left_alone.append(part)
            elif part.category_id == getattr(electronics, "id", None):
                # In the Electronics bucket, not obviously generic, but not confidently
                # identifiable from the label alone either — a candidate for the
                # drawer-by-drawer disambiguation workstream.
                needs_clarification.append(part)
            else:
                left_alone.append(part)

        self.stdout.write(f"pending (autonomous research): {len(pending)}")
        self.stdout.write(f"needs_clarification (ask Seth): {len(needs_clarification)}")
        self.stdout.write(f"left alone (generic, no action): {len(left_alone)}")

        if not dry_run:
            for part in pending:
                if part.category_id is None:
                    part.category = electronics
                    part.is_electronic = True
                part.enrichment_status = Part.ENRICHMENT_PENDING
                part.save()
            for part in needs_clarification:
                part.enrichment_status = Part.ENRICHMENT_NEEDS_CLARIFICATION
                part.save()

        output_path = options.get("output")
        if output_path:
            with open(output_path, "w") as f:
                f.write("Parts needing Seth's clarification before enrichment can help\n")
                f.write("=" * 60 + "\n\n")
                for part in sorted(needs_clarification, key=lambda p: p.name):
                    f.write(f"[{part.id}] {part.name}\n")
            self.stdout.write(f"Wrote needs_clarification list to {output_path}")
