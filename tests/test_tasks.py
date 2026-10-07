"""The Celery pipeline, including what happens when a worker dies mid-crawl.

With acks_late + reject_on_worker_lost, a task that was running when its worker died
is delivered again. The test reproduces that: half the tasks run, one dies after
saving its raw page but before loading it, then *every* task is delivered again.
"""

import pytest
import redis as redis_lib
from django.conf import settings

from ingest import tasks
from ingest.models import CrawlItem, CrawlRun, DeadLetter, RawPage
from tenders.models import Tender

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _redis(monkeypatch):
    client = redis_lib.Redis.from_url(settings.REDIS_URL, db=15)
    try:
        client.ping()
    except redis_lib.ConnectionError:
        pytest.skip("redis not reachable")
    client.flushdb()
    monkeypatch.setattr(tasks, "_redis", client)
    monkeypatch.setattr(tasks, "_fetcher", None)
    yield client
    client.flushdb()


@pytest.fixture
def captured(monkeypatch):
    """Capture the fetch_detail -> parse_and_load chains instead of running them."""
    sent = []

    class FakeChain:
        def __init__(self, *sigs):
            self.sigs = sigs

        def apply_async(self):
            sent.append(self.sigs)

    monkeypatch.setattr(tasks, "chain", FakeChain)
    return sent


def run_chain(sigs):
    fetch_sig, load_sig = sigs
    raw_page_id = tasks.fetch_detail.apply(args=fetch_sig.args).get()
    return tasks.parse_and_load.apply(args=(raw_page_id, *load_sig.args)).get()


def test_full_chain_runs_eagerly(portal):
    run = CrawlRun.objects.create(source="central", mode="full")
    tasks.crawl_listing.apply(args=(run.pk,)).get()
    run.refresh_from_db()
    assert run.status == CrawlRun.Status.SUCCEEDED
    assert run.new == 7
    assert Tender.objects.count() == 7


def test_start_crawl_creates_one_run_per_source(portal, captured):
    ids = tasks.start_crawl.apply(kwargs={"mode": "full", "sources": ["central"]}).get()
    assert len(ids) == 1
    assert len(captured) == 7


def test_worker_killed_mid_crawl_then_redelivered(portal, captured):
    run = CrawlRun.objects.create(source="central", mode="full")
    tasks.crawl_listing.apply(args=(run.pk,)).get()
    assert len(captured) == 7
    assert CrawlItem.objects.filter(crawl_run=run, outcome="pending").count() == 7

    # Worker 1 finishes three tenders...
    for sigs in captured[:3]:
        run_chain(sigs)
    # ...then dies after fetch_detail stored the 4th page but before parse_and_load ran.
    tasks.fetch_detail.apply(args=captured[3][0].args).get()
    run.refresh_from_db()
    assert run.status == CrawlRun.Status.RUNNING
    assert Tender.objects.count() == 3

    # Worker 2 starts; the broker redelivers everything that was not acknowledged.
    # Re-running already-finished chains too is the worst case and must be harmless.
    for sigs in captured:
        run_chain(sigs)

    run.refresh_from_db()
    assert run.status == CrawlRun.Status.SUCCEEDED
    assert Tender.objects.count() == 7
    assert Tender.objects.values("source_tender_id").distinct().count() == 7
    # Counters come from CrawlItem (one row per tender per run), so redelivery cannot
    # inflate them: every tender is counted exactly once.
    assert run.new + run.updated + run.unchanged == 7
    assert CrawlItem.objects.filter(crawl_run=run).count() == 7


def test_exhausted_retries_go_to_dead_letter(portal, captured, settings):
    # Eager retries call apply() again without `throw`, so propagation must be off
    # globally for the retry chain to run to exhaustion like it would on a worker.
    settings.CELERY_TASK_EAGER_PROPAGATES = False
    run = CrawlRun.objects.create(source="central", mode="full")
    tasks.crawl_listing.apply(args=(run.pk,)).get()
    bad = captured[0][0]
    portal.fail_detail[portal.sp_of(bad.args[1])] = 10_000
    result = tasks.fetch_detail.apply(args=bad.args, throw=False)  # eager retries run inline
    assert result.failed()
    dl = DeadLetter.objects.get()
    assert dl.task_name == "ingest.tasks.fetch_detail"
    assert dl.attempts == tasks.MAX_RETRIES + 1
    assert CrawlItem.objects.get(crawl_run=run, source_tender_id=bad.args[1]).outcome == "failed"
    for sigs in captured[1:]:
        run_chain(sigs)
    run.refresh_from_db()
    assert run.status == CrawlRun.Status.MISMATCH
    assert (run.new, run.failed) == (6, 1)


def test_session_cookies_are_shared_through_redis(portal, captured, _redis):
    run = CrawlRun.objects.create(source="central", mode="full")
    tasks.crawl_listing.apply(args=(run.pk,)).get()
    assert _redis.get(f"tenderlens:run:{run.pk}:cookies") is not None
    run_chain(captured[0])
    assert portal.sessions == 0  # reused the listing's session, did not start a new one


def test_close_stale_runs_marks_incomplete(portal, captured):
    from datetime import timedelta

    from django.utils import timezone

    run = CrawlRun.objects.create(source="central", mode="full")
    tasks.crawl_listing.apply(args=(run.pk,)).get()
    CrawlRun.objects.filter(pk=run.pk).update(started=timezone.now() - timedelta(hours=7))
    assert tasks.close_stale_runs.apply().get() == [run.pk]
    run.refresh_from_db()
    assert run.status == CrawlRun.Status.INCOMPLETE
    assert "7 tenders never finished" in run.reconciliation["problems"]


def test_prune_keeps_detail_pages(portal):
    from datetime import timedelta

    from django.utils import timezone

    run = CrawlRun.objects.create(source="central", mode="full")
    tasks.crawl_listing.apply(args=(run.pk,)).get()
    RawPage.objects.update(fetched_at=timezone.now() - timedelta(days=30))
    deleted = tasks.prune_raw_pages.apply().get()
    assert deleted == 2  # index + listing
    assert RawPage.objects.filter(kind="detail").count() == 7


def test_prune_detail_retention_keeps_pages_still_referenced(make_page, settings):
    from datetime import timedelta

    from django.utils import timezone

    from ingest.loader import load_detail_page
    from tests.conftest import fixture_text

    old = timezone.now() - timedelta(days=30)
    html = fixture_text("gepnic_central/detail_01.html")
    current = make_page(html, fetched_at=old)
    load_detail_page(current)  # tender points at this page
    refetched = make_page(html, fetched_at=old)
    assert load_detail_page(refetched).outcome == "unchanged"  # nobody points at it
    broken = make_page(fixture_text("broken/detail_closes_before_published.html"), fetched_at=old)
    assert load_detail_page(broken).outcome == "quarantined"
    recent = make_page(html)

    assert tasks.prune_raw_pages.apply().get() == 0  # unset: detail pages are kept
    settings.CRAWLER = {**settings.CRAWLER, "RAW_DETAIL_RETENTION_DAYS": 7}
    assert tasks.prune_raw_pages.apply().get() == 1
    assert set(RawPage.objects.values_list("pk", flat=True)) == {current.pk, broken.pk, recent.pk}
    assert Tender.objects.get().raw_page_id == current.pk


def test_prune_deletes_finished_items_with_their_page(make_page, settings):
    """Pruning must not UPDATE crawl items: a database at its size limit has no room."""
    from datetime import timedelta

    from django.utils import timezone

    from ingest.loader import load_detail_page
    from tests.conftest import fixture_text

    old = timezone.now() - timedelta(days=30)
    html = fixture_text("gepnic_central/detail_01.html")
    load_detail_page(make_page(html, fetched_at=old))
    refetched = make_page(html, fetched_at=old)
    load_detail_page(refetched)
    done = CrawlRun.objects.create(source="central", status=CrawlRun.Status.SUCCEEDED)
    running = CrawlRun.objects.create(source="central")
    for run in (done, running):
        CrawlItem.objects.create(
            crawl_run=run, source_tender_id="T", outcome="unchanged", raw_page=refetched
        )
    CrawlItem.objects.create(
        crawl_run=done, source_tender_id="T2", outcome="updated", raw_page=refetched
    )

    settings.CRAWLER = {**settings.CRAWLER, "RAW_DETAIL_RETENTION_DAYS": 0}
    assert tasks.prune_raw_pages.apply().get() == 1
    assert list(
        CrawlItem.objects.order_by("source_tender_id").values_list("crawl_run", "raw_page")
    ) == [(running.pk, None)]


@pytest.mark.django_db(transaction=True)
def test_prune_command():
    from django.core.management import call_command

    call_command("prune")  # VACUUM fails inside a transaction block


def test_prune_crawl_items_only_old_finished_runs(db, settings):
    from datetime import timedelta

    from django.utils import timezone

    old = timezone.now() - timedelta(days=30)
    runs = {
        status: CrawlRun.objects.create(source="central", status=status)
        for status in (CrawlRun.Status.SUCCEEDED, CrawlRun.Status.RUNNING)
    }
    CrawlRun.objects.update(started=old)
    recent = CrawlRun.objects.create(source="central", status=CrawlRun.Status.SUCCEEDED)
    for run in [*runs.values(), recent]:
        CrawlItem.objects.create(crawl_run=run, source_tender_id=f"T{run.pk}")

    assert tasks.prune_crawl_items.apply().get() == 0  # unset: keep everything
    settings.CRAWLER = {**settings.CRAWLER, "CRAWL_ITEM_RETENTION_DAYS": 7}
    assert tasks.prune_crawl_items.apply().get() == 1
    assert set(CrawlItem.objects.values_list("crawl_run_id", flat=True)) == {
        runs[CrawlRun.Status.RUNNING].pk,
        recent.pk,
    }


def test_redelivered_crawl_listing_does_not_reset_finished_items(portal, captured):
    run = CrawlRun.objects.create(source="central", mode="full")
    tasks.crawl_listing.apply(args=(run.pk,)).get()
    for sigs in captured[:3]:
        run_chain(sigs)
    tasks.crawl_listing.apply(args=(run.pk,)).get()  # redelivered after a crash
    finished = CrawlItem.objects.filter(crawl_run=run).exclude(outcome="pending").count()
    assert finished == 3
    for sigs in captured:  # original + re-dispatched chains all run
        run_chain(sigs)
    run.refresh_from_db()
    assert run.status == CrawlRun.Status.SUCCEEDED
    assert Tender.objects.count() == 7
