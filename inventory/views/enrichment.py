"""The enrichment queue, inventory export, and the resistor decoder."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .. import enrichment_ai, research
from ..site_config import site_name
from ..models import (
    Category,
    Part,
)



# --- Enrichment queue ---------------------------------------------------------
# Enrichment is all in-app: local keyword classification, a DeepSeek triage pass, and
# DeepSeek + Tavily research (product page, datasheet, price) all run from the queue —
# no export/import round-trip, no external agent.

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
            "status_choices": Part.ENRICHMENT_CHOICES,
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


# --- In-app enrichment (DeepSeek) ---------------------------------------------
# DeepSeek enriches the descriptive fields and triages candidates in one shot; when a
# Tavily key is set, research.py does the actual web search and DeepSeek reads the
# results — so the whole enrichment pipeline runs in-app, no external agent.

def _apply_suggestion(part, suggestion):
    """Apply a DeepSeek suggestion to a part. A suggestion with a category and at least
    one other fact is applied as done; a thin one is flagged for review rather than
    trusted blindly."""
    if not suggestion:
        return
    if suggestion.get("category"):
        category, _ = Category.objects.get_or_create(name=suggestion["category"])
        part.category = category
        if category.name.lower() == "electronics":
            part.is_electronic = True
    if suggestion.get("description"):
        part.description = suggestion["description"]
    if suggestion.get("manufacturer"):
        part.manufacturer = suggestion["manufacturer"]
    confident = bool(suggestion.get("category") and (suggestion.get("description") or suggestion.get("manufacturer")))
    part.enrichment_status = Part.ENRICHMENT_DONE if confident else Part.ENRICHMENT_NEEDS_REVIEW
    part.save(update_fields=["category", "description", "manufacturer", "is_electronic", "enrichment_status"])


def _apply_research(part, data):
    """Apply web-research findings to a part: the descriptive fields plus the product
    and datasheet URLs the search actually surfaced."""
    if data.get("category"):
        category, _ = Category.objects.get_or_create(name=data["category"])
        part.category = category
        if category.name.lower() == "electronics":
            part.is_electronic = True
    if data.get("description"):
        part.description = data["description"]
    if data.get("manufacturer"):
        part.manufacturer = data["manufacturer"]
    if data.get("product_url"):
        part.reorder_url = data["product_url"]
    if data.get("datasheet_url"):
        part.datasheet_url = data["datasheet_url"]
    confident = data.get("confidence") == "high" and bool(data.get("product_url") or data.get("manufacturer"))
    part.enrichment_status = Part.ENRICHMENT_DONE if confident else Part.ENRICHMENT_NEEDS_REVIEW
    part.save(
        update_fields=["category", "description", "manufacturer", "is_electronic", "reorder_url", "datasheet_url", "enrichment_status"]
    )


@login_required
def flag_part_for_enrichment(request, pk):
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        part.enrichment_status = Part.ENRICHMENT_PENDING
        part.save(update_fields=["enrichment_status"])
        messages.success(request, f"Flagged “{part.name}” for enrichment.")
    return redirect("inventory:part_detail", pk=part.pk)


@login_required
def bulk_classify(request):
    """Reclassify many parts straight from the queue — no clicking into each one.

    One POST carries `status_<pk> = <status>` pairs from the inline dropdowns."""
    if request.method == "POST":
        valid = dict(Part.ENRICHMENT_CHOICES)
        changed = 0
        for key, value in request.POST.items():
            if not key.startswith("status_") or value not in valid:
                continue
            pk = key[len("status_"):]
            changed += Part.objects.filter(pk=pk).update(enrichment_status=value)
        messages.success(request, f"Updated {changed} part{'s' if changed != 1 else ''}.")
    return redirect("inventory:enrichment_queue")


@login_required
def enrich_pending_with_ai(request):
    """Run enrichment over every pending part, in-app, and apply it — the
    export-to-Claude loop replaced with one click. When a search key is configured it
    does the full web research (product page, datasheet, description); otherwise it
    falls back to descriptive-only suggestions."""
    if request.method != "POST":
        return redirect("inventory:enrichment_queue")
    if not enrichment_ai.is_configured():
        messages.error(request, "DeepSeek isn't configured — set your key under Settings → Research & AI.")
        return redirect("inventory:enrichment_queue")

    use_research = research.is_configured()
    parts = Part.objects.filter(enrichment_status=Part.ENRICHMENT_PENDING).select_related("category")
    enriched = review = failed = 0
    for part in parts:
        if use_research:
            data, error = research.research_part(
                part.name, part.category.name if part.category else None, part.description, part.manufacturer
            )
            if error:
                failed += 1
                continue
            _apply_research(part, data)
        else:
            suggestion, error = enrichment_ai.suggest_enrichment(
                part.name, part.category.name if part.category else None, part.description, part.manufacturer
            )
            if error:
                failed += 1
                continue
            _apply_suggestion(part, suggestion)

        if part.enrichment_status == Part.ENRICHMENT_DONE:
            enriched += 1
        else:
            review += 1

    mode = "researched" if use_research else "enriched"
    messages.success(
        request,
        f"{mode.capitalize()} {enriched} part(s), flagged {review} for review, {failed} failed, of {parts.count()} pending.",
    )
    return redirect("inventory:enrichment_queue")


@login_required
def ai_scan_candidates(request):
    """One DeepSeek pass over every not-yet-enriched part to flag candidates — the
    AI-driven version of the local keyword classify. Cost-controlled: one model call
    per chunk of names, and triggered by hand, never on a schedule."""
    if request.method != "POST":
        return redirect("inventory:enrichment_queue")
    if not enrichment_ai.is_configured():
        messages.error(request, "DeepSeek isn't configured — set DEEPSEEK_API_KEY.")
        return redirect("inventory:enrichment_queue")

    names = list(Part.objects.filter(enrichment_status=Part.ENRICHMENT_NOT_NEEDED).values_list("name", flat=True))
    status_map = {
        "pending": Part.ENRICHMENT_PENDING,
        "needs_clarification": Part.ENRICHMENT_NEEDS_CLARIFICATION,
        "not_needed": Part.ENRICHMENT_NOT_NEEDED,
    }
    pending = clarification = 0
    for i in range(0, len(names), 100):
        chunk = names[i : i + 100]
        result, error = enrichment_ai.ai_classify_candidates(chunk)
        if error:
            messages.error(request, error)
            return redirect("inventory:enrichment_queue")
        for part in Part.objects.filter(enrichment_status=Part.ENRICHMENT_NOT_NEEDED, name__in=chunk):
            new_status = status_map[result.get(part.name, "not_needed")]
            if new_status == Part.ENRICHMENT_NOT_NEEDED:
                continue
            part.enrichment_status = new_status
            part.save(update_fields=["enrichment_status"])
            if new_status == Part.ENRICHMENT_PENDING:
                pending += 1
            else:
                clarification += 1

    messages.success(request, f"AI scan done: flagged {pending} candidate(s) and {clarification} for clarification.")
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
