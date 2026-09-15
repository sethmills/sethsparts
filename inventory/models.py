import secrets

from django.db import models

from .community import PIN_VERSION, generate_keypair
from .units import DEFAULT_UNIT, STOCK_UNIT_CHOICES, UNIT_SYSTEMS, format_quantity, symbol as unit_symbol


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


class LedStrip(models.Model):
    """A physical LED strip, and which channel it is wired to.

    The app already knows which drawer an LED range belongs to (see
    `DrawerLedSegment`), but it cannot know which strip is plugged into which output
    on the Scorpio — that is physical wiring, visible only to whoever is holding the
    strip and the board. Rather than guess, the owner records it here and the setup
    wizard pushes it to the Pi, because that is where it has to live for /locate to
    work at all.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Matches the strip name used in that drawer's LED mappings, e.g. cabinet1-left",
    )
    channel = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="The Scorpio output this strip is plugged into, 0-7",
    )

    class Meta:
        ordering = ["channel", "name"]
        verbose_name = "LED strip"

    def __str__(self):
        return f"{self.name} (channel {self.channel})"

    @property
    def is_wired(self) -> bool:
        """Whether anything is plugged into this strip's channel.

        A strip with no channel is one the owner has named but not yet plugged in,
        which is a normal halfway state while wiring a cabinet.
        """
        return self.channel is not None


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_shareable = models.BooleanField(
        default=False,
        help_text=(
            "Visible to connected workshops via community search. Off by default — "
            "sharing is opted into per category, and a part with no category is never shareable."
        ),
    )

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
        (ENRICHMENT_NEEDS_CLARIFICATION, "Needs clarification"),
        (ENRICHMENT_NEEDS_REVIEW, "Needs review"),
        (ENRICHMENT_DONE, "Done"),
    ]

    name = models.CharField(max_length=300)
    normalized_name = models.CharField(max_length=300, db_index=True, editable=False)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="parts")
    is_electronic = models.BooleanField(default=False)
    default_unit = models.CharField(
        max_length=8,
        choices=STOCK_UNIT_CHOICES,
        default=DEFAULT_UNIT,
        help_text=(
            "What this part's quantities count. Leave as 'each' for countable parts; "
            "set metres, grams and so on for wire, tubing, filament and solder."
        ),
    )
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


class ArchivableDocument(models.Model):
    """Shared state for anything that keeps a local copy of an external document.

    Abstract, so each concrete user still gets its own table. It exists for two
    reasons: the archiving state cannot drift between part attachments and reference
    documents, and a third kind of document can be added later by inheriting rather
    than by remembering to re-add four fields.

    The failure field is the important one. A reference whose source is behind a login
    wall is worth keeping *as a link* — it just has to say so, rather than looking
    like a cached document that quietly isn't there.
    """

    archived_at = models.DateTimeField(
        null=True, blank=True, help_text="When a local copy was last saved successfully."
    )
    archive_attempted_at = models.DateTimeField(
        null=True, blank=True, help_text="When archiving was last tried, successfully or not."
    )
    archive_content_type = models.CharField(
        max_length=100, blank=True, help_text="What the source actually served, e.g. application/pdf."
    )
    archive_error = models.CharField(
        max_length=300, blank=True, help_text="Why the last attempt failed, shown to the owner."
    )

    class Meta:
        abstract = True

    @property
    def is_archived(self) -> bool:
        return bool(self.file and self.archived_at)

    @property
    def archive_failed(self) -> bool:
        """Tried and failed — as opposed to never tried, which is a different thing."""
        return bool(self.archive_error) and not self.archived_at


class Attachment(ArchivableDocument):
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


class ReferenceCategory(models.Model):
    """A heading in the reference library.

    These used to be a hardcoded choices list, which quietly made the whole reference
    section the developer's rather than the owner's: you could add documents but never
    the shelf they sit on. Now it is a row, so references can be organised the way a
    particular workshop is arranged — "3D printing" is no use to someone who does
    woodwork or leatherwork, and "Electronics reference" is no use to someone who
    doesn't.
    """

    name = models.CharField(max_length=100)
    key = models.SlugField(
        max_length=40,
        unique=True,
        help_text="Stable identifier used in links. Leave it alone once set — changing it changes URLs.",
    )
    order = models.PositiveIntegerField(default=100, help_text="Lower sorts first.")

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "reference category"
        verbose_name_plural = "reference categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.key:
            from django.utils.text import slugify

            self.key = slugify(self.name)[:40] or "category"
        super().save(*args, **kwargs)


class ReferenceDoc(ArchivableDocument):
    """One reference: a pinout, a chart, a guide, a photo of a label.

    Deliberately free-form — a title, optional notes, an optional link out, an
    optional uploaded file, and a category the owner controls. Nothing here is
    specific to any one workshop, which is what lets an install start from the
    shipped starter set and then edit, extend or delete it freely.
    """

    title = models.CharField(max_length=200)
    category = models.ForeignKey(
        ReferenceCategory,
        on_delete=models.PROTECT,
        related_name="docs",
        help_text="Which shelf this sits on.",
    )
    description = models.TextField(blank=True)
    external_url = models.URLField(blank=True, help_text="Canonical/live source, always shown as a link out")
    file = models.FileField(upload_to="reference/%Y/", blank=True, null=True, help_text="Locally cached copy (image/PDF) so this survives even if the source goes away")
    order = models.PositiveIntegerField(default=100, help_text="Lower sorts first within its category.")

    class Meta:
        ordering = ["category__order", "order", "title"]

    @property
    def needs_archiving(self) -> bool:
        """Has a source link but no local copy of it.

        This is both the to-do list the archiving command works from and what the UI
        shows as "not archived yet" — the honest state of a link whose document was
        never fetched, or whose fetch failed.
        """
        return bool(self.external_url) and not self.file

    def __str__(self):
        return self.title


class Bin(models.Model):
    """One physical bin slot within a drawer (16 per drawer, 4 rows of 4) — distinct from
    StockItem.bin_number (which part sits in which bin). This exists so a physical barcode
    sticker on the bin itself can be scanned to identify "this drawer, this bin" directly,
    via the bulk bin-barcode scan flow. Only drawers 1-27 (cabinets 1-3) have bins — cabinet
    4 (drawers 28-36) holds oversized/different items with no bin subdivisions, per Seth."""

    drawer = models.ForeignKey(Drawer, on_delete=models.CASCADE, related_name="bins")
    bin_number = models.PositiveSmallIntegerField(help_text="1-16 (4 rows of 4)")
    barcode_id = models.CharField(max_length=100, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["drawer__container__number", "drawer__label", "bin_number"]
        unique_together = [("drawer", "bin_number")]

    @property
    def bin_row(self):
        return ((self.bin_number - 1) // 4) + 1

    @property
    def bin_column(self):
        return ((self.bin_number - 1) % 4) + 1

    def __str__(self):
        return f"{self.drawer} bin {self.bin_number}"


class SubBin(models.Model):
    """A small/medium sub-container within a Bin -- 0-4 of them, each with its own physical
    barcode. Discovered/added as Seth actually goes through each drawer's bins, not seeded
    up front like Bin (there's no fixed count)."""

    SMALL = "small"
    MEDIUM = "medium"
    SIZE_CHOICES = [(SMALL, "Small"), (MEDIUM, "Medium")]

    bin = models.ForeignKey(Bin, on_delete=models.CASCADE, related_name="sub_bins")
    position = models.PositiveSmallIntegerField(help_text="1-4 within the bin")
    size = models.CharField(max_length=10, choices=SIZE_CHOICES, default=SMALL)
    barcode_id = models.CharField(max_length=100, unique=True, null=True, blank=True)

    class Meta:
        ordering = ["bin", "position"]
        unique_together = [("bin", "position")]

    def __str__(self):
        return f"{self.bin} sub-bin {self.position} ({self.get_size_display()})"


class ContainerPhoto(models.Model):
    """A quick reference photo of a container's contents — for the moving-day intake flow
    (pack a box, snap a photo, move on) as well as any other container someone wants a
    picture of. Separate from Attachment (which is Part-scoped, for manufacturer docs)."""

    container = models.ForeignKey(Container, on_delete=models.CASCADE, related_name="photos")
    image = models.FileField(upload_to="container_photos/%Y/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"Photo of {self.container} ({self.uploaded_at:%Y-%m-%d})"


class IntakeNote(models.Model):
    """A quick, unstructured note about a container's contents — typed or voice-dictated —
    queued for Seth to review later and turn into real Part/StockItem entries. Deliberately
    not auto-parsed into structured data; this is just fast capture during a move.

    A note records *one* location, at the finest granularity known: a specific bin, a
    drawer, or a box/tote. The three fields are mutually exclusive at the leaf — pick a
    bin and the drawer is implied; pick a box and there is no drawer. `location` resolves
    the leaf so callers never have to remember the precedence."""

    VOICE = "voice"
    TYPED = "typed"
    SOURCE_CHOICES = [(VOICE, "Voice"), (TYPED, "Typed")]

    container = models.ForeignKey(
        Container, null=True, blank=True, on_delete=models.CASCADE, related_name="intake_notes",
        help_text="The box/tote this was captured against — the moving-day case.",
    )
    drawer = models.ForeignKey(
        Drawer, null=True, blank=True, on_delete=models.CASCADE, related_name="intake_notes",
        help_text="The cabinet drawer this belongs in, when it has a permanent home.",
    )
    bin = models.ForeignKey(
        Bin, null=True, blank=True, on_delete=models.CASCADE, related_name="intake_notes",
        help_text="The specific bin within a drawer, when known.",
    )
    text = models.TextField()
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=TYPED)
    reviewed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def location(self):
        """The most specific location this note was captured against, or None."""
        return self.bin or self.drawer or self.container

    def location_summary(self) -> str:
        return str(self.location) if self.location else "unassigned"

    def __str__(self):
        where = self.location or "(unassigned)"
        return f"{where}: {self.text[:50]}"


class ShoppingListItem(models.Model):
    """A part to buy on the next supply run, seeded from the reorder dashboard
    (parts below their min quantity). One entry per part — adding it again bumps
    the quantity rather than duplicating the row."""

    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="shopping_list_items")
    quantity = models.PositiveIntegerField(default=1)
    bought = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["bought", "part__name"]
        unique_together = [("part",)]

    def __str__(self):
        return f"{self.part.name} x{self.quantity}"


class StockItem(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="stock_items")
    container = models.ForeignKey(Container, on_delete=models.CASCADE, related_name="stock_items")
    drawer = models.ForeignKey(Drawer, null=True, blank=True, on_delete=models.CASCADE, related_name="stock_items")
    quantity = models.IntegerField(null=True, blank=True)
    quantity_raw = models.CharField(max_length=50, blank=True, help_text="Original spreadsheet value, e.g. '10 aprox'")
    unit = models.CharField(
        max_length=8,
        choices=STOCK_UNIT_CHOICES,
        blank=True,
        default="",
        help_text=(
            "Overrides the part's unit for just this location. Blank means use the part's, "
            "which is what every pre-existing row gets — so old data reads exactly as before."
        ),
    )
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

    @property
    def bin_column(self):
        """Which of the 4 columns (1-4) this bin is in, or None if bin_number isn't set."""
        if self.bin_number is None:
            return None
        return ((self.bin_number - 1) % 4) + 1

    @property
    def effective_unit(self) -> str:
        """This row's unit: its own if set, otherwise the part's, otherwise 'each'.

        Blank means inherit, which is deliberately what the migration leaves on
        every existing row — so nothing that was counted as a plain number starts
        claiming to be metres.
        """
        return self.unit or (self.part.default_unit if self.part_id else "") or DEFAULT_UNIT

    @property
    def quantity_display(self) -> str:
        """The quantity with its unit, e.g. '5 m'. Plain counts render as just '5'."""
        return format_quantity(self.quantity, self.effective_unit)

    @property
    def quantity_label(self) -> str:
        """What to show for this row in a list.

        Preserves the display that was already there — including the original
        spreadsheet text for rows whose quantity was never parsed into a number — and
        only appends a unit when there is a real one. Every row in production is
        'each', so in practice this renders exactly as it always did.
        """
        base = self.quantity_raw or (str(self.quantity) if self.quantity is not None else "unknown")
        sym = unit_symbol(self.effective_unit)
        return f"{base} {sym}".strip() if sym else base

    @property
    def quantity_spoken(self) -> str:
        """For the voice API. Keeps that endpoint's existing wording exactly —
        including "unknown qty", which reads better aloud than "unknown" — and
        appends the unit only when there is one.
        """
        base = self.quantity_raw or (str(self.quantity) if self.quantity is not None else "unknown qty")
        sym = unit_symbol(self.effective_unit)
        return f"{base} {sym}".strip() if sym else base

    def __str__(self):
        where = self.drawer or self.container
        return f"{self.part.name} x{self.quantity_raw or self.quantity} @ {where}"


# --- Community: identity, peers, and the map ----------------------------------
#
# Three things are deliberately independent here, because collapsing them is how
# a privacy model breaks:
#
#   1. Whether this instance appears on other people's maps  (CommunityProfile.discoverable)
#   2. Whether a given workshop can SEARCH this one's parts   (Peer.shares_parts)
#   3. Whether a given workshop exchanges MAP PINS with it    (Peer.exchanges_pins)
#
# (1) is about strangers; (2) and (3) are per-person. Being visible on the map never
# implies being searchable, and being connected for pins never grants inventory
# access. See docs/PLAN_community_sharing.md.


def new_api_key() -> str:
    """A per-peer API credential. Used for authenticating the peer's requests.

    Distinct from the peer's signing key on purpose: this one is a shared secret
    between exactly two instances (fine for request auth), while pin signatures are
    public-key so that any relaying instance can verify them without a secret.
    """
    return secrets.token_urlsafe(32)


class Peer(models.Model):
    """Another workshop's instance that this one is connected to.

    The two capabilities are separate flags, not a type, so the same person can be
    a pin neighbour without ever seeing the inventory — which is exactly what the
    default seed connection needs to be.
    """

    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    STATUS_CHOICES = [
        (PENDING, "Pending — asked, not yet accepted"),
        (ACTIVE, "Active"),
        (REVOKED, "Revoked"),
    ]

    name = models.CharField(max_length=200, help_text="e.g. \"Dad's workshop\"")
    base_url = models.URLField(help_text="Their instance's public address")
    public_key = models.CharField(
        max_length=64, blank=True,
        help_text="Their Ed25519 signing key — their stable identity, used to verify the pins they publish",
    )
    inbound_api_key = models.CharField(
        max_length=64, unique=True, default=new_api_key,
        help_text="The credential we issued to them, checked on requests they make to us",
    )
    outbound_api_key = models.CharField(
        max_length=64, blank=True,
        help_text="The credential they issued to us, sent when we query them",
    )
    is_seed = models.BooleanField(
        default=False,
        help_text="The maintainer's instance, connected by default so a new install has a way onto the map",
    )
    exchanges_pins = models.BooleanField(
        default=True,
        help_text="Exchange anonymous map pins. Never grants access to inventory.",
    )
    shares_parts = models.BooleanField(
        default=False,
        help_text="May search categories marked shareable. Off until opted in for this specific person.",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    contact_note = models.CharField(
        max_length=300, blank=True, help_text="How to reach them, e.g. an email. Shown on search results."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    blocked = models.BooleanField(
        default=False,
        help_text="Blocked workshops are fully cut off — no messages, no search, no pins — and cannot reconnect until unblocked.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    @property
    def is_active(self) -> bool:
        """Only an active peer is queried, and only an active peer's key is accepted."""
        return self.status == self.ACTIVE


class PairingCode(models.Model):
    """A one-time invite a workshop shows so another can connect to it.

    Single use and short-lived: the code is a bearer credential on its own, so its
    protection is the expiry and the single use, not its length. Eight characters of
    base32 (Crockford, so no ambiguous 0/O or 1/I/L) is ~40 bits, which is far past
    guessable inside a 24-hour window that closes after one successful claim.
    """

    ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
    LENGTH = 8
    GROUPS = (4, 4)
    LIFETIME_HOURS = 24

    code = models.CharField(max_length=16, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.ForeignKey(
        Peer, null=True, blank=True, on_delete=models.SET_NULL, related_name="claimed_codes"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.display

    @classmethod
    def issue(cls, now=None):
        from datetime import timedelta

        from django.utils import timezone

        now = now or timezone.now()
        raw = "".join(secrets.choice(cls.ALPHABET) for _ in range(cls.LENGTH))
        return cls.objects.create(code=raw, expires_at=now + timedelta(hours=cls.LIFETIME_HOURS))

    @property
    def display(self) -> str:
        """Grouped for reading aloud: K7F2-9QX3."""
        a, b = self.GROUPS
        return f"{self.code[:a]}-{self.code[a:a + b]}"

    def is_usable(self, now=None) -> bool:
        """Unclaimed and unexpired. Checked with the same care as the token compare."""
        from django.utils import timezone

        now = now or timezone.now()
        return self.claimed_at is None and now < self.expires_at

    @classmethod
    def parse_display(cls, text: str) -> str:
        """Accept 'K7F2-9QX3', 'k7f29qx3', 'K7F2 9QX3' — people type it how they like."""
        cleaned = "".join(c for c in (text or "").upper() if c.isalnum())
        # Crockford's whole point: characters that look alike are folded together.
        return cleaned.replace("O", "0").replace("I", "1").replace("L", "1")


class PeerSearchLog(models.Model):
    """One inbound search from a peer.

    Exists so an owner can see what a connected workshop has actually been looking
    for, instead of having to take it on trust. Without this, "your peers can only
    search what you shared" is an assertion; with it, it is checkable.
    """

    peer = models.ForeignKey(Peer, on_delete=models.CASCADE, related_name="searches")
    query = models.CharField(max_length=200)
    result_count = models.PositiveIntegerField(default=0)
    searched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-searched_at"]

    def __str__(self):
        return f"{self.peer.name}: {self.query!r} -> {self.result_count}"


class Message(models.Model):
    """A message between this instance and one connected workshop.

    One row per message, in either direction. `direction` records whether the owner
    sent it (`outbound`) or a peer sent it (`inbound`). `remote_id` is the *sender's*
    id for the message — it is what makes delivery idempotent, so a retry of a push
    that actually reached the peer the first time (but whose response was lost) cannot
    be stored twice at the far end.
    """

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    DIRECTION_CHOICES = [(INBOUND, "Received"), (OUTBOUND, "Sent")]

    peer = models.ForeignKey(Peer, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)
    body = models.TextField()
    remote_id = models.CharField(max_length=64, blank=True)
    delivered = models.BooleanField(default=True)
    read = models.BooleanField(default=False)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sent_at"]

    def __str__(self):
        who = "from" if self.direction == self.INBOUND else "to"
        return f"{who} {self.peer.name}: {self.body[:40]}"


class CommunityIdentity(models.Model):
    """This instance's own keypair — its stable identity on the network.

    Singleton: exactly one row, created with a fresh keypair on first use.

    The private key lives in the database rather than in `.env` because it is
    application data generated at runtime, not operator-supplied configuration.
    That is consistent with this app's existing trust boundary — the database
    already holds the whole inventory — but it does mean two rules hold:
    **never render it, never serialise it into an API response, and never log it.**
    The test suite asserts all three.
    """

    public_key = models.CharField(max_length=64, unique=True)
    private_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "community identity"

    def __str__(self):
        return f"this instance ({self.public_key[:12]}…)"

    @classmethod
    def load(cls):
        """The one identity row, generating the keypair on first use.

        Tolerates a race between two workers starting at once: the unique
        constraint on `public_key` means the loser re-reads rather than crashing.
        """
        existing = cls.objects.first()
        if existing is not None:
            return existing
        private_hex, public_hex = generate_keypair()
        try:
            return cls.objects.create(private_key=private_hex, public_key=public_hex)
        except Exception:
            return cls.objects.get(public_key=public_hex)


class CommunityProfile(models.Model):
    """This instance's public presence: whether it appears on maps, and where.

    Singleton, same as CommunityIdentity.

    **Location is stored only at postcode-AREA granularity.** For the UK that means
    the outcode (``SW1A``), never the full postcode — a full UK postcode identifies
    roughly fifteen households, so publishing one publishes a doorstep. The
    geocoder returns that centroid directly, which is why there is no rounding or
    grid-snapping step anywhere in this feature.

    Note what is *not* stored: the postcode the owner typed. Keeping the input
    around would mean a serialisation mistake could leak it, and nothing needs it
    once the centroid exists.
    """

    OUTCODE = "outcode"
    ZIP = "zip"
    NOMINATIM = "nominatim"
    MANUAL = "manual"
    SOURCE_CHOICES = [
        (OUTCODE, "UK outcode"),
        (ZIP, "US ZIP"),
        (NOMINATIM, "Postcode via OpenStreetMap"),
        (MANUAL, "Entered by hand"),
    ]

    discoverable = models.BooleanField(
        default=False,
        help_text=(
            "Appear as an anonymous pin on other workshops' maps. Off by default. "
            "Independent of who can search this instance — see Peer.shares_parts."
        ),
    )
    display_name = models.CharField(
        max_length=100, blank=True,
        help_text="Optional. The map shows anonymous pins, so this is not published by default.",
    )
    # Note there is no country field here. Which country the owner is in is a fact
    # about the install, so it lives on SiteSettings; duplicating it here would mean
    # two places to update and one of them eventually going stale.
    location_lat = models.FloatField(null=True, blank=True)
    location_lon = models.FloatField(null=True, blank=True)
    location_source = models.CharField(max_length=20, choices=SOURCE_CHOICES, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "community profile"

    def __str__(self):
        return "discoverable" if self.discoverable else "private"

    @classmethod
    def load(cls):
        obj = cls.objects.first()
        return obj if obj is not None else cls.objects.create()

    @property
    def has_location(self) -> bool:
        return self.location_lat is not None and self.location_lon is not None

    @property
    def can_publish(self) -> bool:
        """Both halves are required before a pin may go out, and both are opt-ins."""
        return self.discoverable and self.has_location


class KnownPin(models.Model):
    """A pin heard from another workshop.

    Keyed by the publishing instance's public key, because that *is* its identity:
    one row per workshop, holding only its newest entry. Everything here is a copy of
    signed material, which is why a pin can be passed on to a workshop that has never
    met the one that published it.

    **A removed pin keeps its row, with nothing in it.** When an owner opts out they
    publish a newer, signed "I'm gone" entry, and every node holding their pin deletes
    the location. Keeping the key's newest timestamp is what stops an *older* pin —
    relayed again by someone whose copy is stale — from resurrecting a workshop that
    has asked to be forgotten. Coordinates are cleared rather than kept hidden, so
    there is nothing left on disk to leak; what remains is a timestamp, a signature and
    a boolean.

    Note what is deliberately absent: which neighbour this pin arrived from. The plan
    forbids disclosing that (watching who receives what would map the social graph),
    and the strongest version of not disclosing it is not storing it.
    """

    public_key = models.CharField(
        max_length=64, unique=True, help_text="The publishing instance's Ed25519 key — also its identity."
    )
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    country = models.CharField(max_length=2, blank=True)
    name = models.CharField(
        max_length=100, blank=True, help_text="Empty for an anonymous pin, which is the default."
    )
    gone = models.BooleanField(
        default=False, help_text="Set by a signed opt-out entry. The location is deleted when this is set."
    )
    signed_at = models.DateTimeField(
        help_text="The timestamp from inside the signed bytes — the owner's own clock, not ours."
    )
    signature = models.CharField(max_length=128)
    pin_version = models.PositiveSmallIntegerField(
        default=PIN_VERSION,
        help_text=(
            "Which version of the pin format this entry was signed as. It is inside the "
            "signed bytes, so re-serving the entry under a different number would "
            "invalidate its own signature."
        ),
    )
    hops = models.PositiveSmallIntegerField(
        default=0, help_text="How many relays away the origin is. Not signed — a cost and loop guard, not a fact."
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-signed_at"]
        verbose_name = "known pin"

    def __str__(self):
        state = "gone" if self.gone else f"{self.lat}, {self.lon}"
        return f"pin {self.public_key[:12]}… ({state})"

    @property
    def is_placeholder(self) -> bool:
        """True for the kept shell of an opted-out pin: no location left at all."""
        return self.gone and self.lat is None and self.lon is None


class SiteSettings(models.Model):
    """Singleton: what this instance is called and how it behaves.

    Every field here is one that used to be hardcoded to Seth's own setup — the app
    name in thirty templates, Europe/London, and 'each' as the only unit a quantity
    could be. A clone would have shown someone else's name and timestamps in the
    wrong timezone, which is exactly why this is a row in the database rather than a
    constant in settings.py: these are the *owner's* answers, not the developer's.

    `setup_completed_at` is the switch the setup wizard hangs off. Null means the
    instance has not been set up, which is what sends a browser to the wizard.
    """

    site_name = models.CharField(
        max_length=60,
        default="My Parts",
        help_text="Shown in the header, every page title, and the admin.",
    )
    show_branding = models.BooleanField(
        default=True,
        help_text='Show the sethsparts brand ("Seth\'s Parts") above the shop name in the header. Untick to show only your own name.',
    )
    show_onscreen_keyboard = models.BooleanField(
        default=True,
        help_text="Show the on-screen keyboard button on the Pi kiosk. Untick if the workshop has a physical keyboard.",
    )
    # AI enrichment keys. Settable from Settings (like SMTP) so a non-technical owner
    # never has to edit .env and restart Docker; the env var is the fallback for people
    # who deploy with Docker and prefer to keep secrets out of the database.
    deepseek_api_key = models.CharField(
        max_length=200, blank=True, help_text="DeepSeek API key for the enrichment suggestions."
    )
    tavily_api_key = models.CharField(
        max_length=200,
        blank=True,
        help_text="Tavily API key for the web-research step (product pages, datasheets, pricing).",
    )
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        help_text=(
            "IANA name, e.g. Europe/London or America/New_York. Every timestamp displays "
            "in this zone — set it to where the workshop actually is."
        ),
    )
    country = models.CharField(
        max_length=2,
        blank=True,
        help_text=(
            "ISO 3166-1 alpha-2, e.g. GB or US. Decides whether postcodes or ZIP codes "
            "are expected when finding nearby workshops."
        ),
    )
    unit_system = models.CharField(
        max_length=10,
        choices=UNIT_SYSTEMS,
        default="metric",
        help_text="Which units are offered first. Every unit stays selectable either way.",
    )
    theme = models.CharField(
        max_length=10,
        choices=[("precision", "Precision — cool slate and cyan"), ("warm", "Warm — charcoal and amber")],
        default="precision",
        help_text="The app's look. Both dark; pick whichever suits the workshop.",
    )
    # Hardware addresses, which is what lets the setup wizard configure them at all —
    # before this they existed only as environment variables, so a browser-based setup
    # could not have set them. Plain CharField rather than URLField on purpose: people
    # type "192.168.1.50:8080" without a scheme, and a form that rejects that before
    # the app has a chance to add "http://" is just obstructive. Blank means not
    # configured, and the matching feature is hidden rather than broken.
    led_controller_url = models.CharField(
        max_length=300,
        blank=True,
        help_text="Address of the LED 'find the part' controller, e.g. http://192.168.1.50:8080",
    )
    led_controller_key = models.CharField(
        max_length=200, blank=True, help_text="Shared secret for the LED controller, if it needs one."
    )
    label_printer_url = models.CharField(
        max_length=300,
        blank=True,
        help_text="Address of the label print bridge, e.g. http://192.168.1.50:9100",
    )
    label_printer_key = models.CharField(
        max_length=200, blank=True, help_text="Shared secret for the print bridge, if it needs one."
    )
    label_driver = models.CharField(
        max_length=20,
        default="zpl",
        choices=[
            ("zpl", "Zebra / ZPL"),
            ("brother_ql", "Brother QL"),
            ("dymo", "Dymo LabelWriter"),
            ("cups", "Any printer via CUPS"),
        ],
        help_text="Which printer language the label renderer should produce.",
    )
    # CharField rather than an integer field, for the same reason the addresses above
    # are: it arrives from a form, and blank has to mean "not configured". Blank means
    # "use this printer's own resolution", which is the right answer for almost
    # everyone -- the number is only here for the 300dpi variant of a printer whose
    # sibling is 203dpi.
    label_dpi = models.CharField(
        max_length=6,
        blank=True,
        help_text=(
            "The printer's dots per inch, e.g. 203. Leave blank to use the resolution "
            "that goes with the printer type above."
        ),
    )
    public_url = models.CharField(
        max_length=300,
        blank=True,
        help_text=(
            "The address you reach this app at, e.g. https://parts.example.com. Pasted "
            "from your tunnel or reverse proxy. Only used to check that it works."
        ),
    )

    # Email notifications. Two opt-ins, deliberately separate: the SMTP settings must
    # be filled in, and each notification turned on individually. Until both happen the
    # app sends nothing. SMTP is the one mechanism rather than OAuth on purpose — a
    # Gmail "app password" is something a non-technical owner can generate in a couple
    # of minutes (the page walks through it), and it works with any provider.
    email_enabled = models.BooleanField(
        default=False,
        help_text="Master switch. Nothing is sent until this is on.",
    )
    smtp_host = models.CharField(max_length=200, blank=True, help_text="e.g. smtp.gmail.com")
    smtp_port = models.PositiveIntegerField(
        default=587, help_text="587 is Gmail's and most providers'; 465 is the TLS-only alternative."
    )
    smtp_user = models.CharField(
        max_length=200, blank=True, help_text="The account that sends the mail, e.g. you@gmail.com"
    )
    smtp_password = models.CharField(
        max_length=200,
        blank=True,
        help_text="A Gmail app password (see the page's instructions), not your login password.",
    )
    smtp_use_tls = models.BooleanField(default=True, help_text="STARTTLS. Leave on — almost every provider wants it.")
    email_from = models.CharField(
        max_length=200, blank=True, help_text="The From: address. Defaults to the SMTP account above."
    )
    notify_email = models.CharField(
        max_length=200, blank=True, help_text="Where notifications go. Defaults to the From: address."
    )
    feedback_email = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where in-app feedback (bug reports, feature requests) is sent. Blank means the feedback form offers copy-to-clipboard instead of sending.",
    )
    notify_on_message = models.BooleanField(default=False)
    notify_on_connection = models.BooleanField(default=False)
    notify_on_search = models.BooleanField(default=False)

    # Set the first time the starter reference set is loaded. The loader is one-shot
    # by default: without this, re-running it would quietly resurrect documents the
    # owner had deliberately deleted, which makes the library impossible to prune.
    starter_reference_loaded_at = models.DateTimeField(
        null=True, blank=True, help_text="When the starter reference library was first loaded."
    )
    setup_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the setup wizard finished. Null means setup is still outstanding.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site settings"
        verbose_name_plural = "site settings"

    def __str__(self):
        return self.site_name

    @classmethod
    def load(cls):
        obj = cls.objects.first()
        return obj if obj is not None else cls.objects.create()

    @property
    def setup_complete(self) -> bool:
        return self.setup_completed_at is not None

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Keep the admin header in step with a rename. The alternative is the admin
        # still showing the old name until the process happens to restart.
        from .site_config import apply_site_branding

        apply_site_branding()
