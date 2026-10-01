from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from ingest.loader import load_detail_page
from ingest.models import Quarantine
from tenders.models import Tender
from tests.conftest import CENTRAL, fixture_text

pytestmark = pytest.mark.django_db


def test_load_twice_gives_same_rows(make_page):
    html = fixture_text("gepnic_central/detail_01.html")
    first = load_detail_page(make_page(html))
    second = load_detail_page(make_page(html))
    assert first.outcome == "new"
    assert second.outcome == "unchanged"
    assert first.tender_id == second.tender_id
    assert Tender.objects.count() == 1


def test_all_fixtures_load_and_reload_idempotently(make_page):
    pages = [p.read_text(encoding="utf-8") for p in sorted(CENTRAL.glob("detail_*.html"))]
    outcomes = [load_detail_page(make_page(h)).outcome for h in pages]
    assert outcomes == ["new"] * len(pages)
    again = [load_detail_page(make_page(h)).outcome for h in pages]
    assert again == ["unchanged"] * len(pages)
    assert Tender.objects.count() == len(pages)


def test_changed_content_updates_and_keeps_first_seen(make_page):
    html = fixture_text("gepnic_central/detail_01.html")
    t0 = timezone.now() - timedelta(hours=2)
    load_detail_page(make_page(html, fetched_at=t0))
    corrigendum = html.replace("07-Oct-2026 11:00 AM", "14-Oct-2026 11:00 AM")
    res = load_detail_page(make_page(corrigendum))
    assert res.outcome == "updated"
    t = Tender.objects.get()
    assert t.closes_at.day == 14
    assert t.first_seen == t0
    assert t.last_seen > t0


def test_backfill_of_older_page_never_overwrites_newer_data(make_page):
    old_html = fixture_text("gepnic_central/detail_01.html")
    new_html = old_html.replace("07-Oct-2026 11:00 AM", "14-Oct-2026 11:00 AM")
    now = timezone.now()
    load_detail_page(make_page(new_html, fetched_at=now))
    res = load_detail_page(make_page(old_html, fetched_at=now - timedelta(days=1)))
    assert res.outcome == "unchanged"
    assert Tender.objects.get().closes_at.day == 14


def test_unchanged_reload_bumps_last_seen(make_page):
    html = fixture_text("gepnic_central/detail_01.html")
    t0 = timezone.now() - timedelta(hours=3)
    load_detail_page(make_page(html, fetched_at=t0))
    load_detail_page(make_page(html))
    assert Tender.objects.get().last_seen > t0


@pytest.mark.parametrize(
    "fixture,field",
    [
        ("broken/detail_closes_before_published.html", "__root__"),
        ("broken/detail_bad_date_negative_value.html", "published_at"),
        ("broken/detail_missing_tender_id.html", "source_tender_id"),
    ],
)
def test_broken_fixture_lands_in_quarantine_with_reason(make_page, fixture, field):
    page = make_page(fixture_text(fixture))
    res = load_detail_page(page)
    assert res.outcome == "quarantined"
    assert Tender.objects.count() == 0
    q = Quarantine.objects.get()
    assert q.raw_page_id == page.id
    assert q.payload["org_chain"].startswith("Aligarh Muslim University")
    assert q.errors and all(e["error"] for e in q.errors)
    if field != "__root__":
        assert field in {e["field"] for e in q.errors}
    else:
        assert "is before published_at" in q.errors[0]["error"]


def test_non_detail_page_is_quarantined_not_dropped(make_page):
    res = load_detail_page(make_page("<html><body>Service unavailable</body></html>"))
    assert res.outcome == "quarantined"
    assert Quarantine.objects.get().errors[0]["field"] == "__page__"


def test_database_enforces_uniqueness_and_date_order():
    now = timezone.now()
    base = dict(
        source="central",
        source_tender_id="X1",
        title="t",
        buyer_raw="b",
        published_at=now,
        closes_at=now,
        content_hash="h",
        fetched_at=now,
        first_seen=now,
        last_seen=now,
    )
    Tender.objects.create(**base)
    with pytest.raises(IntegrityError), transaction.atomic():
        Tender.objects.create(**base)
    with pytest.raises(IntegrityError), transaction.atomic():
        Tender.objects.create(
            **{**base, "source_tender_id": "X2", "closes_at": now - timedelta(days=1)}
        )


def test_state_is_derived_from_pincode_for_central_portal(make_page):
    load_detail_page(make_page(fixture_text("gepnic_central/detail_02.html")))  # Raigarh 496001
    assert Tender.objects.get().state == "Chhattisgarh"


def test_real_portal_page_with_impossible_dates_is_quarantined(make_page):
    """Captured from the live crawl: the portal's detail page says 'Published 18-Oct-2026'
    (its own listing says 18-Sep) and bid submission closes on 03-Oct-2026."""
    res = load_detail_page(make_page(fixture_text("broken/real_published_after_closing.html")))
    assert res.outcome == "quarantined"
    q = Quarantine.objects.get()
    assert q.payload["tender_id"] == "2026_RMLH_926750_1"
    assert q.errors[0]["input"] == {
        "published": "18-Oct-2026 02:24 AM",
        "closes": "03-Oct-2026 02:00 PM",
    }
