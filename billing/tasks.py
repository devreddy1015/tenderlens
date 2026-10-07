"""Billing background jobs: talking to Razorpay outside the webhook request."""

import logging

from celery import shared_task

from billing import services
from billing.models import Subscription

log = logging.getLogger(__name__)


@shared_task(
    bind=True,
    acks_late=True,
    autoretry_for=(services.ProviderError,),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=10,
)
def cancel_at_provider(self, subscription_pk: int) -> str:
    """Cancel a superseded subscription at Razorpay (services._supersede_razorpay). Safe to
    run twice: Razorpay's "already cancelled" counts as success. Network and 5xx errors are
    retried with backoff for about a day; after that the failure is logged for a human."""
    sub = Subscription.objects.filter(pk=subscription_pk).first()
    if sub is None or sub.provider != Subscription.Provider.RAZORPAY:
        return "skipped"
    if not sub.provider_subscription_id:
        return "skipped: no provider id"
    try:
        result = services.cancel_razorpay_now(sub.provider_subscription_id)
    except services.ProviderError:
        if self.request.retries >= self.max_retries:
            log.error(
                "billing: giving up cancelling Razorpay subscription %s (local %s); cancel "
                "it in the Razorpay dashboard",
                sub.provider_subscription_id,
                sub.pk,
            )
        raise
    except services.BillingUnavailable:
        log.error("billing: Razorpay keys missing; cannot cancel %s", sub.provider_subscription_id)
        return "skipped: billing not configured"
    log.info(
        "billing: Razorpay subscription %s cancelled (%s)", sub.provider_subscription_id, result
    )
    return result
