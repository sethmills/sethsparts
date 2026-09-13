"""Record the site's own settings, and treat an already-in-use install as set up.

One migration, two audiences:

* **An install that already has data** — Seth's, live since September — has been in
  use with no SiteSettings row and must never be shown the setup wizard: it is
  already set up. This creates the row holding the values that install has been
  effectively running with, and marks setup complete.

* **A brand-new install** runs every migration against an empty database, sees no
  parts, and is left alone. No row means setup is outstanding, which is precisely
  what sends a first-time user to the wizard.

Whether any parts exist is the honest test. A database with parts in it has an owner
who has been using the app; any other signal (a timestamp, a flag in a settings
file) would either mark fresh installs as done or start nagging live ones.
"""
from django.db import migrations
from django.utils import timezone


def configure_existing_install(apps, schema_editor):
    Part = apps.get_model("inventory", "Part")
    SiteSettings = apps.get_model("inventory", "SiteSettings")

    if not Part.objects.exists():
        # Empty database: a fresh clone. Leave it unconfigured so setup runs.
        return

    if SiteSettings.objects.exists():
        # Already configured, possibly by hand. Never overwrite a real answer.
        return

    SiteSettings.objects.create(
        site_name="Seth's Parts",
        timezone="Europe/London",
        country="GB",
        unit_system="metric",
        # Marked complete deliberately: this install has been in daily use for
        # months, and sending its owner through a first-run wizard would be nonsense.
        setup_completed_at=timezone.now(),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0015_sitesettings_part_default_unit_stockitem_unit_and_more"),
    ]

    operations = [
        # Reverse is a no-op on purpose. Rolling this back would delete a live
        # owner's site name and timezone, which is data loss dressed up as a
        # schema rollback.
        migrations.RunPython(configure_existing_install, migrations.RunPython.noop),
    ]
