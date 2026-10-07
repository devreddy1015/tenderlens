"""Source registry, adapter dispatch, crawl scheduling and GET /api/sources."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from ingest import pipeline, tasks
from ingest.fetcher import FetchResult
from ingest.loader import load_detail_page
from ingest.models import CrawlRun, RawPage
from ingest.parsers import DETAIL_PARSERS, gepnic
from ingest.schedule import crawl_beat_schedule
from ingest.sources import SOURCES, Source, get_source, resolve_keys
from tenders.models import Tender
from tenders.pincode import ALL_STATES
from tests.conftest import fixture_text

pytestmark = pytest.mark.django_db

PORTALS = "gepnic_portals/"


# --- registry ---------------------------------------------------------------------------


def test_registry_is_well_formed():
    hosts = [s.host for s in SOURCES.values()]
    assert len(hosts) == len(set(hosts)), "one portal must not be crawled twice"
    assert len(SOURCES) >= 35
    for key, s in SOURCES.items():
        assert key == s.key and len(key) <= 32  # CrawlRun.source / RawPage.source width
        assert s.kind == "gepnic"
        assert s.base_url.startswith("https://") and s.base_url.endswith("/app")
        assert s.state is None or s.state in ALL_STATES, s.state
        assert s.url.startswith(s.origin)
    # Multi-state portals derive the state from the pincode.
    assert {k for k, s in SOURCES.items() if s.state is None} >= {"central", "defence", "ntpc"}


def test_every_state_portal_is_a_different_state():
    states = [s.state for s in SOURCES.values() if s.state]
    assert len(states) == len(set(states))


def test_resolve_keys_all_and_explicit():
    assert resolve_keys(["all"]) == [s.key for s in SOURCES.values() if s.enabled]
    assert resolve_keys(["mp", " central", "", "mp"]) == ["mp", "central"]
    assert resolve_keys(["central", "all"])[0] == "central"
    assert len(resolve_keys(["central", "all"])) == sum(s.enabled for s in SOURCES.values())
    with pytest.raises(ValueError, match="unknown source 'nowhere'"):
        resolve_keys(["central", "nowhere"])


def test_portals_that_disallow_robots_are_disabled():
    # mahatenders.gov.in/robots.txt disallows everything (checked 2026-10-07).
    assert SOURCES["maharashtra"].enabled is False
    assert "maharashtra" not in resolve_keys(["all"])


def test_disabled_source_is_left_out_of_all(monkeypatch):
    off = Source("off", "Switched off", "https://off.example/nicgep/app", enabled=False)
    monkeypatch.setitem(SOURCES, "off", off)
    assert "off" not in resolve_keys(["all"])
    assert resolve_keys(["off"]) == ["off"]  # still crawlable by name


# --- parser generalises to the new portals ----------------------------------------------


@pytest.mark.parametrize(
    "fixture,orgs,tenders,first",
    [
        ("defproc_org_index.html", 11, 4632, "Department of Defence"),
        ("tn_org_index.html", 62, 5343, "Anna University Chennai"),
    ],
)
def test_new_portal_indexes_parse(fixture, orgs, tenders, first):
    rows = gepnic.parse_org_index(fixture_text(PORTALS + fixture))
    assert len(rows) == orgs
    assert sum(r.tender_count for r in rows) == tenders
    assert rows[0].name == first
    assert all("/nicgep/app?" in r.href and "sp=" in r.href for r in rows)


def test_new_portal_listing_and_detail_parse():
    rows = gepnic.parse_org_listing(fixture_text(PORTALS + "dnh_org_listing.html"))
    assert len(rows) == 17  # the index claimed 17 for this organisation
    assert len({r.tender_id for r in rows}) == 17
    assert rows[0].tender_id == "2026_UTDNH_8287_1"
    d = gepnic.parse_detail(fixture_text(PORTALS + "dnh_detail.html"))
    assert d["tender_id"] == "2026_UTDNH_8287_1"
    assert d["value"] == "80,58,645" and d["emd"] == "1,61,172"
    assert d["closes"] == "13-Oct-2026 02:00 PM"
    assert d["org_chain"].startswith("UT Administration of Dadra and Nagar Haveli")


def test_state_portal_tender_takes_the_portal_state(make_page):
    page = make_page(fixture_text(PORTALS + "dnh_detail.html"), source="dnh")
    result = load_detail_page(page)
    assert result.outcome == "new"
    t = Tender.objects.get(pk=result.tender_id)
    assert (t.source, t.state) == ("dnh", "Dadra and Nagar Haveli and Daman and Diu")
    assert t.value_inr == 8058645


def test_multi_state_portal_derives_state_from_pincode(make_page):
    page = make_page(fixture_text(PORTALS + "dnh_detail.html"), source="defence")
    t = Tender.objects.get(pk=load_detail_page(page).tender_id)
    assert t.state == "Dadra and Nagar Haveli and Daman and Diu"  # pincode 396230


# --- adapter dispatch -------------------------------------------------------------------


def test_new_gepnic_source_crawls_end_to_end(portal):
    """The fake portal answers on any host, so this runs the real GePNIC path for 'up'."""
    run = pipeline.run_sync("up", mode="full")
    assert run.status == CrawlRun.Status.SUCCEEDED and run.new == 7
    assert set(Tender.objects.values_list("source", "state").distinct()) == {
        ("up", "Uttar Pradesh")
    }
    assert set(RawPage.objects.values_list("source", flat=True)) == {"up"}


def test_unknown_kind_has_no_crawler():
    gem = Source("gem", "GeM", "https://gem.example/app", kind="gem")
    with pytest.raises(NotImplementedError, match="no crawler for source kind 'gem'"):
        pipeline.crawler_for(gem, fetcher=None)


def test_pipeline_dispatches_on_kind(monkeypatch, make_page):
    """A non-GePNIC adapter only supplies discovery and detail fetching (plus a detail
    parser); planning, bookkeeping, loading and reconciliation stay shared."""
    detail = fixture_text(PORTALS + "dnh_detail.html")

    class FakeCrawler:
        def __init__(self, source, fetcher, run=None):
            self.source, self.run = source, run

        def discover(self, *, mode="incremental", max_orgs=None):
            disc = pipeline.Discovery(expected=1, listed=1)
            disc.jobs.append(pipeline.DetailJob("2026_UTDNH_8287_1", "https://x/1", "UT"))
            return disc

        def fetch_detail(self, job):
            page = make_page(detail, source=self.source.key, url=job.url)
            RawPage.objects.filter(pk=page.pk).update(crawl_run=self.run)
            return page

    other = Source("other", "Other portal", "https://other.example/app", "Goa", kind="cppp")
    monkeypatch.setitem(SOURCES, "other", other)
    monkeypatch.setitem(pipeline.CRAWLERS, "cppp", FakeCrawler)
    monkeypatch.setitem(DETAIL_PARSERS, "cppp", gepnic)

    class NoRobots:  # the robots.txt gate (ingest/robots.py) gets a 404: no rules
        def get(self, url, **kw):
            return FetchResult(url=url, status=404, body="", fetched_at=timezone.now())

    run = pipeline.run_sync("other", mode="full", fetcher=NoRobots())
    assert run.status == CrawlRun.Status.SUCCEEDED and run.new == 1
    assert Tender.objects.get().state == "Goa"


# --- scheduling -------------------------------------------------------------------------


def test_beat_schedule_staggers_every_source():
    keys = resolve_keys(["all"])
    beat = crawl_beat_schedule(["all"])
    assert len(beat) == 2 * len(keys)
    hourly = [beat[f"crawl-incremental-{k}"] for k in keys]
    nightly = [beat[f"crawl-full-{k}"] for k in keys]
    assert [e["kwargs"] for e in hourly] == [{"mode": "incremental", "sources": [k]} for k in keys]
    assert all(e["kwargs"]["mode"] == "full" for e in nightly)
    minutes = [next(iter(e["schedule"].minute)) for e in hourly]
    assert len(set(minutes)) == len(minutes) and min(minutes) == 5 and max(minutes) < 50
    starts = [(next(iter(e["schedule"].hour)), next(iter(e["schedule"].minute))) for e in nightly]
    assert len(set(starts)) == len(starts)
    assert min(starts) == (1, 0) and max(starts) < (4, 0)  # done starting before pruning


def test_beat_schedule_rejects_unknown_source():
    with pytest.raises(ValueError):
        crawl_beat_schedule(["central", "atlantis"])


def test_settings_schedule_has_per_source_crawls(settings):
    keys = resolve_keys(settings.CRAWLER["SOURCES"])
    assert {f"crawl-incremental-{k}" for k in keys} <= set(settings.CELERY_BEAT_SCHEDULE)
    assert "hourly-incremental-crawl" not in settings.CELERY_BEAT_SCHEDULE


@pytest.fixture
def queued(monkeypatch):
    sent = []
    monkeypatch.setattr(tasks.crawl_listing, "delay", lambda run_id: sent.append(run_id))
    return sent


def test_start_crawl_all_queues_every_enabled_source(settings, queued):
    settings.CRAWLER = {**settings.CRAWLER, "SOURCES": ["all"]}
    ids = tasks.start_crawl.apply(kwargs={"mode": "incremental"}).get()
    assert len(ids) == len(queued) == len(resolve_keys(["all"]))
    assert set(CrawlRun.objects.values_list("source", flat=True)) == set(resolve_keys(["all"]))


def test_start_crawl_skips_a_source_still_running(queued):
    busy = CrawlRun.objects.create(source="mp", mode="full")
    stale = CrawlRun.objects.create(source="kerala", mode="full")
    CrawlRun.objects.filter(pk=stale.pk).update(started=timezone.now() - timedelta(hours=7))
    ids = tasks.start_crawl.apply(kwargs={"sources": ["mp", "kerala", "odisha"]}).get()
    started = set(CrawlRun.objects.filter(pk__in=ids).values_list("source", flat=True))
    assert started == {"kerala", "odisha"}  # a run older than the stale cutoff never blocks
    assert busy.pk not in ids


def test_start_crawl_rejects_unknown_source(queued):
    with pytest.raises(ValueError):
        tasks.start_crawl.apply(kwargs={"sources": ["nowhere"]}).get()
    assert not CrawlRun.objects.exists()


# --- GET /api/sources -------------------------------------------------------------------

CONTRACT_KEYS = {"key", "name", "kind", "state", "url", "open_tenders", "last_run", "enabled"}


@pytest.fixture
def api():
    return APIClient()


def test_sources_contract_shape(api, settings):
    settings.CRAWLER = {**settings.CRAWLER, "SOURCES": ["central", "mp"]}
    r = api.get("/api/sources")
    assert r.status_code == 200
    body = r.json()
    assert [s["key"] for s in body] == list(SOURCES)
    for s in body:
        assert set(s) >= CONTRACT_KEYS and set(s) - CONTRACT_KEYS <= {"last_success"}
        assert s["kind"] in {"gepnic", "gem", "cppp"}
        assert s["open_tenders"] == 0 and s["last_run"] is None and s["last_success"] is None
    by_key = {s["key"]: s for s in body}
    assert by_key["central"]["state"] is None
    assert by_key["mp"]["state"] == "Madhya Pradesh"
    assert by_key["mp"]["url"] == "https://mptenders.gov.in/nicgep/app"
    assert {k for k, s in by_key.items() if s["enabled"]} == {"central", "mp"}


def test_sources_counts_and_runs(api, make_page, settings, django_assert_max_num_queries):
    settings.CRAWLER = {**settings.CRAWLER, "SOURCES": ["all"]}
    for source in ("mp", "mp", "dnh"):
        html = fixture_text(PORTALS + "dnh_detail.html")
        if source == "mp" and Tender.objects.filter(source="mp").exists():
            html = html.replace("2026_UTDNH_8287_1", "2026_MP_1_1")
        load_detail_page(make_page(html, source=source))
    now = timezone.now()
    Tender.objects.update(published_at=now - timedelta(days=2), closes_at=now + timedelta(days=3))
    Tender.objects.filter(source="dnh").update(closes_at=now - timedelta(days=1))  # closed

    ok = CrawlRun.objects.create(source="mp", status="succeeded", new=2, updated=1)
    CrawlRun.objects.filter(pk=ok.pk).update(
        started=now - timedelta(hours=2), finished=now - timedelta(hours=1)
    )
    CrawlRun.objects.create(source="mp", status="running")  # newest, still going
    failed = CrawlRun.objects.create(source="dnh", status="failed", finished=now)

    with django_assert_max_num_queries(3):
        body = {s["key"]: s for s in api.get("/api/sources").json()}
    mp, dnh = body["mp"], body["dnh"]
    assert mp["open_tenders"] == 2 and dnh["open_tenders"] == 0
    assert mp["last_run"] == {"status": "running", "finished": None, "new": 0, "updated": 0}
    assert mp["last_success"] is not None
    assert dnh["last_run"]["status"] == "failed" and dnh["last_success"] is None
    assert dnh["last_run"]["finished"] is not None
    assert failed.source == "dnh"
    assert {k for k, s in body.items() if not s["enabled"]} == {"maharashtra"}  # robots.txt


def test_sources_is_public_and_read_only(api):
    assert api.get("/api/sources").status_code == 200  # no login needed
    assert api.post("/api/sources", {}).status_code == 405


def test_get_source_still_raises_for_unknown_keys():
    with pytest.raises(ValueError):
        get_source("atlantis")
