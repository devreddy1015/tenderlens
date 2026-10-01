"""End-to-end crawl against a fake portal serving real saved pages."""

import re

import pytest

from ingest import pipeline
from ingest.models import CrawlItem, CrawlRun, DeadLetter, RawPage
from tenders.models import Tender

pytestmark = pytest.mark.django_db


def test_crawl_twice_same_rows_zero_duplicates(portal):
    run1 = pipeline.run_sync("central", mode="full")
    assert run1.status == CrawlRun.Status.SUCCEEDED
    assert (run1.new, run1.updated, run1.unchanged) == (7, 0, 0)
    assert run1.expected == 7 and run1.listed == 7

    run2 = pipeline.run_sync("central", mode="full")
    assert (run2.new, run2.updated, run2.unchanged) == (0, 0, 7)
    assert Tender.objects.count() == 7
    assert Tender.objects.values("source", "source_tender_id").distinct().count() == 7


def test_raw_pages_are_stored_before_parsing(portal):
    run = pipeline.run_sync("central", mode="full")
    kinds = list(RawPage.objects.filter(crawl_run=run).values_list("kind", flat=True))
    assert kinds.count("index") == 1
    assert kinds.count("listing") == 1
    assert kinds.count("detail") == 7
    assert run.pages == 9
    t = Tender.objects.first()
    assert t.raw_page.kind == "detail"


def test_incremental_crawl_skips_unchanged_listing_rows(portal):
    pipeline.run_sync("central", mode="full")
    details_before = portal.hits.get("FrontEndViewTender", 0)
    run = pipeline.run_sync("central", mode="incremental")
    assert run.skipped == 7
    assert portal.hits.get("FrontEndViewTender", 0) == details_before  # no detail fetched
    assert run.status == CrawlRun.Status.SUCCEEDED


def test_incremental_crawl_refetches_tender_whose_listing_changed(portal):
    pipeline.run_sync("central", mode="full")
    row = portal.rows[0]
    changed = portal.listing_html.replace(row.closes, "20-Oct-2026 11:00 AM", 1)
    portal.listing_html = changed
    portal.overrides[portal.sp_of(row.tender_id)] = portal.detail_html(row).replace(
        "07-Oct-2026 11:00 AM", "20-Oct-2026 11:00 AM"
    )
    run = pipeline.run_sync("central", mode="incremental")
    assert (run.updated, run.skipped) == (1, 6)
    assert Tender.objects.get(source_tender_id=row.tender_id).closes_at.day == 20


def test_stale_session_is_renewed_transparently(portal):
    sp = portal.sp_of(portal.rows[2].tender_id)
    portal.stale_next.add(sp)
    run = pipeline.run_sync("central", mode="full")
    assert run.new == 7 and run.failed == 0
    assert portal.sessions == 1  # one new session was started


def test_transient_503_is_retried(portal):
    sp = portal.sp_of(portal.rows[1].tender_id)
    portal.fail_detail[sp] = 2  # fetcher allows 3 attempts in tests
    run = pipeline.run_sync("central", mode="full")
    assert run.new == 7 and run.failed == 0


def test_persistent_failure_goes_to_dead_letter_and_flags_run(portal):
    bad = portal.rows[3]
    portal.fail_detail[portal.sp_of(bad.tender_id)] = 99
    run = pipeline.run_sync("central", mode="full")
    assert run.new == 6 and run.failed == 1
    assert run.status == CrawlRun.Status.MISMATCH
    assert "1 tenders dead-lettered" in run.reconciliation["problems"]
    dl = DeadLetter.objects.get()
    assert dl.payload["tender_id"] == bad.tender_id
    assert "HTTP 503" in dl.error
    item = CrawlItem.objects.get(crawl_run=run, source_tender_id=bad.tender_id)
    assert item.outcome == CrawlItem.Outcome.FAILED


def test_reconciliation_flags_index_count_mismatch(portal):
    portal.index_html = re.sub(r"(DirectLink_0[^>]*>\s*)7(\s*</a>)", r"\g<1>9\2", portal.index_html)
    run = pipeline.run_sync("central", mode="full")
    assert run.status == CrawlRun.Status.MISMATCH
    assert run.reconciliation["organisation_mismatches"] == [
        {"organisation": "Aligarh Muslim University", "claimed": 9, "listed": 7}
    ]
    assert "index claims 9 tenders, listings show 7" in run.reconciliation["problems"]


def test_quarantined_detail_counts_in_run(portal):
    bad = portal.rows[0]
    html = portal.detail_html(bad).replace("07-Oct-2026 11:00 AM", "07-Sep-2026 11:00 AM")
    portal.overrides[portal.sp_of(bad.tender_id)] = html
    run = pipeline.run_sync("central", mode="full")
    assert (run.new, run.quarantined) == (6, 1)
    assert run.status == CrawlRun.Status.SUCCEEDED  # quarantine is accounted for, not lost
