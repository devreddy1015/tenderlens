"""'Recommended for you': open tenders that fit the organisation's company profile.

A tender is recommended when it is open, is in one of the profile's states (if any are
set) and sectors (if any are set), is not already in the pipeline, and - when both its
value and the company's turnover are known - is worth at most TURNOVER_MULTIPLE times the
annual turnover. Indian tenders usually ask for an average annual turnover of 30-50% of
the estimated cost (CPWD Works Manual, GFR 2017 practice), so 3x turnover is roughly the
largest tender a company plausibly qualifies for. Tenders without a value stay in.
Newest first: a fresh tender leaves time to prepare a bid.
"""

from decimal import Decimal

from django.db.models import Q, QuerySet
from django.utils import timezone

from tenders import search
from tenders.models import Tender
from tenders.sectors import SECTOR_BY_SLUG
from workspaces.models import BidTrack, Organization

TURNOVER_MULTIPLE = Decimal(3)


def profile_complete(org: Organization) -> bool:
    return bool(org.states or org.sectors)


def max_value(org: Organization) -> Decimal | None:
    if org.annual_turnover_inr is None or org.annual_turnover_inr <= 0:
        return None
    return org.annual_turnover_inr * TURNOVER_MULTIPLE


def queryset(org: Organization, params: dict | None = None) -> QuerySet:
    """Recommended tenders, optionally narrowed further by /api/tenders filters."""
    params = dict(params or {})
    text = search.match(params)
    qs = search.filtered(params, text).filter(closes_at__gte=timezone.now())
    if org.states:
        qs = qs.filter(state__in=org.states)
    if org.sectors:
        qs = qs.filter(sector__in=org.sectors)
    cap = max_value(org)
    if cap is not None:
        qs = qs.filter(Q(value_inr__isnull=True) | Q(value_inr__lte=cap))
    tracked = BidTrack.objects.filter(organization=org).values("tender_id")
    qs = qs.exclude(pk__in=tracked)
    return qs.select_related("buyer_entity").order_by(*search.ORDER["newest"])


def reasons(org: Organization, t: Tender) -> list[str]:
    out = []
    if org.sectors and t.sector in org.sectors:
        sector = SECTOR_BY_SLUG.get(t.sector)
        out.append(f"Sector: {sector.label if sector else t.sector}")
    if org.states and t.state in org.states:
        out.append(f"State: {t.state}")
    cap = max_value(org)
    if cap is not None and t.value_inr is not None and t.value_inr <= cap:
        out.append("Within your turnover limit")
    return out
