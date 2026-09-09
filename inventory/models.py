from django.db import models


class Location(models.Model):
    """Informational provenance only (the spreadsheet's original 'Room') — not used for barcode lookup."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Container(models.Model):
    number = models.PositiveIntegerField(unique=True, help_text="Original 'Box' number from the spreadsheet")
    name = models.CharField(max_length=200, blank=True)
    container_type = models.CharField(max_length=100, help_text="e.g. 'large black tote', 'custom', 'cabinets'")
    barcode_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    dimensions = models.CharField(max_length=100, blank=True)
    location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL, related_name="containers")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        label = self.name or self.container_type
        return f"#{self.number} ({label})"


class Drawer(models.Model):
    """Only created for containers actually subdivided by drawer (the parts cabinets)."""

    container = models.ForeignKey(Container, on_delete=models.CASCADE, related_name="drawers")
    label = models.CharField(max_length=100, help_text="e.g. 'drawer b2'")
    barcode_id = models.CharField(max_length=100, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["container__number", "label"]
        unique_together = [("container", "label")]

    def __str__(self):
        return f"{self.container} / {self.label}"


class DrawerLedSegment(models.Model):
    """One "find the part" WS2812B LED range for a drawer (Phase 8 backlog item). A drawer can
    have more than one -- each cabinet has a left-side and right-side strip covering the same
    drawer range, and locating a drawer should light up its segment on both."""

    drawer = models.ForeignKey(Drawer, on_delete=models.CASCADE, related_name="led_segments")
    led_strip = models.CharField(max_length=100, help_text="Logical WS2812B strip name/ID, e.g. 'cabinet1-left'")
    led_start_index = models.PositiveIntegerField(help_text="First LED index (0-based) for this drawer on that strip")
    led_count = models.PositiveIntegerField(default=1, help_text="Number of LEDs marking this drawer on this strip")

    class Meta:
        ordering = ["drawer", "led_strip"]

    def __str__(self):
        return f"{self.drawer} @ {self.led_strip}[{self.led_start_index}:{self.led_start_index + self.led_count}]"


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Part(models.Model):
    ENRICHMENT_NOT_NEEDED = "not_needed"
    ENRICHMENT_PENDING = "pending"
    ENRICHMENT_NEEDS_CLARIFICATION = "needs_clarification"
    ENRICHMENT_NEEDS_REVIEW = "needs_review"
    ENRICHMENT_DONE = "done"
    ENRICHMENT_CHOICES = [
        (ENRICHMENT_NOT_NEEDED, "Not needed"),
        (ENRICHMENT_PENDING, "Pending"),
        (ENRICHMENT_NEEDS_CLARIFICATION, "Needs clarification (ask Seth)"),
        (ENRICHMENT_NEEDS_REVIEW, "Needs review"),
        (ENRICHMENT_DONE, "Done"),
    ]

    name = models.CharField(max_length=300)
    normalized_name = models.CharField(max_length=300, db_index=True, editable=False)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="parts")
    is_electronic = models.BooleanField(default=False)
    manufacturer = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    min_quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Reorder threshold (Phase 5)")
    reorder_url = models.URLField(blank=True)
    datasheet_url = models.URLField(blank=True, help_text="Quick reference link — not a locally cached copy, see Attachments for that")
    enrichment_status = models.CharField(max_length=20, choices=ENRICHMENT_CHOICES, default=ENRICHMENT_NOT_NEEDED)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.normalized_name = self.name.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Attachment(models.Model):
    DATASHEET = "datasheet"
    PINOUT = "pinout"
    WIRING = "wiring"
    PRODUCT_PAGE = "product_page"
    IMAGE = "image"
    DOC_TYPE_CHOICES = [
        (DATASHEET, "Datasheet"),
        (PINOUT, "Pinout"),
        (WIRING, "Wiring diagram"),
        (PRODUCT_PAGE, "Product page (archived)"),
        (IMAGE, "Image"),
    ]

    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="attachments/%Y/")
    doc_type = models.CharField(max_length=20, choices=DOC_TYPE_CHOICES)
    source_url = models.URLField(blank=True, help_text="Where this was originally fetched from")
    title = models.CharField(max_length=200, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["part", "doc_type"]

    def __str__(self):
        return f"{self.part.name} — {self.get_doc_type_display()}"


class Project(models.Model):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    STATUS_CHOICES = [(ACTIVE, "Active"), (COMPLETED, "Completed"), (ARCHIVED, "Archived")]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def latest_revision(self):
        return self.revisions.order_by("-version").first()


class BOMRevision(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveIntegerField(editable=False, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project", "-version"]
        unique_together = [("project", "version")]

    def save(self, *args, **kwargs):
        if not self.version:
            last = BOMRevision.objects.filter(project=self.project).order_by("-version").first()
            self.version = (last.version + 1) if last else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project.name} rev {self.version}"


class BOMLine(models.Model):
    revision = models.ForeignKey(BOMRevision, on_delete=models.CASCADE, related_name="lines")
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="bom_lines")
    quantity_required = models.PositiveIntegerField()

    class Meta:
        ordering = ["part__name"]
        unique_together = [("revision", "part")]

    def __str__(self):
        return f"{self.part.name} x{self.quantity_required}"


class Build(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="builds")
    revision = models.ForeignKey(BOMRevision, on_delete=models.PROTECT, related_name="builds")
    quantity_built = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    built_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-built_at"]

    def __str__(self):
        return f"{self.project.name} build x{self.quantity_built} @ {self.built_at:%Y-%m-%d %H:%M}"


class BuildConsumption(models.Model):
    """Actual stock deducted for one BOM line during a Build — may be less than requested if stock ran short."""

    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="consumptions")
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="build_consumptions")
    quantity_requested = models.PositiveIntegerField()
    quantity_consumed = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.part.name}: {self.quantity_consumed}/{self.quantity_requested}"

    @property
    def short(self):
        return self.quantity_consumed < self.quantity_requested


class ReferenceDoc(models.Model):
    RASPBERRY_PI = "raspberry_pi"
    ARDUINO = "arduino"
    ELECTRONICS = "electronics"
    PRINTING_3D = "3d_printing"
    CATEGORY_CHOICES = [
        (RASPBERRY_PI, "Raspberry Pi"),
        (ARDUINO, "Arduino"),
        (ELECTRONICS, "Electronics reference"),
        (PRINTING_3D, "3D printing"),
    ]

    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.TextField(blank=True)
    external_url = models.URLField(blank=True, help_text="Canonical/live source, always shown as a link out")
    file = models.FileField(upload_to="reference/%Y/", blank=True, null=True, help_text="Locally cached copy (image/PDF) so this survives even if the source goes away")
    order = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["category", "order", "title"]

    def __str__(self):
        return self.title


class StockItem(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="stock_items")
    container = models.ForeignKey(Container, on_delete=models.CASCADE, related_name="stock_items")
    drawer = models.ForeignKey(Drawer, null=True, blank=True, on_delete=models.CASCADE, related_name="stock_items")
    quantity = models.IntegerField(null=True, blank=True)
    quantity_raw = models.CharField(max_length=50, blank=True, help_text="Original spreadsheet value, e.g. '10 aprox'")
    source_notes = models.CharField(max_length=300, blank=True, help_text="Non-drawer freeform notes from the spreadsheet")
    bin_number = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Which of the drawer's 16 bins (1-16, 4 rows of 4) this sits in, if known",
    )

    class Meta:
        ordering = ["container__number", "drawer__label", "part__name"]

    @property
    def bin_row(self):
        """Which of the 4 rows (1-4) this bin is in, or None if bin_number isn't set."""
        if self.bin_number is None:
            return None
        return ((self.bin_number - 1) // 4) + 1

    def __str__(self):
        where = self.drawer or self.container
        return f"{self.part.name} x{self.quantity_raw or self.quantity} @ {where}"
