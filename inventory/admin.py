from django.contrib import admin

from .models import (
    Attachment,
    BOMLine,
    BOMRevision,
    Build,
    BuildConsumption,
    Category,
    Container,
    Drawer,
    DrawerLedSegment,
    Location,
    Part,
    Project,
    ReferenceDoc,
    StockItem,
)


class DrawerInline(admin.TabularInline):
    model = Drawer
    extra = 0


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ["number", "name", "container_type", "location", "barcode_id"]
    list_filter = ["container_type", "location"]
    search_fields = ["number", "name", "barcode_id"]
    inlines = [DrawerInline]


class DrawerLedSegmentInline(admin.TabularInline):
    model = DrawerLedSegment
    extra = 0


@admin.register(Drawer)
class DrawerAdmin(admin.ModelAdmin):
    list_display = ["container", "label", "barcode_id"]
    list_filter = ["container"]
    search_fields = ["label", "barcode_id"]
    inlines = [DrawerLedSegmentInline]


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
    list_display = ["part", "container", "drawer", "quantity", "quantity_raw"]
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


admin.site.site_header = "Seth's Parts"
