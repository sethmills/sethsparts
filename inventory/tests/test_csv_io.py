import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from ..csv_io import analyze_rows, commit_import, export_csv_text, parse_csv
from ..models import Container, Location, Part, StockItem
from .factories import make_container, make_part, make_stock, make_user


def _csv(headers, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


class ParseCsvTests(TestCase):
    def test_round_trip_headers(self):
        rows, errors = parse_csv(
            _csv(["Part name", "Container number", "Quantity"], [["M3 Bolt", "1", "10"]]).encode("utf-8")
        )
        self.assertEqual(errors, [])
        self.assertEqual(rows, [{"part_name": "M3 Bolt", "container_number": "1", "quantity": "10"}])

    def test_alias_headers(self):
        rows, errors = parse_csv(_csv(["Item", "Box", "Qty"], [["LED", "3", "5"]]).encode("utf-8"))
        self.assertEqual(errors, [])
        self.assertEqual(rows, [{"part_name": "LED", "container_number": "3", "quantity": "5"}])

    def test_special_characters_survive(self):
        name = 'Resistor 1k\u03a9, "5%", 0.5W\nsecond line'
        rows, errors = parse_csv(
            _csv(["Part name", "Container number", "Notes"], [[name, "2", "note with, comma"]]).encode("utf-8")
        )
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["part_name"], name)
        self.assertEqual(rows[0]["notes"], "note with, comma")

    def test_bom_is_handled(self):
        rows, errors = parse_csv(b"\xef\xbb\xbfPart name,Container number\nM3 Bolt,1\n")
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["part_name"], "M3 Bolt")

    def test_missing_required_column(self):
        rows, errors = parse_csv(_csv(["Part name", "Quantity"], [["M3 Bolt", "5"]]).encode("utf-8"))
        self.assertEqual(rows, [])
        self.assertTrue(any("Container" in e for e in errors))


class AnalyzeAndCommitTests(TestCase):
    def test_dedup_parts_and_containers(self):
        rows = [
            {"part_name": "M3 Bolt", "container_number": "1", "quantity": "10"},
            {"part_name": "M3 Bolt", "container_number": "1", "quantity": "5"},
            {"part_name": "M3 bolts", "container_number": "2", "quantity": "3"},
        ]
        analysis = analyze_rows(rows)
        self.assertEqual(analysis["errors"], [])
        # Exact normalized-name dedup: "M3 Bolt" twice = one part; "M3 bolts" differs.
        self.assertEqual(analysis["counts"]["parts_new"], 2)
        self.assertEqual(analysis["counts"]["containers_new"], 2)
        self.assertEqual(analysis["counts"]["stock_items"], 3)

    def test_existing_part_not_overwritten(self):
        existing = make_part(name="M3 Bolt", manufacturer="OldCo")
        rows = [{"part_name": "M3 Bolt", "container_number": "1", "manufacturer": "NewCo", "quantity": "10"}]
        analysis = analyze_rows(rows)
        self.assertEqual(analysis["counts"]["parts_new"], 0)
        commit_import(analysis)
        existing.refresh_from_db()
        self.assertEqual(existing.manufacturer, "OldCo")  # left untouched
        self.assertEqual(existing.stock_items.count(), 1)  # but stock was added

    def test_commit_creates_everything(self):
        rows = [{
            "part_name": "Resistor", "container_number": "1", "container_type": "tote",
            "location": "Garage", "drawer": "drawer a1", "quantity": "10", "unit": "pcs",
            "category": "Electronics", "bin_number": "3", "notes": "bought 2026",
        }]
        analysis = analyze_rows(rows)
        self.assertEqual(analysis["errors"], [])
        counts = commit_import(analysis)
        self.assertEqual(counts["stock_items"], 1)
        self.assertEqual(Part.objects.count(), 1)
        self.assertEqual(Container.objects.count(), 1)
        self.assertEqual(Location.objects.count(), 1)
        self.assertEqual(analysis["new_containers"][0].barcode_id, "C1")
        si = StockItem.objects.get()
        self.assertEqual(si.quantity, 10)
        self.assertEqual(si.bin_number, 3)
        self.assertEqual(si.part.category.name, "Electronics")
        self.assertEqual(si.drawer.label, "drawer a1")

    def test_bad_bin_is_reported_and_skipped(self):
        rows = [{"part_name": "X", "container_number": "1", "bin_number": "101"}]
        analysis = analyze_rows(rows)
        self.assertTrue(analysis["errors"])
        self.assertEqual(analysis["counts"]["stock_items"], 0)

    def test_missing_name_and_bad_container_reported(self):
        rows = [
            {"container_number": "1"},
            {"part_name": "X", "container_number": "not-a-number"},
        ]
        analysis = analyze_rows(rows)
        self.assertEqual(len(analysis["errors"]), 2)


class ExportRoundTripTests(TestCase):
    def test_round_trip_finds_everything_existing(self):
        container = make_container(number=7, container_type="tote")
        part = make_part(name="M3 Bolt")
        make_stock(part, container, quantity=10)
        text, count = export_csv_text()
        self.assertEqual(count, 1)
        rows, errors = parse_csv(text.encode("utf-8"))
        self.assertEqual(errors, [])
        analysis = analyze_rows(rows)
        self.assertEqual(analysis["errors"], [])
        self.assertEqual(analysis["counts"]["parts_new"], 0)
        self.assertEqual(analysis["counts"]["containers_new"], 0)


class CsvViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.container = make_container(number=1)
        self.part = make_part(name="M3 Bolt")

    def test_export_csv_view(self):
        make_stock(self.part, self.container, quantity=4)
        resp = self.client.get(reverse("inventory:export_csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("M3 Bolt", resp.content.decode("utf-8"))

    def test_import_preview_then_confirm(self):
        up = SimpleUploadedFile("inv.csv", b"Part name,Container number,Quantity\nResistor,1,10\n", content_type="text/csv")
        resp = self.client.post(reverse("inventory:import_csv"), {"csv_file": up})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Confirm and import 1 row")
        resp = self.client.post(reverse("inventory:import_csv"), {"confirm": "1"})
        self.assertRedirects(resp, reverse("inventory:import_csv"))
        self.assertTrue(Part.objects.filter(name="Resistor").exists())
        self.assertEqual(StockItem.objects.count(), 1)
