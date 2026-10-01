"""Celery pipeline: crawl_listing -> fetch_detail -> parse_and_load.

Failure model:
  * every task is idempotent; with acks_late a task whose worker died is simply re-run
  * fetch_detail retries with exponential backoff (max 5); after that the URL goes to
    dead_letter and the tender is marked failed so the run can still finish
  * a run finishes when no CrawlItem is pending; close_stale_runs sweeps up runs whose
    tasks were lost entirely (e.g. Redis flushed)
"""

import json
import logging
from datetime import timedelta

import httpx
from celery import Task, chain, shared_task
from django.conf import settings
from django.utils import timezone

from ingest import pipeline
from ingest.fetcher import Fetcher, FetchError
from ingest.loader import load_detail_page
from ingest.models import CrawlItem, CrawlRun, DeadLetter, RawPage
from ingest.parsers.gepnic import StaleSession
from ingest.ratelimit import RedisRateLimiter
from ingest.sources import get_source

log = logging.getLogger(__name__)

MAX_RETRIES = 5
_fetcher: Fetcher | None = None
_redis = None


def redis_client():
    global _redis
    if _redis is None:
        import redis

        _redis = redis.Redis.from_url(settings.REDIS_URL)
    return _redis


def worker_fetcher() -> Fetcher:
    """One HTTP client per worker process, sharing a Redis-backed politeness budget."""
    global _fetcher
    if _fetcher is None:
        _fetcher = Fetcher(
            RedisRateLimiter(redis_client(), settings.CRAWLER["MIN_INTERVAL_SECONDS"])
        )
    return _fetcher


def _cookie_key(run_id: int) -> str:
    return f"tenderlens:run:{run_id}:cookies"


def save_session(run_id: int, fetcher: Fetcher) -> None:
    redis_client().set(_cookie_key(run_id), json.dumps(fetcher.export_cookies()), ex=6 * 3600)


def load_session(run_id: int, fetcher: Fetcher, domain: str) -> bool:
    raw = redis_client().get(_cookie_key(run_id))
    if not raw:
        return False
    fetcher.load_cookies(json.loads(raw), domain)
    return True


class DeadLetterTask(Task):
    """When retries are exhausted, record the failure instead of losing it."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        payload = {"args": list(args), "kwargs": kwargs}
        url = kwargs.get("url") or (args[2] if len(args) > 2 else "")
        DeadLetter.objects.create(
            url=str(url),
            error=f"{type(exc).__name__}: {exc}",
            attempts=self.request.retries + 1,
            task_name=self.name,
            payload=json.loads(json.dumps(payload, default=str)),
        )
        run_id = kwargs.get("run_id") or (args[0] if args else None)
        tender_id = kwargs.get("tender_id") or (args[1] if len(args) > 1 else None)
        if run_id and tender_id:
            pipeline.record_outcome(run_id, tender_id, CrawlItem.Outcome.FAILED)
            pipeline.maybe_finalize(run_id)


@shared_task
def start_crawl(mode: str = "incremental", sources: list[str] | None = None) -> list[int]:
    run_ids = []
    for key in sources or settings.CRAWLER["SOURCES"]:
        get_source(key)  # fail fast on typos
        run = CrawlRun.objects.create(source=key, mode=mode)
        crawl_listing.delay(run.pk)
        run_ids.append(run.pk)
    return run_ids


@shared_task(
    bind=True,
    autoretry_for=(FetchError, StaleSession, httpx.TransportError),
    retry_backoff=30,
    retry_backoff_max=900,
    max_retries=3,
)
def crawl_listing(self, run_id: int, max_orgs: int | None = None) -> int:
    run = CrawlRun.objects.get(pk=run_id)
    if run.status != CrawlRun.Status.RUNNING:
        return 0
    source = get_source(run.source)
    fetcher = worker_fetcher()
    fetcher.reset_session()
    try:
        disc = pipeline.Crawler(source, fetcher, run).discover(mode=run.mode, max_orgs=max_orgs)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            CrawlRun.objects.filter(pk=run_id).update(
                status=CrawlRun.Status.FAILED, error=repr(exc), finished=timezone.now()
            )
        raise
    pipeline.record_plan(run, disc)
    save_session(run_id, fetcher)
    for job in disc.jobs:
        chain(
            fetch_detail.s(run_id, job.tender_id, job.url),
            parse_and_load.s(run_id, job.tender_id),
        ).apply_async()
    if not disc.jobs:
        pipeline.maybe_finalize(run_id)
    log.info(
        "run %s: dispatched %d detail fetches, skipped %d",
        run_id,
        len(disc.jobs),
        len(disc.skipped),
    )
    return len(disc.jobs)


@shared_task(
    bind=True,
    base=DeadLetterTask,
    autoretry_for=(FetchError, StaleSession, httpx.TransportError, TimeoutError),
    retry_backoff=True,  # 1s, 2s, 4s, ... with jitter
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def fetch_detail(self, run_id: int, tender_id: str, url: str) -> int:
    run = CrawlRun.objects.get(pk=run_id)
    source = get_source(run.source)
    fetcher = worker_fetcher()
    crawler = pipeline.Crawler(source, fetcher, run)
    if not load_session(run_id, fetcher, source.origin.split("://", 1)[1]):
        crawler.ensure_session()
    before = fetcher.export_cookies()
    page = crawler.fetch_detail(pipeline.DetailJob(tender_id, url, ""))
    if fetcher.export_cookies() != before:  # the crawler had to renew the session
        save_session(run_id, fetcher)
    return page.pk


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def parse_and_load(self, raw_page_id: int, run_id: int, tender_id: str) -> str:
    page = RawPage.objects.get(pk=raw_page_id)
    result = load_detail_page(page)
    pipeline.record_outcome(run_id, tender_id, result.outcome, raw_page_id)
    pipeline.maybe_finalize(run_id)
    return result.outcome


@shared_task
def close_stale_runs(max_age_hours: int = 6) -> list[int]:
    cutoff = timezone.now() - timedelta(hours=max_age_hours)
    closed = []
    for run in CrawlRun.objects.filter(status=CrawlRun.Status.RUNNING, started__lt=cutoff):
        pipeline.maybe_finalize(run.pk, force=True)
        closed.append(run.pk)
    return closed


@shared_task
def prune_raw_pages() -> int:
    """Index/listing pages are only needed for a few days; detail pages are kept."""
    cutoff = timezone.now() - timedelta(days=settings.CRAWLER["RAW_LISTING_RETENTION_DAYS"])
    deleted, _ = RawPage.objects.filter(
        kind__in=[RawPage.Kind.INDEX, RawPage.Kind.LISTING], fetched_at__lt=cutoff
    ).delete()
    return deleted
