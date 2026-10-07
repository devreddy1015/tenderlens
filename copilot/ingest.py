"""Document -> pages -> chunks -> embeddings, stored in Postgres (pgvector).

process() is idempotent: a ready document is left alone, and a re-run (a retry after a
crash, a manual reprocess) replaces the chunks in one transaction, so a document never ends up
with half its chunks or with two copies of them.
"""

import hashlib
import logging
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from copilot import embeddings, grounding
from copilot.chunking import chunk_pages, document_context
from copilot.extract import Page, extract
from copilot.models import Chunk, Document

log = logging.getLogger(__name__)

MAX_PAGES = 500  # longer files are almost always scanned annexure bundles; refuse politely
ERROR_NO_TEXT = (
    "No text could be read from this PDF. It is probably a scan, and OCR is not available "
    "on this server."
)


def sha256_of(fileobj) -> str:
    h = hashlib.sha256()
    blocks = (
        fileobj.chunks() if hasattr(fileobj, "chunks") else iter(lambda: fileobj.read(1 << 20), b"")
    )
    for block in blocks:
        h.update(block)
    if hasattr(fileobj, "seek"):
        fileobj.seek(0)
    return h.hexdigest()


def passage_text(heading: str, text: str, context: str = "") -> str:
    """Embed "context + heading + text": the heading often carries the meaning ("EMD",
    "Turnover"), the context says which tender it is. Context comes first so the model's
    512-token window never truncates it away. (e5's "passage: " prefix is added by
    embeddings.embed_passages.)"""
    body = f"{heading}\n{text}" if heading and not text.startswith(heading) else text
    return f"{context}\n{body}" if context else body


def process(doc: Document, *, force: bool = False, path: Path | None = None) -> Document:
    """path: read this file instead of doc.file (the evaluation ingests in place)."""
    if doc.status == Document.Status.READY and not force and doc.chunks.exists():
        return doc
    try:
        ex = extract(path or Path(doc.file.path))
        if len(ex.pages) > MAX_PAGES:
            raise ValueError(f"The PDF has {len(ex.pages)} pages; the limit is {MAX_PAGES}.")
        chunks = chunk_pages(ex.pages)
        if not chunks:
            raise ValueError(ERROR_NO_TEXT)
        context = document_context(ex.pages, tender=doc.tender)
        vectors = embeddings.embed_passages(
            [passage_text(c.heading, c.text, context) for c in chunks]
        )
        with transaction.atomic():
            Chunk.objects.filter(document=doc).delete()
            Chunk.objects.bulk_create(
                Chunk(
                    document=doc,
                    ord=c.ord,
                    page_from=c.page_from,
                    page_to=c.page_to,
                    heading=c.heading[:500],
                    context=context,
                    text=c.text,
                    tokens=c.tokens,
                    embedding=v,
                )
                for c, v in zip(chunks, vectors, strict=True)
            )
            doc.pages, doc.ocr_pages = len(ex.pages), ex.ocr_pages
            doc.page_texts = [p.text for p in ex.pages]
            doc.status, doc.error, doc.processed_at = Document.Status.READY, "", timezone.now()
            doc.save(
                update_fields=[
                    "pages",
                    "ocr_pages",
                    "page_texts",
                    "status",
                    "error",
                    "processed_at",
                ]
            )
    except Exception as exc:
        log.exception("copilot: processing document %s failed", doc.pk)
        message = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
        doc.status, doc.error, doc.processed_at = Document.Status.FAILED, message[:2000], None
        doc.save(update_fields=["status", "error", "processed_at"])
        return doc
    try:
        fill_tender_prebid(doc)
    except Exception:  # a convenience for the calendar; never fails the document
        log.exception("copilot: pre-bid date of document %s not stored", doc.pk)
    return doc


def stored_pages(doc: Document) -> list[Page]:
    return [Page(number=i, text=t) for i, t in enumerate(doc.page_texts or [], start=1)]


def reindex(doc: Document) -> int:
    """Recompute a ready document's chunk context and embeddings from its stored page texts,
    without re-reading the PDF: for chunks written before Chunk.context existed, after the
    document is linked to a tender, or after the context rules or the embedding model
    change. The tsvector follows by itself (generated column). Returns chunks updated."""
    chunks = list(doc.chunks.order_by("ord"))
    if not chunks:
        return 0
    context = document_context(stored_pages(doc), tender=doc.tender)
    vectors = embeddings.embed_passages([passage_text(c.heading, c.text, context) for c in chunks])
    for c, v in zip(chunks, vectors, strict=True):
        c.context, c.embedding = context, v
    with transaction.atomic():
        Chunk.objects.bulk_update(chunks, ["context", "embedding"], batch_size=200)
    return len(chunks)


# --- pre-bid meeting -> Tender ----------------------------------------------------------
IST = ZoneInfo("Asia/Kolkata")
_CLOCK = re.compile(
    r"(?<![\d.:])(\d{1,2})[:.](\d{2})(?![\d.:])\s*(?:([ap])\.?\s*m\b\.?|hrs\b|hours\b)?", re.I
)


def brief_datetime(value: str) -> datetime | None:
    """ "03-Oct-2026 at 11:00 AM" / "15.10.2026, 15:00 hrs" -> aware IST datetime. None unless
    the value holds exactly one date and one clock time: a date alone ("October 1, 2026")
    would put the meeting at midnight."""
    dates = [f for f in grounding.facts(value) if f.kind == "date"]
    if len(dates) != 1:
        return None
    rest = value.replace(dates[0].text, " ")
    clocks = list(_CLOCK.finditer(rest))
    if len(clocks) != 1:
        return None
    hour, minute, meridiem = int(clocks[0][1]), int(clocks[0][2]), (clocks[0][3] or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "p" else 0)
    if hour > 23 or minute > 59:
        return None
    return datetime.combine(dates[0].value, time(hour, minute), tzinfo=IST)


def _mentions(text: str, needle: str) -> bool:
    return bool(needle) and len(needle) >= 6 and " ".join(needle.split()).lower() in text


def fill_tender_prebid(doc: Document) -> datetime | None:
    """Store the Bid Brief's pre-bid meeting on the linked Tender when the portal gave none,
    so the pipeline calendar can show it. Tender data is shared by every customer, so the
    value must be confident: an exact date and time, inside the tender's own window
    (published .. bid submission end), read from a document that names the tender's ID or
    reference number (an unrelated PDF attached to the wrong tender changes nothing)."""
    from copilot.brief import document_fields
    from tenders.models import Tender

    tender = doc.tender
    if tender is None or tender.prebid_meeting is not None:
        return None
    field = document_fields(doc).get("prebid_meeting")
    when = brief_datetime(field.value) if field else None
    if when is None:
        return None
    if not (tender.published_at - timedelta(days=1) <= when <= tender.closes_at):
        return None
    text = " ".join(" ".join(doc.page_texts or []).split()).lower()
    if not (_mentions(text, tender.source_tender_id) or _mentions(text, tender.ref_no)):
        return None
    updated = Tender.objects.filter(pk=tender.pk, prebid_meeting__isnull=True).update(
        prebid_meeting=when
    )
    return when if updated else None


def max_upload_bytes() -> int:
    return settings.COPILOT_MAX_UPLOAD_MB * 1024 * 1024
