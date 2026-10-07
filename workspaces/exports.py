"""Tender exports: CSV for spreadsheets, OCDS 1.1 release packages for other tooling.

Both carry the source portal and its link on every tender: the portals' content has no
open licence, so we export structured metadata with attribution and link out to the
documents instead of republishing them.
"""

import csv
from collections.abc import Iterable, Iterator
from datetime import datetime
from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from tenders.models import Tender

MAX_CSV_ROWS = 10_000

CSV_COLUMNS = [
    ("tender_id", lambda t: t.source_tender_id),
    ("reference_no", lambda t: t.ref_no),
    ("title", lambda t: t.title),
    ("buyer", lambda t: t.buyer_entity.canonical_name if t.buyer_entity else t.buyer_raw),
    ("organisation_chain", lambda t: t.org_chain),
    ("category", lambda t: t.category),
    ("sector", lambda t: t.sector),
    ("state", lambda t: t.state),
    ("location", lambda t: t.location),
    ("pincode", lambda t: t.pincode),
    ("value_inr", lambda t: t.value_inr),
    ("emd_inr", lambda t: t.emd_inr),
    ("fee_inr", lambda t: t.fee_inr),
    ("published_at", lambda t: t.published_at),
    ("closes_at", lambda t: t.closes_at),
    ("bid_opening_at", lambda t: t.opens_at),
    ("source_portal", lambda t: source_name(t.source)),
    ("source_url", lambda t: t.url),
    ("tenderlens_url", lambda t: f"{settings.SITE_URL}/tenders/{t.pk}"),
]

# A cell starting with one of these is run as a formula by Excel / LibreOffice / Sheets
# ("CSV injection", e.g. =HYPERLINK(...) in a tender title).
FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")


def source_name(key: str) -> str:
    from ingest.sources import SOURCES

    src = SOURCES.get(key)
    return getattr(src, "name", None) or key


def source_origin(key: str) -> str | None:
    from ingest.sources import SOURCES

    src = SOURCES.get(key)
    try:
        return src.origin if src is not None else None
    except AttributeError:
        return None


def safe_cell(value) -> str:
    """A CSV cell that spreadsheets show as text, never evaluate."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return timezone.localtime(value).isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    text = str(value)
    if text.startswith(FORMULA_START):
        return "'" + text
    return text


class _Echo:
    def write(self, value):
        return value


def csv_rows(tenders: Iterable[Tender]) -> Iterator[str]:
    """CSV lines, starting with a UTF-8 BOM so Excel reads Hindi and ₹ correctly."""
    writer = csv.writer(_Echo())
    yield "﻿" + writer.writerow([name for name, _ in CSV_COLUMNS])
    for t in tenders:
        yield writer.writerow([safe_cell(get(t)) for _, get in CSV_COLUMNS])


# --- OCDS -------------------------------------------------------------------------------

OCDS_VERSION = "1.1"
PUBLISHER = {"name": "TenderLens"}
CATEGORY = {"works": "works", "goods": "goods", "services": "services"}


def ocid(t: Tender) -> str:
    return f"{settings.OCDS_PREFIX}-{t.source}-{t.source_tender_id}"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _amount(v: Decimal | None) -> dict | None:
    return None if v is None else {"amount": float(v), "currency": "INR"}


def award_model():
    """The Award model if the sources stage has added one (tenders or ingest app)."""
    for label in ("tenders.Award", "ingest.Award"):
        try:
            return apps.get_model(label)
        except LookupError:
            continue
    return None


def awards_by_tender(tender_ids: list[int]) -> dict[int, list]:
    model = award_model()
    if model is None or not tender_ids:
        return {}
    out: dict[int, list] = {}
    for a in model.objects.filter(tender_id__in=tender_ids).order_by("pk"):
        out.setdefault(a.tender_id, []).append(a)
    return out


def _first(obj, *names):
    for name in names:
        value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return None


def release(t: Tender, awards: list | None = None, *, now: datetime | None = None) -> dict:
    """One OCDS release describing the tender as we last saw it."""
    now = now or timezone.now()
    oc = ocid(t)
    buyer_name = t.buyer_entity.canonical_name if t.buyer_entity else t.buyer_raw
    buyer_id = f"buyer-{t.buyer_entity_id}" if t.buyer_entity_id else f"buyer-{t.source}-raw"
    buyer_party = {"id": buyer_id, "name": buyer_name, "roles": ["buyer"]}
    address = {k: v for k, v in (("region", t.state), ("postalCode", t.pincode)) if v}
    if address:
        buyer_party["address"] = {**address, "countryName": "India"}
    parties = [buyer_party]

    tender: dict = {
        "id": t.source_tender_id,
        "title": t.title,
        "tenderPeriod": {"startDate": _iso(t.published_at), "endDate": _iso(t.closes_at)},
        "documents": [
            {
                "id": f"{t.source_tender_id}-notice",
                "documentType": "tenderNotice",
                "title": f"Tender notice on {source_name(t.source)}",
                "url": t.url or source_origin(t.source),
                "format": "text/html",
                "language": "en",
            }
        ],
    }
    if t.closes_at >= now:
        tender["status"] = "active"
    if t.value_inr is not None:
        tender["value"] = _amount(t.value_inr)
    if t.tender_type:
        tender["procurementMethodDetails"] = t.tender_type
    if CATEGORY.get(t.category.lower()):
        tender["mainProcurementCategory"] = CATEGORY[t.category.lower()]
    if t.emd_inr is not None:
        tender["guarantee"] = {"description": "Earnest money deposit (EMD)", **_amount(t.emd_inr)}
    if t.opens_at:
        tender["awardPeriod"] = {"startDate": _iso(t.opens_at)}
    if not tender["documents"][0]["url"]:
        tender.pop("documents")

    rel = {
        "ocid": oc,
        "id": f"{oc}-{t.content_hash[:16]}",
        "date": _iso(t.last_seen),
        "tag": ["tender"],
        "initiationType": "tender",
        "language": "en",
        "parties": parties,
        "buyer": {"id": buyer_id, "name": buyer_name},
        "tender": tender,
    }
    ocds_awards = []
    for i, a in enumerate(awards or [], 1):
        name = _first(a, "bidder_name", "bidder", "name") or "Unknown bidder"
        key = _first(a, "bidder_key", "normalised_bidder_key", "normalized_bidder_key") or name
        supplier_id = f"supplier-{key}"
        if not any(p["id"] == supplier_id for p in parties):
            parties.append({"id": supplier_id, "name": str(name), "roles": ["supplier"]})
        award = {
            "id": f"{t.source_tender_id}-award-{getattr(a, 'pk', i)}",
            "status": "active",
            "suppliers": [{"id": supplier_id, "name": str(name)}],
        }
        amount = _first(a, "amount_inr")
        if amount is not None:
            award["value"] = _amount(Decimal(amount))
        date = _first(a, "award_date")
        if date is not None:
            award["date"] = date.isoformat()
        ocds_awards.append(award)
    if ocds_awards:
        rel["awards"] = ocds_awards
        rel["tag"] = ["tender", "award"]
    return rel


def release_package(tenders: list[Tender], *, uri: str, links: dict) -> dict:
    now = timezone.now()
    awards = awards_by_tender([t.pk for t in tenders])
    return {
        "uri": uri,
        "version": OCDS_VERSION,
        "publishedDate": now.isoformat(),
        "publisher": PUBLISHER,
        # No licence is claimed: the source portals publish under none. Every release names
        # and links its source portal.
        "publicationPolicy": f"{settings.SITE_URL}/about",
        "links": links,
        "releases": [release(t, awards.get(t.pk), now=now) for t in tenders],
    }
