"""Turn the reference library's categories into something the owner controls.

The categories were a hardcoded choices list — four shelves chosen by whoever built
the app. That made the reference section editable in its contents but not in its
shape: you could add a document, but only under Raspberry Pi, Arduino, Electronics or
3D printing. This converts them to rows, so an owner can rename, reorder, add and
remove them, and repoints every existing document at its category row.

Django cannot generate this migration for you, because a CharField cannot become a
ForeignKey in one step. The order below is the point: add the foreign key, populate
it from the old string, and only then drop the string column.
"""
import django.db.models.deletion
from django.db import migrations, models


def forwards(apps, schema_editor):
    ReferenceCategory = apps.get_model("inventory", "ReferenceCategory")
    ReferenceDoc = apps.get_model("inventory", "ReferenceDoc")

    # The four shelves that previously existed only as constants. Created in their
    # original order so an existing library looks exactly as it did before.
    defaults = [
        ("raspberry_pi", "Raspberry Pi", 10),
        ("arduino", "Arduino", 20),
        ("electronics", "Electronics reference", 30),
        ("3d_printing", "3D printing", 40),
    ]

    by_key = {}
    for key, name, order in defaults:
        category, _ = ReferenceCategory.objects.get_or_create(
            key=key, defaults={"name": name, "order": order}
        )
        by_key[key] = category

    for doc in ReferenceDoc.objects.all():
        category = by_key.get(doc.category)
        if category is None:
            # Only reachable if someone edited the database by hand. Give the stray
            # value its own shelf rather than silently dropping the document.
            key = doc.category or "uncategorised"
            category, _ = ReferenceCategory.objects.get_or_create(
                key=key, defaults={"name": doc.category or "Uncategorised", "order": 100}
            )
            by_key[key] = category
        doc.category_new_id = category.pk
        doc.save(update_fields=["category_new"])


def backwards(apps, schema_editor):
    """Put the string keys back, so this can be reversed without losing the link.

    Note this cannot restore a category somebody created after the migration — the
    old schema only had room for four known values. Reversing is for rolling back a
    deploy, not for undoing real use.
    """
    ReferenceDoc = apps.get_model("inventory", "ReferenceDoc")
    for doc in ReferenceDoc.objects.select_related("category_new"):
        doc.category = doc.category_new.key if doc.category_new else ""
        doc.save(update_fields=["category"])


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0017_sitesettings_label_printer_key_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReferenceCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                (
                    "key",
                    models.SlugField(
                        help_text="Stable identifier used in links. Leave it alone once set — changing it changes URLs.",
                        max_length=40,
                        unique=True,
                    ),
                ),
                ("order", models.PositiveIntegerField(default=100, help_text="Lower sorts first.")),
            ],
            options={
                "verbose_name": "reference category",
                "verbose_name_plural": "reference categories",
                "ordering": ["order", "name"],
            },
        ),
        # Nullable only for as long as it takes to populate it from the old column.
        migrations.AddField(
            model_name="referencedoc",
            name="category_new",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="docs",
                to="inventory.referencecategory",
                help_text="Which shelf this sits on.",
            ),
        ),
        migrations.RunPython(forwards, backwards),
        # Give the old column a default *before* dropping it. This is not cosmetic:
        # reversing RemoveField re-adds `category` to a table that already has
        # documents in it, and a NOT NULL column with no default cannot be added to a
        # populated table — the rollback fails with a constraint error. Carrying a
        # default in the recorded field state is what makes 0018 reversible.
        migrations.AlterField(
            model_name="referencedoc",
            name="category",
            field=models.CharField(
                choices=[
                    ("raspberry_pi", "Raspberry Pi"),
                    ("arduino", "Arduino"),
                    ("electronics", "Electronics reference"),
                    ("3d_printing", "3D printing"),
                ],
                default="electronics",
                max_length=20,
            ),
        ),
        migrations.RemoveField(model_name="referencedoc", name="category"),
        migrations.RenameField(
            model_name="referencedoc",
            old_name="category_new",
            new_name="category",
        ),
        # Every row was populated above, so this can be tightened. It also fails loudly
        # if one was somehow missed, rather than leaving documents with no shelf.
        migrations.AlterField(
            model_name="referencedoc",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="docs",
                to="inventory.referencecategory",
                help_text="Which shelf this sits on.",
            ),
        ),
    ]
