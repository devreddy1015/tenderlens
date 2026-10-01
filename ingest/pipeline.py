"""Crawl logic shared by the synchronous command and the Celery tasks.

Flow per source:
  1. organisation index  -> how many tenders each organisation claims (for reconciliation)
  2. organisation pages  -> one ListingRow per tender
  3. plan                -> incremental mode skips tenders whose listing row is unchanged
  4. detail pages        -> stored in raw_page first, then parsed and loaded
"""

import hashlib
import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from ingest.fetcher import Fetcher, FetchError
from ingest.models import CrawlItem, CrawlRun, RawPage
from ingest.parsers import gepnic
from ingest.ratelimit import LocalRateLimiter
from ingest.sources import Source, get_source
from ingest.validation import parse_ist
from tenders.models import Tender

log = logging.getLogger(__name__)


@dataclass
class DetailJob:
    tender_id: str
    url: str
    organisation: str


@dataclass
class Discovery:
    jobs: list[DetailJob] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    expected: int | None = 0
    listed: int = 0
    org_mismatches: list[dict] = field(default_factory=list)


def make_fetcher() -> Fetcher:
    return Fetcher(LocalRateLimiter(settings.CRAWLER["MIN_INTERVAL_SECONDS"]))


class Crawler:
    def __init__(self, source: Source, fetcher: Fetcher, run: CrawlRun | None = None):
        self.source = source
        self.fetcher = fetcher
        self.run = run

    # --- fetching ---------------------------------------------------------------

    def ensure_session(self) -> None:
        """GePNIC links work in any live session; a GET of the app root creates one."""
        self.fetcher.reset_session()
        self.fetcher.get(self.source.base_url)

    def fetch_page(
        self, url: str, kind: str, *, tender_id: str = "", referer: str | None = None
    ) -> RawPage:
        result = self.fetcher.get(url, referer=referer)
        if gepnic.is_stale_session(result.body):
            log.info("stale session on %s, starting a new one", url)
            self.ensure_session()
            result = self.fetcher.get(url, referer=referer)
            if gepnic.is_stale_session(result.body):
                raise gepnic.StaleSession(url)
        if result.status >= 400:
            raise FetchError(f"{url}: HTTP {result.status}")
        page = RawPage.objects.create(
            source=self.source.key,
            kind=kind,
            url=url,
            fetched_at=result.fetched_at,
            status=result.status,
            body_hash=hashlib.sha256(result.body.encode()).hexdigest(),
            body=result.body,
            crawl_run=self.run,
            source_tender_id=tender_id,
        )
        if self.run is not None:
            CrawlRun.objects.filter(pk=self.run.pk).update(pages=F("pages") + 1)
        return page

    # --- discovery --------------------------------------------------------------

    def discover(self, *, mode: str = "incremental", max_orgs: int | None = None) -> Discovery:
        index_page = self.fetch_page(self.source.org_index_url, RawPage.Kind.INDEX)
        orgs = gepnic.parse_org_index(index_page.body)
        if max_orgs:
            orgs = orgs[:max_orgs]
        disc = Discovery(expected=sum(o.tender_count for o in orgs))
        rows_by_id: dict[str, tuple[gepnic.ListingRow, str]] = {}
        for org in orgs:
            listing = self.fetch_page(
                self.source.absolute(org.href),
                RawPage.Kind.LISTING,
                referer=self.source.org_index_url,
            )
            rows = gepnic.parse_org_listing(listing.body)
            if len(rows) != org.tender_count:
                disc.org_mismatches.append(
                    {"organisation": org.name, "claimed": org.tender_count, "listed": len(rows)}
                )
            for row in rows:
                if row.tender_id:
                    rows_by_id.setdefault(row.tender_id, (row, org.name))
            disc.listed += len(rows)
        self._plan(disc, rows_by_id, mode)
        return disc

    def _plan(self, disc: Discovery, rows_by_id: dict, mode: str) -> None:
        existing = {}
        if mode == "incremental" and rows_by_id:
            existing = {
                t["source_tender_id"]: t
                for t in Tender.objects.filter(
                    source=self.source.key, source_tender_id__in=list(rows_by_id)
                ).values("source_tender_id", "title", "closes_at", "published_at")
            }
        for tender_id, (row, org_name) in rows_by_id.items():
            known = existing.get(tender_id)
            if known is not None and _listing_unchanged(row, known):
                disc.skipped.append(tender_id)
            else:
                disc.jobs.append(DetailJob(tender_id, self.source.absolute(row.href), org_name))

    def fetch_detail(self, job: DetailJob) -> RawPage:
        return self.fetch_page(job.url, RawPage.Kind.DETAIL, tender_id=job.tender_id)


def _listing_unchanged(row: gepnic.ListingRow, known: dict) -> bool:
    """A corrigendum almost always moves a date; the title check catches the rest."""
    try:
        closes = parse_ist(row.closes)
        published = parse_ist(row.published)
    except ValueError:
        return False
    return (
        closes == known["closes_at"]
        and published == known["published_at"]
        and (row.title.strip() == known["title"].strip())
    )


# --- run bookkeeping (used by both sync and Celery paths) -------------------------


def record_plan(run: CrawlRun, disc: Discovery) -> None:
    now = timezone.now()
    CrawlItem.objects.bulk_create(
        [
            CrawlItem(crawl_run=run, source_tender_id=j.tender_id, organisation=j.organisation)
            for j in disc.jobs
        ]
        + [
            CrawlItem(crawl_run=run, source_tender_id=t, outcome=CrawlItem.Outcome.SKIPPED)
            for t in disc.skipped
        ],
        # A redelivered crawl_listing must not reset items that already finished.
        ignore_conflicts=True,
    )
    if disc.skipped:
        Tender.objects.filter(source=run.source, source_tender_id__in=disc.skipped).update(
            last_seen=now
        )
    CrawlRun.objects.filter(pk=run.pk).update(
        expected=disc.expected,
        listed=disc.listed,
        reconciliation={"organisation_mismatches": disc.org_mismatches},
    )


def record_outcome(
    run_id: int, tender_id: str, outcome: str, raw_page_id: int | None = None
) -> None:
    CrawlItem.objects.update_or_create(
        crawl_run_id=run_id,
        source_tender_id=tender_id,
        defaults={"outcome": outcome, "raw_page_id": raw_page_id},
    )


def maybe_finalize(run_id: int, *, force: bool = False) -> CrawlRun | None:
    """Close the run once no item is pending. Safe to call concurrently and repeatedly."""
    with transaction.atomic():
        run = CrawlRun.objects.select_for_update().get(pk=run_id)
        if run.status != CrawlRun.Status.RUNNING:
            return run
        counts = dict(
            CrawlItem.objects.filter(crawl_run_id=run_id)
            .values_list("outcome")
            .annotate(n=Count("id"))
            .values_list("outcome", "n")
        )
        pending = counts.get(CrawlItem.Outcome.PENDING, 0)
        if pending and not force:
            return None
        Out = CrawlItem.Outcome
        run.new = counts.get(Out.NEW, 0)
        run.updated = counts.get(Out.UPDATED, 0)
        run.unchanged = counts.get(Out.UNCHANGED, 0)
        run.skipped = counts.get(Out.SKIPPED, 0)
        run.quarantined = counts.get(Out.QUARANTINED, 0)
        run.failed = counts.get(Out.FAILED, 0)
        accounted = sum(counts.values()) - pending
        rec = dict(run.reconciliation or {})
        rec.update(
            {
                "expected_from_index": run.expected,
                "listed_rows": run.listed,
                "distinct_tenders": sum(counts.values()),
                "accounted": accounted,
                "loaded": run.new + run.updated + run.unchanged + run.skipped,
                "pending": pending,
            }
        )
        problems = []
        if run.expected is not None and run.listed is not None and run.expected != run.listed:
            problems.append(f"index claims {run.expected} tenders, listings show {run.listed}")
        if pending:
            problems.append(f"{pending} tenders never finished")
        if run.failed:
            problems.append(f"{run.failed} tenders dead-lettered")
        rec["problems"] = problems
        run.reconciliation = rec
        if force and pending:
            run.status = CrawlRun.Status.INCOMPLETE
        elif problems:
            run.status = CrawlRun.Status.MISMATCH
        else:
            run.status = CrawlRun.Status.SUCCEEDED
        run.finished = timezone.now()
        run.save()
    if problems:
        log.warning("crawl run %s reconciliation: %s", run_id, "; ".join(problems))
    log.info(
        "crawl run %s %s: new=%s updated=%s unchanged=%s skipped=%s quarantined=%s failed=%s",
        run.pk,
        run.status,
        run.new,
        run.updated,
        run.unchanged,
        run.skipped,
        run.quarantined,
        run.failed,
    )
    return run


def run_sync(
    source_key: str,
    *,
    mode: str = "incremental",
    max_orgs: int | None = None,
    max_details: int | None = None,
    fetcher: Fetcher | None = None,
) -> CrawlRun:
    """Whole crawl in one process. Used by `manage.py crawl --sync` and the tests."""
    from ingest.loader import load_detail_page
    from ingest.models import DeadLetter

    source = get_source(source_key)
    run = CrawlRun.objects.create(source=source.key, mode=mode)
    own_fetcher = fetcher is None
    fetcher = fetcher or make_fetcher()
    try:
        crawler = Crawler(source, fetcher, run)
        disc = crawler.discover(mode=mode, max_orgs=max_orgs)
        if max_details is not None and len(disc.jobs) > max_details:
            # A deliberately partial crawl: the index count no longer applies.
            disc.jobs = disc.jobs[:max_details]
            disc.listed = len(disc.jobs) + len(disc.skipped)
            disc.expected = None
        record_plan(run, disc)
        for job in disc.jobs:
            try:
                page = crawler.fetch_detail(job)
            except (FetchError, gepnic.StaleSession) as exc:
                DeadLetter.objects.create(
                    url=job.url,
                    error=str(exc),
                    attempts=fetcher.max_attempts,
                    task_name="run_sync.fetch_detail",
                    payload={"run_id": run.pk, "tender_id": job.tender_id},
                )
                record_outcome(run.pk, job.tender_id, CrawlItem.Outcome.FAILED)
                continue
            result = load_detail_page(page)
            record_outcome(run.pk, job.tender_id, result.outcome, page.pk)
    except Exception as exc:
        CrawlRun.objects.filter(pk=run.pk).update(
            status=CrawlRun.Status.FAILED, error=repr(exc), finished=timezone.now()
        )
        raise
    finally:
        if own_fetcher:
            fetcher.close()
    return maybe_finalize(run.pk) or run
