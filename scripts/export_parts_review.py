"""One-off export: parts needing review/clarification -> an editable spreadsheet.

Run with: ./venv/bin/python scripts/export_parts_review.py
Not a management command -- this is a one-time deliverable generator, not an
app feature.
"""
import json
import os
import sys
from urllib.parse import quote

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.worksheet.worksheet import Worksheet  # noqa: E402

from inventory.models import Part, StockItem  # noqa: E402

SCRATCH = "/private/tmp/claude-501/-Users-seth/d95730c8-627a-4511-954d-f4112cc34ecf/scratchpad"
SOURCE_FILES = [
    "adafruit_parts.json",
    "batch1_results.json",
    "batch2_merged.json",
    "batch3_results.json",
]
SITE = "https://sethsparts.com"

HEADER_FILL = PatternFill("solid", fgColor="1E2128")
HEADER_FONT = Font(color="E6E8EB", bold=True)
LOW_FILL = PatternFill("solid", fgColor="FFF3CD")


def load_notes():
    notes = {}
    for fn in SOURCE_FILES:
        path = os.path.join(SCRATCH, fn)
        if os.path.exists(path):
            for entry in json.load(open(path)):
                notes[entry["id"]] = entry
    return notes


def style_header(ws: Worksheet, ncols):
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 28


def search_url(name):
    return f"https://www.google.com/search?q={quote(name)}"


def part_url(pk):
    return f"{SITE}/parts/{pk}/"


def add_hyperlink(ws, row, col, url, label):
    cell = ws.cell(row=row, column=col, value=label)
    cell.hyperlink = url
    cell.font = Font(color="1F5FD2", underline="single")
    return cell


def build_needs_review_sheet(wb, notes):
    ws = wb.active
    ws.title = "Needs Review"
    headers = [
        "ID", "Part Name", "Current Guess", "Confidence", "Why Uncertain",
        "Part Page", "Quick Search", "Correct Product / Model (fill in)", "Correct URL (fill in)",
    ]
    ws.append(headers)
    style_header(ws, len(headers))

    parts = Part.objects.filter(enrichment_status="needs_review").order_by("name")
    for i, p in enumerate(parts, start=2):
        entry = notes.get(p.id, {})
        ws.cell(row=i, column=1, value=p.id)
        ws.cell(row=i, column=2, value=p.name)
        ws.cell(row=i, column=3, value=entry.get("matched_product_name", p.description))
        confidence = entry.get("confidence", "")
        conf_cell = ws.cell(row=i, column=4, value=confidence)
        ws.cell(row=i, column=5, value=entry.get("notes", ""))
        add_hyperlink(ws, i, 6, part_url(p.id), "Open in app")
        add_hyperlink(ws, i, 7, search_url(p.name), "Google it")
        # columns 8-9 left blank for the user

        if confidence == "low":
            for col in range(1, len(headers) + 1):
                ws.cell(row=i, column=col).fill = LOW_FILL

    widths = [6, 32, 40, 11, 50, 12, 12, 30, 30]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.auto_filter.ref = f"A1:{chr(64 + len(headers))}{ws.max_row}"
    return ws


def build_needs_clarification_sheet(wb):
    ws = wb.create_sheet("Needs Clarification")
    headers = [
        "ID", "Part Name", "Container", "Drawer", "Qty",
        "Part Page", "Quick Search", "What is this? (fill in)", "Correct URL (fill in)",
    ]
    ws.append(headers)
    style_header(ws, len(headers))

    parts = Part.objects.filter(enrichment_status="needs_clarification").order_by(
        "stock_items__container__number", "stock_items__drawer__label", "name"
    )
    seen = set()
    row = 2
    for p in parts:
        if p.id in seen:
            continue
        seen.add(p.id)
        for si in StockItem.objects.filter(part=p).select_related("container", "drawer").order_by(
            "container__number", "drawer__label"
        ):
            ws.cell(row=row, column=1, value=p.id)
            ws.cell(row=row, column=2, value=p.name)
            ws.cell(row=row, column=3, value=si.container.number)
            ws.cell(row=row, column=4, value=si.drawer.label if si.drawer else "")
            ws.cell(row=row, column=5, value=si.quantity_raw or si.quantity)
            add_hyperlink(ws, row, 6, part_url(p.id), "Open in app")
            add_hyperlink(ws, row, 7, search_url(p.name), "Google it")
            row += 1

    widths = [6, 32, 11, 11, 8, 12, 12, 34, 30]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.auto_filter.ref = f"A1:{chr(64 + len(headers))}{ws.max_row}"
    return ws


def main():
    notes = load_notes()
    wb = Workbook()
    build_needs_review_sheet(wb, notes)
    build_needs_clarification_sheet(wb)
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "parts_review.xlsx")
    wb.save(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
