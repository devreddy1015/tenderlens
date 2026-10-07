"""Subscriptions: checkout, cancellation and Razorpay webhooks.

Organization.plan_code is never set directly by billing code paths: every change goes
through sync_plan(), which derives it from the organisation's subscriptions, so the plan
always matches what the customer is paying for.

Razorpay flow: POST checkout creates a Razorpay subscription (Subscriptions API) and a
local row in "created"; the browser opens Razorpay Checkout with its id; Razorpay then
sends signed webhooks (subscription.activated / charged / cancelled / ...) which move the
row's status. Payment details never touch our servers.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import UTC, datetime, timedelta

import httpx
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from billing.models import Subscription, WebhookEvent
from billing.plans import DEFAULT_PLAN, PLANS
from workspaces.models import Organization

log = logging.getLogger(__name__)
RAZORPAY_API = "https://api.razorpay.com/v1"
# Renewals Razorpay schedules for a subscription (it needs a finite total_count).
TOTAL_COUNT = {"month": 120, "year": 10}
ACTIVATE = {"subscription.activated", "subscription.charged", "subscription.resumed"}
DEACTIVATE = {"subscription.cancelled", "subscription.halted", "subscription.completed"}
STATUS_FOR = {
    "subscription.authenticated": Subscription.Status.CREATED,
    "subscription.pending": Subscription.Status.PENDING,
    "subscription.cancelled": Subscription.Status.CANCELLED,
    "subscription.halted": Subscription.Status.HALTED,
    "subscription.completed": Subscription.Status.COMPLETED,
    "subscription.paused": Subscription.Status.HALTED,
}


class BillingUnavailable(APIException):
    status_code = 503
    default_detail = "Payments are not configured on this server."
    default_code = "billing_unavailable"


class ProviderError(APIException):
    status_code = 502
    default_detail = "The payment provider did not respond. Please try again."
    default_code = "provider_error"


def sync_plan(org: Organization) -> str:
    """Set org.plan_code from its newest entitling subscription (else free)."""
    sub = current_subscription(org, entitled_only=True)
    code = sub.plan_code if sub is not None and sub.plan_code in PLANS else DEFAULT_PLAN
    if org.plan_code != code:
        org.plan_code = code
        org.save(update_fields=["plan_code"])
    return code


def current_subscription(org: Organization, *, entitled_only: bool = False):
    qs = Subscription.objects.filter(organization=org)
    if entitled_only:
        qs = qs.filter(status__in=Subscription.ENTITLED)
    else:  # the one to show: entitling first, then the newest
        entitled = qs.filter(status__in=Subscription.ENTITLED).order_by("-updated_at", "-id")
        return entitled.first() or qs.order_by("-created_at", "-id").first()
    return qs.order_by("-updated_at", "-id").first()


def _period_end(interval: str, start=None) -> datetime:
    start = start or timezone.now()
    return start + (timedelta(days=365) if interval == "year" else timedelta(days=30))


def razorpay_plan_id(code: str, interval: str) -> str:
    """Razorpay plan id for (plan, interval): settings.RAZORPAY_PLAN_IDS, filled from env
    RAZORPAY_PLAN_<CODE>_<INTERVAL> (e.g. RAZORPAY_PLAN_PRO_MONTH)."""
    key = f"{code}_{interval}".upper()
    plan_id = settings.RAZORPAY_PLAN_IDS.get(key) or os.environ.get(f"RAZORPAY_PLAN_{key}", "")
    if not plan_id:
        raise BillingUnavailable(f"No Razorpay plan is configured for {code} ({interval}).")
    return plan_id


def plan_for_razorpay_id(plan_id: str) -> tuple[str, str] | None:
    for key, value in settings.RAZORPAY_PLAN_IDS.items():
        if value and value == plan_id:
            code, _, interval = key.lower().rpartition("_")
            return code, interval
    return None


def _razorpay_auth() -> tuple[str, str]:
    if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        raise BillingUnavailable()
    return settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET


def _razorpay(method: str, path: str, payload: dict) -> dict:
    try:
        resp = httpx.request(
            method, f"{RAZORPAY_API}{path}", json=payload, auth=_razorpay_auth(), timeout=20
        )
    except httpx.HTTPError as exc:
        log.warning("razorpay %s %s failed: %s", method, path, exc)
        raise ProviderError() from exc
    if resp.status_code >= 400:
        log.warning("razorpay %s %s -> %s %s", method, path, resp.status_code, resp.text[:500])
        raise ProviderError()
    return resp.json()


def checkout(org: Organization, user, code: str, interval: str) -> dict:
    plan = PLANS.get(code)
    if plan is None:
        raise ValidationError({"plan": "Unknown plan."})
    if interval not in TOTAL_COUNT:
        raise ValidationError({"interval": "month or year."})
    price = plan.price_inr_month if interval == "month" else plan.price_inr_year
    if price is None:
        raise ValidationError({"plan": f"{plan.name} is sold by contract. Contact us."})
    if price == 0:
        raise ValidationError({"plan": "The free plan needs no checkout. Cancel instead."})
    provider = settings.BILLING_PROVIDER
    if provider == "fake":
        with transaction.atomic():
            _end_others(org, keep=None)
            Subscription.objects.create(
                organization=org,
                plan_code=code,
                interval=interval,
                status=Subscription.Status.ACTIVE,
                provider=Subscription.Provider.FAKE,
                provider_subscription_id=f"fake_{secrets.token_hex(8)}",
                current_period_end=_period_end(interval),
            )
            sync_plan(org)
        return {"provider": "fake", "activated": True}
    if provider != "razorpay":
        raise BillingUnavailable()
    data = _razorpay(
        "POST",
        "/subscriptions",
        {
            "plan_id": razorpay_plan_id(code, interval),
            "total_count": TOTAL_COUNT[interval],
            "customer_notify": 1,
            "notes": {"organization_id": str(org.pk), "plan": code, "interval": interval},
        },
    )
    Subscription.objects.create(
        organization=org,
        plan_code=code,
        interval=interval,
        status=Subscription.Status.CREATED,
        provider=Subscription.Provider.RAZORPAY,
        provider_subscription_id=data["id"],
    )
    return {
        "provider": "razorpay",
        "key_id": settings.RAZORPAY_KEY_ID,
        "subscription_id": data["id"],
        "short_url": data.get("short_url"),
    }


def _end_others(org: Organization, keep: Subscription | None) -> None:
    """A new fake/manual subscription replaces the previous local ones."""
    qs = Subscription.objects.filter(
        organization=org,
        status__in=[*Subscription.ENTITLED, Subscription.Status.CREATED],
        provider__in=[Subscription.Provider.FAKE, Subscription.Provider.MANUAL],
    )
    if keep is not None:
        qs = qs.exclude(pk=keep.pk)
    qs.update(status=Subscription.Status.CANCELLED, updated_at=timezone.now())


def cancel(org: Organization) -> Subscription | None:
    """Cancel the current subscription. Razorpay: at the end of the paid period (the plan
    stays until Razorpay's subscription.cancelled webhook); fake/manual: immediately."""
    sub = current_subscription(org, entitled_only=True)
    if sub is None:
        raise ValidationError({"detail": "There is no active subscription to cancel."})
    if sub.provider == Subscription.Provider.RAZORPAY:
        _razorpay(
            "POST",
            f"/subscriptions/{sub.provider_subscription_id}/cancel",
            {"cancel_at_cycle_end": 1},
        )
        sub.cancel_at_period_end = True
        sub.save(update_fields=["cancel_at_period_end", "updated_at"])
    else:
        sub.status = Subscription.Status.CANCELLED
        sub.save(update_fields=["status", "updated_at"])
        sync_plan(org)
    return sub


# --- webhook ------------------------------------------------------------------------------


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def handle_webhook(body: bytes, event_id: str) -> str:
    """Apply one verified Razorpay webhook delivery; returns what happened. Idempotent per
    event id: a redelivery is recorded once and applied once."""
    try:
        data = json.loads(body)
    except ValueError:
        raise ValidationError({"detail": "Body is not JSON."}) from None
    if not isinstance(data, dict):
        raise ValidationError({"detail": "Body is not a JSON object."})
    event = str(data.get("event", ""))
    event_id = event_id or "sha256:" + hashlib.sha256(body).hexdigest()
    with transaction.atomic():
        try:
            with transaction.atomic():
                row = WebhookEvent.objects.create(
                    provider="razorpay", event_id=event_id[:128], event=event[:64], payload=data
                )
        except IntegrityError:
            return "duplicate"
        result = _apply(event, data)
        row.processed_at = timezone.now()
        row.result = result[:200]
        row.save(update_fields=["processed_at", "result"])
    return result


def _apply(event: str, data: dict) -> str:
    if not event.startswith("subscription."):
        return "ignored"
    entity = (((data.get("payload") or {}).get("subscription") or {}).get("entity")) or {}
    sub_id = entity.get("id")
    if not sub_id:
        return "ignored: no subscription id"
    sub = Subscription.objects.select_for_update().filter(provider_subscription_id=sub_id).first()
    if sub is None:
        sub = _adopt(entity)
        if sub is None:
            return "ignored: unknown subscription"
    org = Organization.objects.select_for_update().get(pk=sub.organization_id)
    if sub.status in Subscription.TERMINAL:
        if event in ACTIVATE and sub.provider == Subscription.Provider.RAZORPAY:
            # Razorpay still charges a subscription we ended (a superseded one whose cancel
            # never got through): cancel it again. The charge itself needs a manual refund.
            log.error(
                "billing: %s for subscription %s which is %s; re-sending the cancel",
                event,
                sub.pk,
                sub.status,
            )
            transaction.on_commit(lambda: _enqueue_provider_cancel(sub.pk))
            return f"ignored: subscription already {sub.status}; cancel re-sent"
        return f"ignored: subscription already {sub.status}"
    if event in ACTIVATE:
        sub.status = Subscription.Status.ACTIVE
    elif event in STATUS_FOR:
        sub.status = STATUS_FOR[event]
    else:
        return "ignored"
    if entity.get("current_end"):
        sub.current_period_end = datetime.fromtimestamp(int(entity["current_end"]), UTC)
    sub.save()
    superseded: list[int] = []
    if sub.status == Subscription.Status.ACTIVE:
        _end_others(org, keep=sub)
        superseded = _supersede_razorpay(org, keep=sub)
    code = sync_plan(org)
    return f"{sub.status}; plan {code}" + (f"; superseded {len(superseded)}" if superseded else "")


def _supersede_razorpay(org: Organization, keep: Subscription) -> list[int]:
    """An upgrade or downgrade creates a second Razorpay subscription; when it becomes active
    the older one must stop charging. It is marked cancelled here at once (so a late
    `charged` webhook for it is ignored and cannot take the plan back), and cancelled at
    Razorpay by a Celery task after this transaction commits: the webhook answers at once
    and a Razorpay outage is retried instead of failing the delivery."""
    old = list(
        Subscription.objects.select_for_update()
        .filter(
            organization=org,
            provider=Subscription.Provider.RAZORPAY,
            status__in=Subscription.ENTITLED,
        )
        .exclude(pk=keep.pk)
        .values_list("pk", flat=True)
    )
    if not old:
        return []
    Subscription.objects.filter(pk__in=old).update(
        status=Subscription.Status.CANCELLED, updated_at=timezone.now()
    )
    for pk in old:
        log.info("billing: subscription %s superseded by %s; cancelling at Razorpay", pk, keep.pk)
        transaction.on_commit(lambda pk=pk: _enqueue_provider_cancel(pk))
    return old


def _enqueue_provider_cancel(subscription_pk: int) -> None:
    from billing.tasks import cancel_at_provider

    try:
        cancel_at_provider.delay(subscription_pk)
    except Exception:  # broker down; the next `charged` webhook for it queues it again
        log.exception("billing: could not queue the Razorpay cancel of %s", subscription_pk)


# Razorpay's answer when the subscription is already over: the goal is reached.
_ALREADY_ENDED = re.compile(
    r"not cancell?able|already (?:been )?cancell?ed|completed|expired", re.I
)


def cancel_razorpay_now(provider_subscription_id: str) -> str:
    """Cancel a Razorpay subscription immediately (no further charges). Idempotent: a
    subscription Razorpay reports as already cancelled or completed counts as done.
    Raises ProviderError on network errors and other HTTP errors (the caller retries)."""
    path = f"/subscriptions/{provider_subscription_id}/cancel"
    try:
        resp = httpx.post(
            f"{RAZORPAY_API}{path}",
            json={"cancel_at_cycle_end": 0},
            auth=_razorpay_auth(),
            timeout=20,
        )
    except httpx.HTTPError as exc:
        log.warning("razorpay POST %s failed: %s", path, exc)
        raise ProviderError() from exc
    if resp.status_code < 400:
        return str((resp.json() or {}).get("status", "cancelled"))
    if resp.status_code == 400 and _ALREADY_ENDED.search(resp.text):
        return "already ended"
    log.warning("razorpay POST %s -> %s %s", path, resp.status_code, resp.text[:500])
    raise ProviderError()


def _adopt(entity: dict) -> Subscription | None:
    """A subscription created outside our checkout (e.g. in the Razorpay dashboard) that
    names our organisation in its notes."""
    notes = entity.get("notes") or {}
    org = Organization.objects.filter(pk=_int(notes.get("organization_id"))).first()
    mapped = plan_for_razorpay_id(str(entity.get("plan_id", "")))
    if org is None or mapped is None:
        return None
    code, interval = mapped
    return Subscription.objects.create(
        organization=org,
        plan_code=code,
        interval=interval,
        provider=Subscription.Provider.RAZORPAY,
        provider_subscription_id=entity["id"],
    )


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
