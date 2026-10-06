"""What an organisation's plan allows, and metering against it.

    plan = get_plan(org)
    consume(org, "questions_per_month")      # before answering; raises QuotaExceeded (402)
    require_feature(org, "export")           # boolean limits
    ensure_capacity(org, "seats", current=n) # count limits: members, alert subscriptions

consume() is one INSERT ... ON CONFLICT DO UPDATE ... WHERE count + n <= limit statement:
the row lock taken by the upsert serialises concurrent requests, so two parallel
questions can never both take the last unit of quota.
"""

from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

from billing.models import Usage
from billing.plans import DEFAULT_PLAN, FEATURE_KEYS, LIMIT_KEYS, MONTHLY_KEYS, PLANS, Limit, Plan

LABELS = {
    "alerts": "email alerts",
    "questions_per_month": "Copilot questions this month",
    "documents_per_month": "document uploads this month",
    "seats": "seats",
    "export": "exports",
    "api": "API access",
}


class QuotaExceeded(APIException):
    """HTTP 402 with body {"detail": ..., "code": "quota_exceeded", "limit": <key>}."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "quota_exceeded"
    default_detail = "Your plan's limit is reached."

    def __init__(self, key: str, message: str | None = None):
        self.limit_key = key
        self.body = {
            "detail": message or f"Your plan's limit for {LABELS.get(key, key)} is reached.",
            "code": self.default_code,
            "limit": key,
        }
        super().__init__(detail=self.body, code=self.default_code)


def period(at=None) -> str:
    """The quota month, "YYYY-MM" in Indian time (quotas reset at IST midnight on the 1st)."""
    return timezone.localtime(at or timezone.now()).strftime("%Y-%m")


def get_plan(org) -> Plan:
    return PLANS.get(org.plan_code) or PLANS[DEFAULT_PLAN]


def limit(org, key: str) -> Limit:
    """int cap, None for unlimited, 0 / False when the plan does not include it."""
    if key not in LIMIT_KEYS:
        raise KeyError(f"unknown limit {key!r}; expected one of {LIMIT_KEYS}")
    return get_plan(org).limits[key]


def used(org, key: str, *, at=None) -> int:
    """Units of a monthly limit used in the current (or `at`'s) month."""
    return (
        Usage.objects.filter(organization_id=org.pk, key=key, period=period(at))
        .values_list("count", flat=True)
        .first()
        or 0
    )


def remaining(org, key: str) -> int | None:
    """Units left this month; None when unlimited."""
    cap = limit(org, key)
    if cap is None:
        return None
    return max(0, int(cap) - used(org, key))


_CONSUME_SQL = """
INSERT INTO billing_usage (organization_id, key, period, count, updated_at)
VALUES (%(org)s, %(key)s, %(period)s, %(n)s, now())
ON CONFLICT (organization_id, key, period) DO UPDATE
    SET count = billing_usage.count + EXCLUDED.count, updated_at = now()
    {guard}
RETURNING count
"""


def consume(org, key: str, n: int = 1) -> int:
    """Count n units of a monthly limit; returns the month's new total. Raises
    QuotaExceeded, without counting anything, when that would go over the plan's cap."""
    if key not in MONTHLY_KEYS:
        raise ValueError(f"{key!r} is not a monthly limit; use ensure_capacity()")
    if n < 1:
        raise ValueError("n must be at least 1")
    cap = limit(org, key)
    if cap is not None and n > cap:
        raise QuotaExceeded(key)
    guard = "" if cap is None else "WHERE billing_usage.count + EXCLUDED.count <= %(cap)s"
    params = {"org": org.pk, "key": key, "period": period(), "n": n, "cap": cap}
    with connection.cursor() as cur:
        cur.execute(_CONSUME_SQL.format(guard=guard), params)
        row = cur.fetchone()
    if row is None:  # the row exists and the guard refused the increment
        raise QuotaExceeded(key)
    return row[0]


def refund(org, key: str, n: int = 1) -> None:
    """Give back units consumed this month, e.g. when an upload is rejected after
    consume(). Never goes below zero."""
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE billing_usage SET count = GREATEST(count - %s, 0), updated_at = now() "
            "WHERE organization_id = %s AND key = %s AND period = %s",
            [n, org.pk, key, period()],
        )


def ensure_capacity(org, key: str, *, current: int, adding: int = 1) -> None:
    """For limits on a current count (members, alert subscriptions): raises QuotaExceeded
    when `current + adding` would exceed the plan's cap. The caller counts `current`."""
    cap = limit(org, key)
    if cap is not None and current + adding > cap:
        raise QuotaExceeded(key)


def require_feature(org, key: str) -> None:
    """For boolean limits (export, api)."""
    if key not in FEATURE_KEYS:
        raise ValueError(f"{key!r} is not a feature flag; expected one of {FEATURE_KEYS}")
    value = limit(org, key)
    if value is not None and not value:
        raise QuotaExceeded(key, f"Your plan does not include {LABELS[key]}. Upgrade to use it.")


def usage_summary(org) -> dict[str, int]:
    """{key: used this month} for every monthly limit (for GET /api/workspace)."""
    rows = dict(
        Usage.objects.filter(organization_id=org.pk, period=period()).values_list("key", "count")
    )
    return {key: rows.get(key, 0) for key in MONTHLY_KEYS}
