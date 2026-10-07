"""Bid outcomes recorded in the pipeline, as training rows (docs/BID_ADVISOR.md section 1).

Indian award pages are CAPTCHA-gated, but our users see the results of the tenders they bid
on. When a tracked tender is marked won or lost with the L1 price, it becomes one
HistoricalAward (source "tenderlens", one row per organisation and tender) next to the
open-data rows, with the same derived columns because it goes through the same upsert.

`shared` follows Organization.contribute_outcomes: shared rows may train the pooled model
(ratios only, after the tender has closed; enforced by training), unshared rows only ever
serve that organisation's own comparables.
"""

from django.utils import timezone

from intel.models import HistoricalAward
from intel.sources.base import AwardRow, upsert

SOURCE = "tenderlens"
RESULT_STATUSES = ("won", "lost")
CATEGORIES = {"works", "goods", "services", "consultancy"}


def source_id(track) -> str:
    return f"{track.organization_id}:{track.tender_id}"


def _category(text: str) -> str:
    """Tender.category is the portal's label ("Works", "Goods", "Services"...)."""
    text = (text or "").strip().lower()
    if text.startswith("consult"):
        return "consultancy"
    return text if text in CATEGORIES else ""


def _method(tender_type: str) -> str:
    """GePNIC "Tender Type": Open Tender, Global Tenders, National Competitive Bid,
    Limited, Open Limited, Single."""
    text = (tender_type or "").lower()
    if "limited" in text:
        return "limited"
    if "single" in text:
        return "single"
    if "open" in text or "global" in text or "competitive" in text:
        return "open"
    return ""


def record_outcome(track) -> HistoricalAward | None:
    """Upserts or removes the track's training row so it always matches the track: a row
    exists exactly while the status is won/lost with an L1 price and the tender has a
    known value. Idempotent; the award date is the day the result was first recorded."""
    tender, org = track.tender, track.organization
    sid = source_id(track)
    usable = (
        track.status in RESULT_STATUSES
        and track.l1_amount_inr is not None
        and track.l1_amount_inr > 0
        and tender.value_inr is not None
        and tender.value_inr > 0
    )
    if not usable:
        HistoricalAward.objects.filter(source=SOURCE, source_id=sid).delete()
        return None
    first_recorded = (
        HistoricalAward.objects.filter(source=SOURCE, source_id=sid)
        .values_list("award_date", flat=True)
        .first()
    )
    winner = track.winner_name.strip() or (org.name if track.status == "won" else "")
    buyer = tender.buyer_entity.canonical_name if tender.buyer_entity_id else tender.buyer_raw
    row = AwardRow(
        source_id=sid,
        country="IN",
        state=tender.state,
        buyer=buyer,
        title=tender.title,
        category=_category(tender.category),
        sector=tender.sector,
        method=_method(tender.tender_type),
        estimated_value=tender.value_inr,
        award_value=track.l1_amount_inr,
        num_bidders=track.num_bidders,
        winner=winner,
        tender_date=timezone.localtime(tender.published_at).date(),
        award_date=first_recorded or timezone.localdate(),
        url=tender.url,
        tender_id=tender.pk,
        organization_id=org.pk,
        shared=org.contribute_outcomes,
    )
    upsert([row], SOURCE)
    return HistoricalAward.objects.get(source=SOURCE, source_id=sid)


def forget_outcome(track) -> None:
    """The track was deleted: its outcome row goes with it."""
    HistoricalAward.objects.filter(source=SOURCE, source_id=source_id(track)).delete()


def set_sharing(org) -> int:
    """Applies Organization.contribute_outcomes to the rows it already recorded."""
    return HistoricalAward.objects.filter(source=SOURCE, organization=org).update(
        shared=org.contribute_outcomes
    )
