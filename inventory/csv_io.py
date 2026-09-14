"""Robust CSV import/export for the inventory.

Export writes one row per StockItem with Excel-safe UTF-8 (a BOM plus the csv
module's quoting, so commas, quotes, newlines and non-ASCII survive a round trip).
Import reads that back — or any header-compatible CSV — maps common column-name
variants, and resolves references smartly: parts dedupe by name, containers by
number, drawers by (container, label), locations and categories by name. It
previews what would change before writing, then commits atomically.
"""

import csv
import io
import re
from collections import OrderedDict

from django.db import transaction

from .models import Category, Container, Drawer, Location, Part, StockItem

# Canonical field keys in export order. The display header for each is the first
# entry in COLUMN_ALIASES, so a file we export parses back through our own import.
EXPORT_COLUMNS = [
    "part_name", "category", "manufacturer", "description", "is_electronic",
    "reorder_url", "datasheet_url", "min_quantity",
    "container_number", "container_type", "location",
    "drawer", "bin_number",
    "quantity", "unit", "notes",
]

# Human-readable headers written by export (and recognised back by import — the
# first alias of each canonical key). Kept in the same order as EXPORT_COLUMNS.
EXPORT_HEADERS = [
    "Part name", "Category", "Manufacturer", "Description", "Is electronic",
    "Reorder URL", "Datasheet URL", "Min quantity",
    "Container number", "Container type", "Location",
    "Drawer", "Bin number", "Quantity", "Unit", "Notes",
]

_DISPLAY_NAMES = dict(zip(EXPORT_COLUMNS, EXPORT_HEADERS))

COLUMN_ALIASES = {
    "part_name": ["part name", "part", "name", "item", "item name"],
    "category": ["category", "type", "group"],
    "manufacturer": ["manufacturer", "mfr", "brand", "make"],
    "description": ["description", "part description", "specs", "specification"],
    "is_electronic": ["is electronic", "electronic", "electronics"],
    "reorder_url": ["reorder url", "reorder link", "buy link", "purchase url", "order url"],
    "datasheet_url": ["datasheet url", "datasheet link", "datasheet"],
    "min_quantity": ["min quantity", "reorder threshold", "min qty", "reorder point", "reorder at"],
    "container_number": ["container number", "box", "box number", "container", "tote number", "container no", "box no"],
    "container_type": ["container type", "box size", "tote type", "box type", "size"],
    "location": ["location", "room", "area", "place"],
    "drawer": ["drawer", "drawer label", "drawer name"],
    "bin_number": ["bin number", "bin", "bin no"],
    "quantity": ["quantity", "qty", "count", "num items", "amount", "number"],
    "unit": ["unit", "units", "uom", "measure"],
    "notes": ["notes", "source notes", "comments", "comment"],
}

BINS_PER_DRAWER = 16


def _norm_header(value):
    return " ".join(str(value or "").strip().lower().split())


_HEADER_TO_KEY = {}
for _key, _names in COLUMN_ALIASES.items():
    for _name in _names:
        _HEADER_TO_KEY[_norm_header(_name)] = _key


# --- Export -------------------------------------------------------------------

def export_csv_text():
    """Return (csv_text_with_bom, row_count) for every StockItem."""
    rows = (
        StockItem.objects.select_related(
            "part", "part__category", "container", "container__location", "drawer"
        )
        .order_by("container__number", "part__name")
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_HEADERS)
    count = 0
    for si in rows:
        part = si.part
        writer.writerow([
            part.name,
            part.category.name if part.category else "",
            part.manufacturer,
            part.description,
            "yes" if part.is_electronic else "",
            part.reorder_url,
            part.datasheet_url,
            part.min_quantity if part.min_quantity is not None else "",
            si.container.number,
            si.container.container_type,
            si.container.location.name if si.container.location else "",
            si.drawer.label if si.drawer else "",
            si.bin_number if si.bin_number is not None else "",
            si.quantity_raw or (str(si.quantity) if si.quantity is not None else ""),
            si.unit or "",
            si.source_notes,
        ])
        count += 1
    return "\ufeff" + buf.getvalue(), count


# --- Import: parsing ----------------------------------------------------------

def parse_csv(raw_bytes):
    """Decode uploaded bytes into a list of dicts keyed by canonical field.

    Returns (rows, errors). ``errors`` are fatal problems (undecodable, no
    header, or a missing required column) that make the whole file un-importable;
    per-row problems are reported later by :func:`analyze_rows`.
    """
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return [], ["Couldn't decode the file — expected a text/CSV file."]

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["The file has no header row."]

    mapping = OrderedDict()
    for fn in reader.fieldnames:
        key = _HEADER_TO_KEY.get(_norm_header(fn))
        if key:
            mapping[fn] = key

    missing = [c for c in ("part_name", "container_number") if c not in mapping.values()]
    if missing:
        missing_names = [_DISPLAY_NAMES[c] for c in missing]
        return [], ["Missing required column(s): " + ", ".join(missing_names)]

    rows = []
    for record in reader:
        row = {}
        for fn, value in record.items():
            key = mapping.get(fn)
            if key:
                row[key] = value
        # Skip fully blank lines (a stray trailing newline in the file).
        if any((v or "").strip() for v in row.values()):
            rows.append(row)
    return rows, []


# --- Import: resolution -------------------------------------------------------

def _parse_quantity(value):
    raw = (value or "").strip()
    if not raw:
        return None
    match = re.search(r"\d+", raw)
    return int(match.group()) if match else None


def _parse_int(value):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return max(0, int(float(raw)))
    except (ValueError, TypeError):
        return None


def _parse_bool(value):
    return (value or "").strip().lower() in {"yes", "true", "1", "y", "x", "on", "electronic"}


def _parse_bin(value):
    """Return int 1-16, None for blank, or False for an out-of-range value."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        n = int(float(raw))
    except (ValueError, TypeError):
        return False
    return n if 1 <= n <= BINS_PER_DRAWER else False


def _get_category(name, caches, new_categories, seen_new):
    name = (name or "").strip()
    if not name:
        return None
    key = name.lower()
    cat = caches["categories"].get(key)
    if cat is None:
        cat = Category.objects.filter(name__iexact=name).first()
        if cat is None:
            cat = Category(name=name)
            caches["categories"][key] = cat
            if id(cat) not in seen_new["category"]:
                seen_new["category"].add(id(cat))
                new_categories.append(cat)
        else:
            caches["categories"][key] = cat
    return cat


def analyze_rows(rows):
    """Resolve every row against the DB WITHOUT writing.

    Returns a dict with ``resolved`` (per-row data for commit), ``errors``
    ([(row_number, message)]), ``counts`` (what a commit would create), and the
    deduplicated lists of unsaved objects to create.
    """
    caches = {"parts": {}, "containers": {}, "drawers": {}, "locations": {}, "categories": {}}
    seen_new = {k: set() for k in ("part", "container", "drawer", "location", "category")}
    new_parts, new_containers, new_drawers, new_locations, new_categories = [], [], [], [], []
    resolved, errors = [], []

    for i, row in enumerate(rows, start=2):  # row 1 is the header
        name = (row.get("part_name") or "").strip()
        container_num_raw = (row.get("container_number") or "").strip()

        if not name:
            errors.append((i, "missing part name"))
            continue
        if not container_num_raw:
            errors.append((i, "missing container number"))
            continue
        try:
            container_number = int(float(container_num_raw))
        except (ValueError, TypeError):
            errors.append((i, f"container number '{container_num_raw}' isn't a number"))
            continue

        # Part — dedupe by normalized name; existing parts are left untouched.
        normalized = name.lower()
        part = caches["parts"].get(normalized)
        if part is None:
            part = Part.objects.filter(normalized_name=normalized).first()
            if part is None:
                part = Part(name=name)
                caches["parts"][normalized] = part
                if id(part) not in seen_new["part"]:
                    seen_new["part"].add(id(part))
                    new_parts.append(part)
            else:
                caches["parts"][normalized] = part
        part_new = id(part) in seen_new["part"]
        if part_new:
            part.category = _get_category(row.get("category"), caches, new_categories, seen_new)
            part.manufacturer = (row.get("manufacturer") or "").strip()
            part.description = (row.get("description") or "").strip()
            part.is_electronic = _parse_bool(row.get("is_electronic"))
            part.reorder_url = (row.get("reorder_url") or "").strip()
            part.datasheet_url = (row.get("datasheet_url") or "").strip()
            part.min_quantity = _parse_int(row.get("min_quantity"))

        # Location — by name.
        location_name = (row.get("location") or "").strip()
        location = None
        if location_name:
            location = caches["locations"].get(location_name.lower())
            if location is None:
                location = Location.objects.filter(name__iexact=location_name).first()
                if location is None:
                    location = Location(name=location_name)
                    caches["locations"][location_name.lower()] = location
                    if id(location) not in seen_new["location"]:
                        seen_new["location"].add(id(location))
                        new_locations.append(location)
                else:
                    caches["locations"][location_name.lower()] = location

        # Container — by number.
        container = caches["containers"].get(container_number)
        if container is None:
            container = Container.objects.filter(number=container_number).first()
            if container is None:
                container = Container(
                    number=container_number,
                    container_type=(row.get("container_type") or "").strip(),
                    location=location,
                    barcode_id=f"C{container_number}",
                )
                caches["containers"][container_number] = container
                if id(container) not in seen_new["container"]:
                    seen_new["container"].add(id(container))
                    new_containers.append(container)
            else:
                caches["containers"][container_number] = container
        container_new = id(container) in seen_new["container"]

        # Drawer — by (container, label).
        drawer_label = (row.get("drawer") or "").strip()
        drawer = None
        drawer_new = False
        if drawer_label:
            dkey = (container_number, drawer_label.lower())
            drawer = caches["drawers"].get(dkey)
            if drawer is None:
                drawer = Drawer.objects.filter(
                    container__number=container_number, label__iexact=drawer_label
                ).first()
                if drawer is None:
                    drawer = Drawer(label=drawer_label, container=container)
                    caches["drawers"][dkey] = drawer
                    if id(drawer) not in seen_new["drawer"]:
                        seen_new["drawer"].add(id(drawer))
                        new_drawers.append(drawer)
                    drawer_new = True
                else:
                    caches["drawers"][dkey] = drawer
            else:
                drawer_new = id(drawer) in seen_new["drawer"]

        bin_number = _parse_bin(row.get("bin_number"))
        if bin_number is False:
            errors.append((i, f"bin number '{row.get('bin_number')}' isn't 1-{BINS_PER_DRAWER}"))
            continue

        quantity_raw = (row.get("quantity") or "").strip()
        resolved.append({
            "part": part, "part_new": part_new,
            "container": container, "container_new": container_new,
            "drawer": drawer, "drawer_new": drawer_new,
            "stock": {
                "quantity": _parse_quantity(quantity_raw),
                "quantity_raw": quantity_raw,
                "unit": (row.get("unit") or "").strip(),
                "source_notes": (row.get("notes") or "").strip(),
                "bin_number": bin_number,
            },
        })

    return {
        "resolved": resolved,
        "errors": errors,
        "counts": {
            "parts_new": len(new_parts),
            "containers_new": len(new_containers),
            "drawers_new": len(new_drawers),
            "locations_new": len(new_locations),
            "categories_new": len(new_categories),
            "stock_items": len(resolved),
        },
        "new_parts": new_parts,
        "new_containers": new_containers,
        "new_drawers": new_drawers,
        "new_locations": new_locations,
        "new_categories": new_categories,
    }


def commit_import(analysis):
    """Write a resolved analysis atomically. Returns the same ``counts`` dict."""
    with transaction.atomic():
        for location in analysis["new_locations"]:
            location.save()
        for category in analysis["new_categories"]:
            category.save()
        for part in analysis["new_parts"]:
            part.save()  # also sets normalized_name via the model's save()
        for container in analysis["new_containers"]:
            container.save()
        for drawer in analysis["new_drawers"]:
            drawer.save()
        for rr in analysis["resolved"]:
            StockItem.objects.create(
                part=rr["part"],
                container=rr["container"],
                drawer=rr["drawer"],
                quantity=rr["stock"]["quantity"],
                quantity_raw=rr["stock"]["quantity_raw"],
                unit=rr["stock"]["unit"],
                source_notes=rr["stock"]["source_notes"],
                bin_number=rr["stock"]["bin_number"],
            )
    return analysis["counts"]
