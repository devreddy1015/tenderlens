"""Alert digests. Runs after every crawl run finishes, and hourly as a fallback.

Per subscription: find open tenders first seen since its high-water mark that it has not
been sent before, email one digest, then record the deliveries and advance the mark.
If the email fails, nothing is recorded, so the next run retries the same tenders.
"""

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from alerts import emails, matching
from alerts.models import AlertDelivery, AlertSubscription

log = logging.getLogger(__name__)

MAX_PER_EMAIL = 25


def send_for_subscription(sub: AlertSubscription, *, now=None) -> int:
    """Send this subscription's digest if there is anything new. Returns tenders sent."""
    now = now or timezone.now()
    first = sub.checked_until is None
    qs = matching.for_subscription(
        sub, first_seen_after=sub.checked_until, first_seen_until=now, now=now
    )
    qs = qs.exclude(pk__in=AlertDelivery.objects.filter(subscription=sub).values("tender_id"))
    total = qs.count()
    tenders = list(qs[:MAX_PER_EMAIL])
    if tenders:
        emails.build_digest(sub, tenders, first=first, total=total).send()
        with transaction.atomic():
            AlertDelivery.objects.bulk_create(
                [AlertDelivery(subscription=sub, tender=t) for t in tenders], ignore_conflicts=True
            )
            AlertSubscription.objects.filter(pk=sub.pk).update(checked_until=now, last_sent_at=now)
    else:
        AlertSubscription.objects.filter(pk=sub.pk).update(checked_until=now)
    return len(tenders)


def send_test(sub: AlertSubscription) -> int:
    """'Send me a test': what is open right now, recorded nowhere."""
    qs = matching.for_subscription(sub)
    total = qs.count()
    tenders = list(qs[:5])
    emails.build_digest(sub, tenders, first=True, total=total, test=True).send()
    return total


@shared_task(bind=True, autoretry_for=(OSError,), retry_backoff=60, max_retries=5)
def send_alerts(self) -> dict:
    sent = failed = 0
    ids = list(AlertSubscription.objects.filter(active=True).values_list("pk", flat=True))
    for pk in ids:
        with transaction.atomic():
            # skip_locked: two overlapping runs never process the same subscription.
            sub = (
                AlertSubscription.objects.select_for_update(skip_locked=True)
                .select_related("user")
                .filter(pk=pk, active=True)
                .first()
            )
            if sub is None:
                continue
            try:
                sent += send_for_subscription(sub)
            except Exception:
                failed += 1
                log.exception("alert %s failed; will retry on the next run", pk)
    if failed and not sent:
        raise OSError(f"{failed} alert digests failed")  # likely SMTP down: retry with backoff
    return {"subscriptions": len(ids), "tenders_sent": sent, "failed": failed}


@shared_task
def send_first_digest(subscription_id: int) -> int:
    sub = AlertSubscription.objects.select_related("user").get(pk=subscription_id)
    return send_for_subscription(sub)
