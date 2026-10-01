import logging

from celery import shared_task
from django.conf import settings

from tenders import search
from tenders.models import Tender

log = logging.getLogger(__name__)


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=5,
    ignore_result=True,
)
def index_tender(tender_id: int) -> None:
    """Re-index one tender after it is upserted. Idempotent: the ES doc id is the row id."""
    if not settings.ES_ENABLED:
        return
    tender = Tender.objects.select_related("buyer_entity").filter(pk=tender_id).first()
    if tender is None:
        search.delete_one(tender_id)
        return
    search.index_one(tender)
