from django.contrib import admin

from .models import (
    Attachment,
    Bin,
    BOMLine,
    BOMRevision,
    Build,
    BuildConsumption,
    Category,
    CommunityIdentity,
    CommunityProfile,
    Container,
    ContainerPhoto,
    Drawer,
    DrawerLedSegment,
    IntakeNote,
    LedStrip,
    Location,
    PairingCode,
    Part,
    Peer,
    PeerSearchLog,
    Project,
    ReferenceDoc,
    StockItem,
    SubBin,
)


class DrawerInline(admin.TabularInline):
    model = Drawer
    extra = 0


class ContainerPhotoInline(admin.TabularInline):
    model = ContainerPhoto
    extra = 0
    readonly_fields = ["uploaded_at"]


class IntakeNoteInline(admin.TabularInline):
    model = IntakeNote
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ["number", "name", "container_type", "location", "barcode_id"]
    list_filter = ["container_type", "location"]
    search_fields = ["number", "name", "barcode_id"]
    inlines = [DrawerInline, ContainerPhotoInline, IntakeNoteInline]


@admin.register(IntakeNote)
class IntakeNoteAdmin(admin.ModelAdmin):
    list_display = ["container", "text", "source", "reviewed", "created_at"]
    list_filter = ["reviewed", "source"]
    list_editable = ["reviewed"]
    search_fields = ["text"]
    autocomplete_fields = ["container"]


class DrawerLedSegmentInline(admin.TabularInline):
    model = DrawerLedSegment
    extra = 0


@admin.register(LedStrip)
class LedStripAdmin(admin.ModelAdmin):
    """The strip-to-channel map, which the setup wizard pushes to the Pi."""

    list_display = ["name", "channel"]
    list_editable = ["channel"]
    search_fields = ["name"]
    ordering = ["channel"]


class BinInline(admin.TabularInline):
    model = Bin
    extra = 0


class SubBinInline(admin.TabularInline):
    model = SubBin
    extra = 0


@admin.register(Drawer)
class DrawerAdmin(admin.ModelAdmin):
    list_display = ["container", "label", "barcode_id"]
    list_filter = ["container"]
    search_fields = ["label", "barcode_id"]
    inlines = [DrawerLedSegmentInline, BinInline]


@admin.register(Bin)
class BinAdmin(admin.ModelAdmin):
    list_display = ["drawer", "bin_number", "barcode_id"]
    list_filter = ["drawer__container"]
    search_fields = ["barcode_id"]
    autocomplete_fields = ["drawer"]
    inlines = [SubBinInline]


@admin.register(SubBin)
class SubBinAdmin(admin.ModelAdmin):
    list_display = ["bin", "position", "size", "barcode_id"]
    list_filter = ["size", "bin__drawer__container"]
    search_fields = ["barcode_id"]
    autocomplete_fields = ["bin"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ["name"]


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_electronic", "manufacturer", "enrichment_status", "min_quantity"]
    list_filter = ["category", "is_electronic", "enrichment_status"]
    list_editable = ["min_quantity"]
    search_fields = ["name", "manufacturer", "description"]
    inlines = [AttachmentInline]


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ["part", "doc_type", "source_url", "fetched_at"]
    list_filter = ["doc_type"]
    search_fields = ["part__name", "title"]
    autocomplete_fields = ["part"]


class StockItemInline(admin.TabularInline):
    model = StockItem
    extra = 0
    autocomplete_fields = ["part"]


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ["part", "container", "drawer", "quantity", "quantity_raw", "bin_number"]
    list_editable = ["bin_number"]
    list_filter = ["container", "drawer"]
    search_fields = ["part__name", "source_notes"]
    autocomplete_fields = ["part", "container", "drawer"]


class BOMLineInline(admin.TabularInline):
    model = BOMLine
    extra = 1
    autocomplete_fields = ["part"]


@admin.register(BOMRevision)
class BOMRevisionAdmin(admin.ModelAdmin):
    list_display = ["project", "version", "created_at"]
    list_filter = ["project"]
    inlines = [BOMLineInline]
    readonly_fields = ["version"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["name", "description"]


class BuildConsumptionInline(admin.TabularInline):
    model = BuildConsumption
    extra = 0
    readonly_fields = ["part", "quantity_requested", "quantity_consumed"]
    can_delete = False


@admin.register(Build)
class BuildAdmin(admin.ModelAdmin):
    list_display = ["project", "revision", "quantity_built", "built_at"]
    list_filter = ["project"]
    inlines = [BuildConsumptionInline]
    readonly_fields = ["project", "revision", "quantity_built", "notes", "built_at"]

    def has_add_permission(self, request):
        # Builds are created via the "Build this revision" action on the project page,
        # not hand-entered — that's what actually consumes stock.
        return False


@admin.register(ReferenceDoc)
class ReferenceDocAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "order", "external_url"]
    list_filter = ["category"]
    search_fields = ["title", "description"]


@admin.register(CommunityIdentity)
class CommunityIdentityAdmin(admin.ModelAdmin):
    """Read-only, and the signing key is not listed here at all.

    `private_key` is deliberately absent from `fields` and `readonly_fields`: this
    page is reachable by anyone who gets into the admin, and the private key can
    forge this instance's pins for as long as it exists. It has no reason to be
    displayed, so it is not.
    """

    fields = ["public_key", "created_at"]
    readonly_fields = ["public_key", "created_at"]
    list_display = ["public_key", "created_at"]

    def has_add_permission(self, request):
        # One identity per instance; it is generated on first use, not created by hand.
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting it would silently change this instance's identity on the network.
        return False


@admin.register(CommunityProfile)
class CommunityProfileAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Appearing on the map",
            {
                "fields": ("discoverable", "display_name"),
                "description": (
                    "Discoverable shows this workshop as an anonymous pin on other "
                    "instances' maps. It is independent of who can search your parts — "
                    "that is set per person under Community → Peers."
                ),
            },
        ),
        (
            "Approximate location",
            {
                "fields": ("location_lat", "location_lon", "location_source"),
                "description": (
                    "Postcode-AREA only: a UK outcode or a US ZIP centroid. Never store a "
                    "full UK postcode here — one identifies roughly fifteen households. "
                    "The postcode you typed is deliberately not kept."
                ),
            },
        ),
        ("Meta", {"fields": ("updated_at",)}),
    )
    readonly_fields = ["updated_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Peer)
class PeerAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "exchanges_pins", "shares_parts", "is_seed", "last_seen_at"]
    list_filter = ["status", "exchanges_pins", "shares_parts", "is_seed"]
    search_fields = ["name", "base_url"]
    readonly_fields = ["public_key", "created_at", "last_seen_at"]
    fieldsets = (
        (None, {"fields": ("name", "base_url", "status", "contact_note")}),
        (
            "What they may do",
            {
                "fields": ("exchanges_pins", "shares_parts"),
                "description": (
                    "Two separate permissions. Exchanging pins puts you on the same map and "
                    "never grants access to inventory. Sharing parts lets them search the "
                    "categories you marked shareable — turn that on for one person at a time."
                ),
            },
        ),
        (
            "Credentials",
            {
                "fields": ("public_key", "inbound_api_key", "outbound_api_key"),
                "description": (
                    "inbound_api_key is the credential you issued them; outbound_api_key is "
                    "the one they issued you. Set automatically when pairing succeeds."
                ),
            },
        ),
        ("Meta", {"fields": ("is_seed", "created_at", "last_seen_at")}),
    )


@admin.register(PairingCode)
class PairingCodeAdmin(admin.ModelAdmin):
    list_display = ["code_display", "created_at", "expires_at", "claimed_at", "claimed_by", "usable"]
    readonly_fields = ["code", "created_at", "expires_at", "claimed_at", "claimed_by"]

    @admin.display(description="Code")
    def code_display(self, obj):
        return obj.display

    @admin.display(boolean=True, description="Usable")
    def usable(self, obj):
        return obj.is_usable()

    def has_add_permission(self, request):
        # Issued from the Community page so the code is shown to the owner once it exists.
        return False


@admin.register(PeerSearchLog)
class PeerSearchLogAdmin(admin.ModelAdmin):
    """An audit log. Read-only by design — a log you can edit is not a log."""

    list_display = ["peer", "query", "result_count", "searched_at"]
    list_filter = ["peer"]
    search_fields = ["query"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# The admin's header is no longer set here. It comes from SiteSettings via
# inventory.site_config.apply_site_branding(), called in InventoryConfig.ready() and
# again whenever the name changes — so a clone shows its owner's name, not Seth's.
