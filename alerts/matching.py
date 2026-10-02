from datetime import datetime

from django.db.models import Q, QuerySet
from django.utils import timezone

from tenders.models import Tender


def matching_tenders(
    *,
    states: list[str],
    pin_prefixes: list[str],
    sectors: list[str],
    keywords: str = "",
    min_value_inr=None,
    first_seen_after: datetime | None = None,
    first_seen_until: datetime | None = None,
    now: datetime | None = None,
) -> QuerySet[Tender]:
    """Open tenders matching an alert's criteria, soonest closing first."""
    now = now or timezone.now()
    qs = Tender.objects.filter(closes_at__gte=now).select_related("buyer_entity")
    area = Q()
    for state in states:
        area |= Q(state=state)
    for prefix in pin_prefixes:
        area |= Q(pincode__startswith=prefix)
    if area:
        qs = qs.filter(area)
    if sectors:
        qs = qs.filter(sector__in=sectors)
    words = [w.strip() for w in keywords.replace(";", ",").split(",") if w.strip()]
    if words:
        kw = Q()
        for w in words:
            kw |= Q(title__icontains=w)
        qs = qs.filter(kw)
    if min_value_inr is not None:
        qs = qs.filter(value_inr__gte=min_value_inr)
    if first_seen_after is not None:
        qs = qs.filter(first_seen__gt=first_seen_after)
    if first_seen_until is not None:
        qs = qs.filter(first_seen__lte=first_seen_until)
    return qs.order_by("closes_at", "id")


def for_subscription(sub, **kwargs) -> QuerySet[Tender]:
    return matching_tenders(
        states=sub.states,
        pin_prefixes=sub.pin_prefixes,
        sectors=sub.sectors,
        keywords=sub.keywords,
        min_value_inr=sub.min_value_inr,
        **kwargs,
    )


def describe_area(sub) -> str:
    parts = list(sub.states) + [f"PIN {p}xxx" for p in sub.pin_prefixes]
    return ", ".join(parts) if parts else "all of India"
