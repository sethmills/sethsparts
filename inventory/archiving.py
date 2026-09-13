"""Archive external documents, so they are still here when the internet moves on.

Datasheets for obscure parts disappear constantly: small manufacturers redesign their
websites, hobby shops close, forum attachment links rot, and a product page that
worked last year returns a 404 today. A link is not a document. So anything this app
links out to can be fetched once and kept locally, and **the local copy becomes what
the app actually serves and displays** — the original URL is kept as provenance, not
as the thing you depend on.

Why a shared module rather than a helper in each caller: part attachments and reference
documents both need exactly this, and the parts that make it safe (a size cap, a scheme
allowlist, recording *why* a fetch failed) are the parts that get forgotten when the
logic is copied and pasted.

**What this deliberately does not archive:**
- **Repurchase links** (`Part.reorder_url`). Those are a live action, not a document.
  A cached product page would show a stale price, which is worse than no page at all.
- **Anything that isn't a document.** A fetch returning HTML is stored honestly as a
  product page, but what actually came back is recorded — so a login wall or a bot
  block shows up as a login wall or a bot block, not as a datasheet.

**On legality, in the place a future reader will look:** a local copy here is for the
owner's own reference, the equivalent of printing a datasheet and filing it. The
shipped starter set contains **links only and no files**, so this repository never
redistributes anyone's PDF; each install archives its own copies of what it keeps.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

# Identifies the app honestly to the server being asked for a file. A generic browser
# string would be a lie about who is calling.
USER_AGENT = "Mozilla/5.0 (compatible; WorkshopParts/1.0; personal workshop archive)"

ALLOWED_SCHEMES = ("http", "https")

# A scanned datasheet rarely exceeds a few MB; this is high enough not to mangle real
# documents and low enough that one bad URL cannot fill the disk.
DEFAULT_MAX_BYTES = 40 * 1024 * 1024
DEFAULT_TIMEOUT = 20

EXTENSION_BY_TYPE = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/tiff": ".tiff",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/html": ".html",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

# Extensions we will trust from a URL over the content type, because a PDF served as
# application/octet-stream is common and its URL almost always ends in .pdf.
TRUSTED_URL_EXTENSIONS = (
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".tif", ".tiff",
    ".txt", ".csv", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".html", ".htm",
)


@dataclass
class ArchiveResult:
    """Outcome of one attempt. `error` is written for a human to read."""

    ok: bool
    content: bytes = b""
    filename: str = ""
    content_type: str = ""
    final_url: str = ""
    status_code: int | None = None
    error: str = ""

    @property
    def is_html(self) -> bool:
        return self.content_type.startswith("text/html")


def _short(message, limit=280) -> str:
    text = re.sub(r"\s+", " ", str(message)).strip()
    return text[:limit]


def filename_for(url: str, content_type: str) -> str:
    """A safe filename for the stored copy.

    Prefers the URL's own name — that is what the publisher called it, and someone
    opening the media folder later will recognise it. Falls back to the content type,
    and only then to something generic.
    """
    stem = ""
    path = urlparse(url).path or ""
    if path:
        candidate = unquote(path.rstrip("/").rsplit("/", 1)[-1])
        # Strip anything that could escape the upload directory or upset a filesystem.
        candidate = re.sub(r"[^A-Za-z0-9._-]", "_", candidate).lstrip(".")
        if candidate and "." in candidate:
            stem = candidate[:120]

    if not stem:
        ext = EXTENSION_BY_TYPE.get(content_type, "") or ".bin"
        stem = f"document{ext}"

    return stem


def fetch(url: str, *, timeout: int = DEFAULT_TIMEOUT, max_bytes: int = DEFAULT_MAX_BYTES) -> ArchiveResult:
    """Download a document. Never raises: a dead link is expected input, not a crash."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        return ArchiveResult(
            ok=False,
            error=f"Only http and https links can be archived (got “{parsed.scheme or 'no scheme'}”).",
        )
    if not parsed.netloc:
        return ArchiveResult(ok=False, error="That link has no host in it.")

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            timeout=timeout,
            stream=True,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return ArchiveResult(ok=False, error=_short(exc))

    try:
        if response.status_code >= 400:
            return ArchiveResult(
                ok=False,
                status_code=response.status_code,
                error=f"The source returned HTTP {response.status_code}.",
            )

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                return ArchiveResult(
                    ok=False,
                    status_code=response.status_code,
                    error=f"The file is larger than {max_bytes // (1024 * 1024)} MB.",
                )
            chunks.append(chunk)
        content = b"".join(chunks)
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        final_url = response.url or url
    finally:
        # Releases the connection. Without this, a large streamed response holds a
        # socket open until garbage collection.
        response.close()

    if not content:
        return ArchiveResult(ok=False, status_code=200, error="The source returned an empty response.")

    # A URL ending in a known document extension is better evidence of what this is
    # than an octet-stream content type, which many servers use for PDFs.
    url_ext = urlparse(final_url).path.lower().rsplit(".", 1)
    if content_type in ("application/octet-stream", "") and len(url_ext) == 2:
        if f".{url_ext[1]}" in TRUSTED_URL_EXTENSIONS:
            content_type = {
                "pdf": "application/pdf",
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
            }.get(url_ext[1], content_type)

    return ArchiveResult(
        ok=True,
        content=content,
        filename=filename_for(final_url, content_type),
        content_type=content_type,
        final_url=final_url,
        status_code=response.status_code,
    )


def archive_on_save_enabled() -> bool:
    return bool(getattr(settings, "ARCHIVE_ON_SAVE", True))


def archive_timeout() -> int:
    return int(getattr(settings, "ARCHIVE_TIMEOUT", DEFAULT_TIMEOUT))


# --- The two models that hold documents --------------------------------------


def archive_reference_doc(doc, *, timeout: int | None = None) -> ArchiveResult:
    """Fetch and store the local copy for a reference document."""
    if not doc.external_url:
        return ArchiveResult(ok=False, error="No source link to archive.")
    return _store(doc, doc.external_url, timeout=timeout)


def archive_attachment(attachment, *, timeout: int | None = None) -> ArchiveResult:
    """Fetch and store the local copy for a part attachment."""
    if not attachment.source_url:
        return ArchiveResult(ok=False, error="No source link to archive.")
    return _store(attachment, attachment.source_url, timeout=timeout)


def _store(obj, url: str, *, timeout: int | None = None) -> ArchiveResult:
    """Fetch, save the file onto `obj`, and record what happened.

    The outcome is always recorded on the row, success or failure. A reference whose
    source is a login wall is worth keeping as a link — it just has to be honest that
    that is all it is, rather than looking like a cached document that isn't there.
    """
    timeout = archive_timeout() if timeout is None else timeout
    result = fetch(url, timeout=timeout)

    obj.archive_attempted_at = timezone.now()
    if result.ok:
        obj.file.save(result.filename, ContentFile(result.content), save=False)
        obj.archived_at = timezone.now()
        obj.archive_content_type = result.content_type
        obj.archive_error = ""
    else:
        obj.archive_error = result.error[:300]

    obj.save(update_fields=["file", "archived_at", "archive_content_type", "archive_error", "archive_attempted_at"])
    return result
