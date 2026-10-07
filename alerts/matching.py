"""Which tenders an alert matches. Keywords are matched by the same Postgres full-text
search as /api/tenders (tenders.search), so an alert finds what the user's search finds:
stemming ("toilets" finds "toilet"), prefixes ("constr" finds "construction"), websearch
syntax ("quoted phrase", -not, or) and typo correction for words that occur nowhere in the
data ("toliet" -> "toilet"). The keyword field is a comma- or semicolon-separated list of
such queries, and a tender matches when any one of them matches.

Unlike the search box, a keyword never falls back to "any one word": "road repair" in an
alert means both words, otherwise every road tender in the country would be emailed.
"""

from datetime import datetime

from django.db.models import BooleanField, Q, QuerySet
from django.db.models.expressions import RawSQL
from django.utils import timezone

from tenders import search
from tenders.models import Tender


def split_keywords(keywords: str) -> list[str]:
    return [w.strip() for w in keywords.replace(";", ",").split(",") if w.strip()]


def keyword_condition(keywords: str) -> Q | None:
    """A filter for "any keyword matches", or None when there are no keywords. A keyword
    with no searchable words (only stop words or symbols) falls back to a title substring
    match, as before."""
    words = split_keywords(keywords)
    if not words:
        return None
    queries: list[str] = []
    cond = Q()
    for kw in words:
        clauses, negated = search.parse(kw)
        tsq = search.to_tsquery(clauses, negated)
        if not tsq:
            cond |= Q(title__icontains=kw)
            continue
        queries.append(tsq)
        fixed = search.correct(kw)
        if fixed != kw and (fixed_tsq := search.to_tsquery(*search.parse(fixed))):
            queries.append(fixed_tsq)
    if queries:
        sql = " OR ".join([f"{search.VECTOR} @@ %s::tsquery"] * len(queries))
        cond |= Q(RawSQL(f"({sql})", queries, output_field=BooleanField()))
    return cond


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
    kw = keyword_condition(keywords)
    if kw is not None:
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
