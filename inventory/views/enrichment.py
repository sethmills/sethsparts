"""The enrichment queue, inventory export, and the resistor decoder."""
import os
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..site_config import site_name
from ..models import (
    Part,
)



# --- Enrichment queue ---------------------------------------------------------
# The actual research (finding a product page, pinout, datasheet, price) needs a live
# agent making real web requests -- nothing the deployed app can run unattended for
# free on a schedule. What *is* buildable and safe to trigger from here: reclassifying
# candidates (pure DB logic), exporting a worklist for that research pass, and
# importing the finished results -- so the only manual step is asking Claude to
# process the exported file, not SSHing in to run management commands by hand.

@login_required
def enrichment_queue(request):
    from django.db.models import Count as _Count  # local alias, avoids shadowing concerns

    raw_counts = dict(Part.objects.values_list("enrichment_status").annotate(n=_Count("id")))
    status_counts = [(label, raw_counts.get(value, 0)) for value, label in Part.ENRICHMENT_CHOICES]
    pending = Part.objects.filter(enrichment_status=Part.ENRICHMENT_PENDING).select_related("category")
    needs_review = Part.objects.filter(enrichment_status=Part.ENRICHMENT_NEEDS_REVIEW).select_related("category")
    needs_clarification = Part.objects.filter(enrichment_status=Part.ENRICHMENT_NEEDS_CLARIFICATION).select_related("category")

    return render(
        request,
        "inventory/enrichment_queue.html",
        {
            "status_counts": status_counts,
            "pending": pending,
            "needs_review": needs_review,
            "needs_clarification": needs_clarification,
        },
    )


@login_required
def run_enrichment_classification(request):
    if request.method == "POST":
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("classify_enrichment_queue", stdout=out)
        messages.success(request, out.getvalue().replace("\n", " · ").strip(" ·"))
    return redirect("inventory:enrichment_queue")


@login_required
def export_enrichment_worklist(request):
    """A JSON list of pending parts for a research pass to work from -- id + whatever's
    already known, so the research doesn't start from nothing. Not the same shape
    ingest_enrichment expects back (that's the *output* of research); this is the input."""
    parts = Part.objects.filter(enrichment_status=Part.ENRICHMENT_PENDING).select_related("category")
    worklist = [
        {
            "id": part.id,
            "name": part.name,
            "category": part.category.name if part.category else None,
            "manufacturer": part.manufacturer,
            "description": part.description,
        }
        for part in parts
    ]
    response = JsonResponse(worklist, safe=False, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = "attachment; filename=enrichment_worklist.json"
    return response


@login_required
def import_enrichment_results(request):
    if request.method == "POST":
        upload = request.FILES.get("results_file")
        if not upload:
            messages.error(request, "No file received.")
            return redirect("inventory:enrichment_queue")

        import tempfile
        from io import StringIO

        from django.core.management import call_command

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        out = StringIO()
        try:
            call_command("ingest_enrichment", tmp_path, stdout=out)
            messages.success(request, out.getvalue().replace("\n", " · ").strip(" ·"))
        except Exception as exc:
            messages.error(request, f"Import failed: {exc}")
        finally:
            os.unlink(tmp_path)
    return redirect("inventory:enrichment_queue")


# --- Phase 6: Export ----------------------------------------------------------

@login_required
def export_inventory(request):
    import io
    import zipfile
    from datetime import datetime
    from pathlib import Path

    from django.conf import settings
    from django.http import FileResponse

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = settings.DATABASES["default"]["NAME"]
        if Path(db_path).exists():
            zf.write(db_path, arcname="db.sqlite3")

        media_root = Path(settings.MEDIA_ROOT)
        if media_root.exists():
            for file_path in media_root.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, arcname=str(Path("media") / file_path.relative_to(media_root)))

        readme = (
            f"{site_name()} export\n"
            "=====================\n"
            "To restore: drop db.sqlite3 into a fresh checkout of the tor-inventory project\n"
            "(replacing its empty one) and copy media/ alongside it, then run migrate as normal.\n"
            "This only works for the SQLite dev setup — a Postgres deployment needs its own\n"
            "restore path (pg_restore from a pg_dump), not this file.\n"
        )
        zf.writestr("README.txt", readme)

    buffer.seek(0)
    filename = f"tor-inventory-export-{datetime.now():%Y%m%d-%H%M%S}.zip"
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type="application/zip")


# --- Reference section --------------------------------------------------------
#
# The reference library's views live in inventory/views/reference.py now that it is
# something the owner edits rather than a fixed list. This signpost stays because this
# is where people will look for it.


@login_required
def resistor_calculator(request):
    return render(request, "inventory/resistor_calculator.html")
