"""CSV import/export of the inventory — the round-trippable, spreadsheet-friendly
path alongside the full ZIP backup in :mod:`.enrichment`."""

import json
import os
import tempfile
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from ..csv_io import analyze_rows, commit_import, export_csv_text, parse_csv


@login_required
def export_csv(request):
    text, _count = export_csv_text()
    response = HttpResponse(text, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f"attachment; filename=inventory-export-{datetime.now():%Y%m%d-%H%M%S}.csv"
    )
    return response


@login_required
def import_csv(request):
    if request.method == "POST":
        # Confirm step — the raw rows were stashed on disk at upload time (the
        # session only carries a path, not the whole file).
        if request.POST.get("confirm"):
            path = request.session.pop("csv_import_path", None)
            if not path:
                messages.error(request, "Import session expired — please upload the file again.")
                return redirect("inventory:import_csv")
            try:
                with open(path, encoding="utf-8") as f:
                    rows = json.load(f)
            except (OSError, ValueError):
                rows = None
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass

            if rows is None:
                messages.error(request, "Couldn't reload the import — please upload the file again.")
                return redirect("inventory:import_csv")

            analysis = analyze_rows(rows)
            if analysis["errors"]:
                messages.error(request, "Import aborted: some rows still had problems.")
                return redirect("inventory:import_csv")

            counts = commit_import(analysis)
            messages.success(
                request,
                f"Imported {counts['stock_items']} stock entries — {counts['parts_new']} new parts, "
                f"{counts['containers_new']} new containers, {counts['drawers_new']} new drawers, "
                f"{counts['locations_new']} new locations.",
            )
            return redirect("inventory:import_csv")

        # Upload step.
        upload = request.FILES.get("csv_file")
        if not upload:
            messages.error(request, "No file received.")
            return redirect("inventory:import_csv")

        rows, fatal = parse_csv(upload.read())
        if fatal:
            for err in fatal:
                messages.error(request, err)
            return redirect("inventory:import_csv")
        if not rows:
            messages.error(request, "The file had a header but no data rows.")
            return redirect("inventory:import_csv")

        analysis = analyze_rows(rows)

        fd, path = tempfile.mkstemp(suffix=".json", prefix="sethsparts-import-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        request.session["csv_import_path"] = path

        return render(
            request,
            "inventory/import_csv_preview.html",
            {
                "counts": analysis["counts"],
                "errors": analysis["errors"],
                "total_rows": len(rows),
            },
        )

    return render(request, "inventory/import_csv.html")
