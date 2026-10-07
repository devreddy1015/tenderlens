"""robots.txt gate (ingest/robots.py): a crawl run reads robots.txt before anything else and
follows RFC 9309 (2xx obey, 4xx allow, 5xx/network: last good copy or skip)."""

import time
from urllib.robotparser import RobotFileParser

import httpx
import pytest
from django.core.cache import cache

from ingest import pipeline, robots, tasks
from ingest.models import CrawlRun, RawPage
from ingest.sources import get_source
from tenders.models import Tender

pytestmark = pytest.mark.django_db

CENTRAL = get_source("central")  # https://eprocure.gov.in/eprocure/app
DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


@pytest.fixture(autouse=True)
def _fresh_cache():
    # The test cache outlives a test; a cached refusal would block other files' crawls.
    cache.clear()
    yield
    cache.clear()


def _cache_copy(body: str, *, status: int = 200, age_days: float = 0) -> None:
    cache.set(
        robots._key(CENTRAL.origin),
        {"status": status, "body": body, "fetched_at": time.time() - age_days * 86400},
        robots.KEEP_SECONDS * 2,  # outlive the copy's own age check
    )


def _assert_blocked(run: CrawlRun, portal, words: str) -> None:
    assert run.status == CrawlRun.Status.FAILED and run.finished
    assert words in run.error
    assert run.reconciliation["problems"] == [run.error]
    # Nothing but robots.txt was requested, and nothing was stored or loaded.
    assert set(portal.hits) == {"robots"} and portal.sessions == 0
    assert RawPage.objects.count() == 0 and Tender.objects.count() == 0


def test_404_means_no_rules_and_is_cached_for_a_day(portal):
    run = pipeline.run_sync("central", mode="full")
    assert run.status == CrawlRun.Status.SUCCEEDED and run.new == 7
    assert portal.hits["robots"] == 1
    pipeline.run_sync("central", mode="incremental")
    assert portal.hits["robots"] == 1  # the cached answer was reused


def test_allowing_robots_txt_is_obeyed(portal):
    portal.robots = httpx.Response(
        200, text="User-agent: *\nDisallow: /eprocure/app/private\nCrawl-delay: 1\n"
    )
    run = pipeline.run_sync("central", mode="full")
    assert run.status == CrawlRun.Status.SUCCEEDED and run.new == 7


def test_disallow_all_fails_the_run_and_fetches_nothing(portal):
    portal.robots = httpx.Response(200, text=DISALLOW_ALL)
    run = pipeline.run_sync("central", mode="full")
    _assert_blocked(run, portal, "robots.txt at https://eprocure.gov.in/robots.txt disallows")
    assert "TenderLens" in run.error


def test_a_group_for_our_agent_wins_over_the_star_group(portal):
    portal.robots = httpx.Response(
        200, text="User-agent: *\nAllow: /\n\nUser-agent: TenderLens\nDisallow: /eprocure/\n"
    )
    _assert_blocked(pipeline.run_sync("central", mode="full"), portal, "disallows")


def test_rules_for_other_bots_do_not_apply(portal):
    portal.robots = httpx.Response(200, text="User-agent: BadBot\nDisallow: /\n")
    assert pipeline.run_sync("central", mode="full").status == CrawlRun.Status.SUCCEEDED


def test_5xx_without_a_cached_copy_skips_the_run(portal):
    portal.robots = httpx.Response(503, text="busy")
    run = pipeline.run_sync("central", mode="full")
    _assert_blocked(run, portal, "could not be read")
    assert "no copy from the last 30 days" in run.error
    assert portal.hits["robots"] == 3  # the fetcher's retries (MAX_ATTEMPTS in tests)


def test_network_error_without_a_cached_copy_skips_the_run(portal):
    portal.robots = httpx.ConnectError("connection refused")
    _assert_blocked(pipeline.run_sync("central", mode="full"), portal, "could not be read")


def test_5xx_uses_the_last_good_copy(portal):
    _cache_copy("User-agent: *\nDisallow:\n", age_days=3)  # stale for 24 h, kept for 30 days
    portal.robots = httpx.Response(500, text="oops")
    run = pipeline.run_sync("central", mode="full")
    assert run.status == CrawlRun.Status.SUCCEEDED and run.new == 7
    assert portal.hits["robots"] == 3  # it did try to refresh first


def test_5xx_with_a_cached_refusal_still_refuses(portal):
    _cache_copy(DISALLOW_ALL, age_days=3)
    portal.robots = httpx.Response(502, text="bad gateway")
    _assert_blocked(pipeline.run_sync("central", mode="full"), portal, "disallows")


def test_5xx_ignores_a_copy_older_than_30_days(portal):
    _cache_copy("User-agent: *\nDisallow:\n", age_days=31)
    portal.robots = httpx.Response(503, text="busy")
    _assert_blocked(pipeline.run_sync("central", mode="full"), portal, "could not be read")


def test_a_fresh_copy_is_used_without_fetching(portal):
    _cache_copy(DISALLOW_ALL, age_days=0.5)
    run = pipeline.run_sync("central", mode="full")
    assert portal.hits == {} and run.status == CrawlRun.Status.FAILED


def test_good_answers_refresh_the_cache(portal):
    _cache_copy(DISALLOW_ALL, age_days=2)
    portal.robots = httpx.Response(200, text="User-agent: *\nAllow: /\n")
    assert pipeline.run_sync("central", mode="full").status == CrawlRun.Status.SUCCEEDED
    copy = cache.get(robots._key(CENTRAL.origin))
    assert copy["status"] == 200 and "Allow" in copy["body"]
    assert time.time() - copy["fetched_at"] < 60


def test_celery_crawl_listing_is_gated_too(portal):
    portal.robots = httpx.Response(200, text=DISALLOW_ALL)
    run = CrawlRun.objects.create(source="central", mode="full")
    assert tasks.crawl_listing.apply(args=(run.pk,)).get() == 0
    run.refresh_from_db()
    _assert_blocked(run, portal, "disallows")


# --- RFC 9309 matching ------------------------------------------------------------------


def _parser(text: str) -> RobotFileParser:
    p = RobotFileParser()
    p.parse(text.splitlines())
    return p


AGENT = "TenderLens/0.1 (+https://example.org)"
INDEX = "https://eprocure.gov.in/eprocure/app?page=FrontEndTendersByOrganisation&service=page"


@pytest.mark.parametrize(
    "text,allowed",
    [
        ("", True),
        (DISALLOW_ALL, False),
        ("User-agent: *\nDisallow:\n", True),
        # Longest match wins, whatever the order (robotparser alone takes the first).
        ("User-agent: *\nAllow: /\nDisallow: /eprocure/\n", False),
        ("User-agent: *\nDisallow: /\nAllow: /eprocure/\n", True),
        # Wildcards and the end anchor.
        ("User-agent: *\nDisallow: /*FrontEndTendersByOrganisation\n", False),
        ("User-agent: *\nDisallow: /eprocure/app$\n", True),
        ("User-agent: *\nDisallow: /*.pdf$\n", True),
        # Allow wins a tie.
        ("User-agent: *\nDisallow: /eprocure\nAllow: /eprocure\n", True),
        ("User-agent: tenderlens\nDisallow: /\n", False),  # agent names are case-insensitive
    ],
)
def test_can_fetch_follows_rfc_9309(text, allowed):
    assert robots.can_fetch(_parser(text), AGENT, INDEX) is allowed
