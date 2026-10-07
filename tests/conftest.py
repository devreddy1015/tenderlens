import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

FIXTURES = Path(__file__).parent / "fixtures"
CENTRAL = FIXTURES / "gepnic_central"
BASE = "https://eprocure.gov.in/eprocure/app"


def fixture_text(relpath: str) -> str:
    return (FIXTURES / relpath).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _test_settings(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    # Private per-test cache: throttle counters must not leak between tests or runs.
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests"}
    }
    settings.CRAWLER = {**settings.CRAWLER, "MIN_INTERVAL_SECONDS": 0.0, "MAX_ATTEMPTS": 3}


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    monkeypatch.setattr("ingest.fetcher.time.sleep", lambda s: None)
    monkeypatch.setattr("ingest.ratelimit.time.sleep", lambda s: None)


class FakePortal:
    """Serves real saved GePNIC pages through respx.

    The org index lists one organisation (AMU, 7 tenders). Each detail page is the real
    detail_01.html with its Tender ID swapped for the one the listing row points at, so
    every tender in the listing gets a realistic, distinct detail page.
    """

    def __init__(self, router: respx.Router):
        self.router = router
        self.index_html = fixture_text("gepnic_central/org_index_small.html")
        self.listing_html = fixture_text("gepnic_central/org_list_amu.html")
        self.detail_template = fixture_text("gepnic_central/detail_01.html")
        self.stale_html = fixture_text("gepnic_central/stale_session.html")
        from ingest.parsers import gepnic

        self.rows = gepnic.parse_org_listing(self.listing_html)
        self.by_sp = {self._sp(r.href): r for r in self.rows}
        self.stale_next: set[str] = set()  # sp values that return a stale page once
        self.fail_detail: dict[str, int] = {}  # sp -> number of 503s still to serve
        self.overrides: dict[str, str] = {}  # sp -> full html override
        self.hits: dict[str, int] = {}
        self.sessions = 0
        # robots.txt (ingest/robots.py): GePNIC portals answer 404, i.e. no rules.
        self.robots: httpx.Response | Exception = httpx.Response(404, text="Not Found")
        router.get(url__regex=r".*").mock(side_effect=self._handle)

    @staticmethod
    def _sp(href: str) -> str:
        return parse_qs(urlsplit(href.replace("&amp;", "&")).query).get("sp", [""])[0]

    TEMPLATE_TITLE = (
        "Providing Spare / Emergency Supply Cable and its Accessories from Substation of "
        "Trauma Centre to Central Sterilization Service Department (CSSD) JNMCH, AMU, Aligarh"
    )

    def detail_html(self, row) -> str:
        """detail_01.html rewritten to carry this listing row's id, title and dates."""
        html = self.detail_template.replace("2026_AMU_926330_3", row.tender_id)
        html = html.replace(self.TEMPLATE_TITLE, row.title)
        html = html.replace("01-Oct-2026 04:00 PM", row.published)  # published
        html = html.replace("07-Oct-2026 11:00 AM", row.closes)  # submission end
        return html.replace("08-Oct-2026 11:00 AM", row.opens)  # bid opening

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if urlsplit(url).path == "/robots.txt":
            self.hits["robots"] = self.hits.get("robots", 0) + 1
            if isinstance(self.robots, Exception):
                raise self.robots
            return self.robots
        q = parse_qs(urlsplit(url).query)
        page = q.get("page", [""])[0]
        sp = q.get("sp", [""])[0]
        self.hits[page or "root"] = self.hits.get(page or "root", 0) + 1
        cookies = {"set-cookie": "JSESSIONID=abc123; Path=/"}
        if not page:
            self.sessions += 1
            return httpx.Response(200, text="<html>home</html>", headers=cookies)
        if page == "FrontEndTendersByOrganisation" and not sp:
            return httpx.Response(200, text=self.index_html, headers=cookies)
        if page == "FrontEndTendersByOrganisation":
            return httpx.Response(200, text=self.listing_html)
        if page == "FrontEndViewTender":
            if sp in self.stale_next:
                self.stale_next.discard(sp)
                return httpx.Response(200, text=self.stale_html)
            if self.fail_detail.get(sp, 0) > 0:
                self.fail_detail[sp] -= 1
                return httpx.Response(503, text="busy")
            if sp in self.overrides:
                return httpx.Response(200, text=self.overrides[sp])
            row = self.by_sp.get(sp)
            if row is None:
                return httpx.Response(404, text="not found")
            return httpx.Response(200, text=self.detail_html(row))
        return httpx.Response(404, text="unexpected " + url)

    def sp_of(self, tender_id: str) -> str:
        return next(self._sp(r.href) for r in self.rows if r.tender_id == tender_id)


@pytest.fixture
def portal():
    with respx.mock(assert_all_called=False) as router:
        yield FakePortal(router)


@pytest.fixture
def make_page(db):
    """Store an HTML string as a RawPage, like the crawler would."""
    import hashlib

    from django.utils import timezone

    from ingest.models import RawPage

    def _make(
        html: str, *, fetched_at=None, source="central", url=BASE + "?page=FrontEndViewTender"
    ):
        return RawPage.objects.create(
            source=source,
            kind=RawPage.Kind.DETAIL,
            url=url,
            fetched_at=fetched_at or timezone.now(),
            status=200,
            body_hash=hashlib.sha256(html.encode()).hexdigest(),
            body=html,
        )

    return _make


def strip_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
