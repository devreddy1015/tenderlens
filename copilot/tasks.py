"""Celery tasks. Uploads return at once; reading, OCR and embedding run here."""

import logging

from celery import shared_task

from copilot import ingest
from copilot.models import Document

log = logging.getLogger(__name__)


@shared_task(acks_late=True)
def process_document(document_id: int, force: bool = False) -> str:
    """Idempotent (see copilot.ingest.process): a redelivered task finds the document ready
    and returns. A failure is recorded on the document (status "failed", error) and the
    month's document quota is given back, since the customer got nothing for it."""
    doc = Document.objects.select_related("organization").filter(pk=document_id).first()
    if doc is None:  # deleted before the worker got to it
        return "missing"
    doc = ingest.process(doc, force=force)
    if doc.status == Document.Status.FAILED:
        from billing.entitlements import period, refund

        if period(doc.created_at) == period():
            refund(doc.organization, "documents_per_month")
    return doc.status
