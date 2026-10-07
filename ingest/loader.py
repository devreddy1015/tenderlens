"""Idempotent load: parse -> validate -> resolve buyer -> upsert, or quarantine."""

import logging
from dataclasses import dataclass
from datetime import datetime

from django.db import connection, transaction

from ingest.models import Quarantine, RawPage
from ingest.parsers import DETAIL_PARSERS, gepnic
from ingest.sources import get_source
from ingest.validation import TenderIn, validate_detail
from tenders import resolution
from tenders.pincode import state_from_pincode
from tenders.sectors import classify as classify_sector

log = logging.getLogger(__name__)

# The conditional DO UPDATE is the core of idempotency:
#   * same tender, same content       -> WHERE is false, nothing is written, no row returned
#   * same tender, changed content    -> row updated, first_seen preserved
#   * an older page replayed by a backfill never overwrites newer data (fetched_at guard)
# xmax = 0 is true only for freshly inserted rows, which tells "new" from "updated".
UPSERT_SQL = """
INSERT INTO tender (
    source, source_tender_id, ref_no, title, buyer_raw, buyer_entity_id, org_chain,
    category, product_category, tender_type, sector, value_inr, emd_inr, fee_inr,
    published_at, closes_at, opens_at, prebid_meeting, location, pincode, state, url,
    content_hash, fetched_at, raw_page_id, first_seen, last_seen
) VALUES (
    %(source)s, %(source_tender_id)s, %(ref_no)s, %(title)s, %(buyer_raw)s, %(buyer_entity_id)s,
    %(org_chain)s, %(category)s, %(product_category)s, %(tender_type)s, %(sector)s, %(value_inr)s,
    %(emd_inr)s, %(fee_inr)s, %(published_at)s, %(closes_at)s, %(opens_at)s,
    %(prebid_meeting)s, %(location)s,
    %(pincode)s, %(state)s, %(url)s, %(content_hash)s, %(fetched_at)s, %(raw_page_id)s,
    %(fetched_at)s, %(fetched_at)s
)
ON CONFLICT (source, source_tender_id) DO UPDATE SET
    ref_no = EXCLUDED.ref_no,
    title = EXCLUDED.title,
    buyer_raw = EXCLUDED.buyer_raw,
    buyer_entity_id = EXCLUDED.buyer_entity_id,
    org_chain = EXCLUDED.org_chain,
    category = EXCLUDED.category,
    product_category = EXCLUDED.product_category,
    tender_type = EXCLUDED.tender_type,
    sector = EXCLUDED.sector,
    value_inr = EXCLUDED.value_inr,
    emd_inr = EXCLUDED.emd_inr,
    fee_inr = EXCLUDED.fee_inr,
    published_at = EXCLUDED.published_at,
    closes_at = EXCLUDED.closes_at,
    opens_at = EXCLUDED.opens_at,
    -- A portal that says "NA" keeps a date the Copilot read from the tender's documents.
    prebid_meeting = COALESCE(EXCLUDED.prebid_meeting, tender.prebid_meeting),
    location = EXCLUDED.location,
    pincode = EXCLUDED.pincode,
    state = EXCLUDED.state,
    url = EXCLUDED.url,
    content_hash = EXCLUDED.content_hash,
    fetched_at = EXCLUDED.fetched_at,
    raw_page_id = EXCLUDED.raw_page_id,
    last_seen = GREATEST(tender.last_seen, EXCLUDED.last_seen)
WHERE tender.content_hash <> EXCLUDED.content_hash
  AND tender.fetched_at <= EXCLUDED.fetched_at
RETURNING id, (xmax = 0) AS inserted
"""

TOUCH_SQL = """
UPDATE tender SET last_seen = GREATEST(last_seen, %(fetched_at)s)
WHERE source = %(source)s AND source_tender_id = %(source_tender_id)s
RETURNING id
"""


@dataclass
class LoadResult:
    outcome: str  # new | updated | unchanged | quarantined
    tender_id: int | None = None
    source_tender_id: str = ""
    errors: list | None = None


def upsert_tender(
    tender: TenderIn, *, fetched_at: datetime, raw_page_id: int | None, buyer_entity_id: int | None
) -> tuple[str, int]:
    params = tender.model_dump()
    params.update(
        sector=classify_sector(tender.title, tender.product_category, tender.category),
        content_hash=tender.content_hash(),
        fetched_at=fetched_at,
        raw_page_id=raw_page_id,
        buyer_entity_id=buyer_entity_id,
    )
    with connection.cursor() as cur:
        cur.execute(UPSERT_SQL, params)
        row = cur.fetchone()
        if row is not None:
            return ("new" if row[1] else "updated"), row[0]
        cur.execute(TOUCH_SQL, params)
        row = cur.fetchone()
        return "unchanged", row[0]


def quarantine(raw: dict, errors: list[dict], *, source: str, raw_page_id: int | None) -> None:
    Quarantine.objects.create(payload=raw, errors=errors, source=source, raw_page_id=raw_page_id)
    log.warning(
        "quarantined %s/%s: %s",
        source,
        raw.get("tender_id") or "?",
        "; ".join(f"{e['field']}: {e['error']}" for e in errors),
    )


def load_detail_page(page: RawPage) -> LoadResult:
    """Parse one stored detail page and load it. Safe to call any number of times."""
    source = get_source(page.source)
    try:
        raw = DETAIL_PARSERS[source.kind].parse_detail(page.body)
    except gepnic.NotADetailPage as exc:
        errors = [{"field": "__page__", "error": str(exc), "input": page.url}]
        quarantine({"url": page.url}, errors, source=page.source, raw_page_id=page.id)
        return LoadResult("quarantined", errors=errors, source_tender_id=page.source_tender_id)

    state = source.state or state_from_pincode(raw.get("pincode"))
    tender, errors = validate_detail(raw, source=page.source, url=page.url, state=state)
    if tender is None:
        quarantine(raw, errors, source=page.source, raw_page_id=page.id)
        return LoadResult("quarantined", errors=errors, source_tender_id=raw.get("tender_id", ""))

    with transaction.atomic():
        # Names are blocked by state. A name already seen keeps its entity (alias lookup);
        # a new name is compared with the buyers of this tender's state.
        res = resolution.resolve(tender.buyer_raw, tender.state)
        outcome, tender_pk = upsert_tender(
            tender, fetched_at=page.fetched_at, raw_page_id=page.id, buyer_entity_id=res.entity_id
        )
    return LoadResult(outcome, tender_pk, tender.source_tender_id)
