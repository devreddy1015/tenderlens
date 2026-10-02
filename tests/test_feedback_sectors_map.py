import json
from pathlib import Path

import pytest
from django.core import mail
from rest_framework.test import APIClient

from feedback.models import Feedback
from ingest.loader import load_detail_page
from tenders.models import Tender
from tenders.pincode import ALL_STATES
from tenders.sectors import SECTOR_BY_SLUG, SECTORS, classify
from tests.conftest import CENTRAL

MAP = Path(__file__).parent.parent / "frontend" / "src" / "data" / "india-states.json"


# --- sectors --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,product_category,category,expected",
    [
        # Real titles from the 2 Oct 2026 crawl.
        (
            "Supply and Installation of Crash Rated Hydraulic Bollards at Nimmo Bazgo Power Station",
            "Miscellaneous Works",
            "Works",
            "security",
        ),
        (
            "SITC of IP-Based CCTV System complete with cameras",
            "Electrical Works",
            "Works",
            "security",
        ),
        (
            "Supply and installation of Hyper Converged Infrastructure (HCI) Solution for IIT Guwahati ERP",
            "Computer- S/W",
            "Goods",
            "it",
        ),
        (
            "Exclusive indoor advertisement rights on Dwarka Mor Metro Station section of DMRC Network",
            "Miscellaneous Works",
            "Works",
            "other",
        ),
        (
            "Short term maintenance of Raigarh-Sarangarh road section of NH-216",
            "Civil Works - Highways",
            "Works",
            "roads",
        ),
        (
            "Construction of Four Lane with paved shoulder of Bhagalpur Kharhara",
            "Civil Works",
            "Works",
            "roads",
        ),
        (
            "TENDER FOR SWEEPING AND MAINTAINING INCLUDING REMOVAL OF GARBAGES FOR THE AREAS OF ROADS, YARDS",
            "Civil Works",
            "Works",
            "facility",
        ),
        (
            "Supply of High Voltage Air Insulated Relays",
            "Miscellaneous Goods",
            "Goods",
            "electrical",
        ),
        (
            "Supply, Installation, Testing and Commissioning of MGPS System in 150 Bedded CCHB at AIIMS Bhopal",
            "Miscellaneous Works",
            "Works",
            "health",
        ),
        (
            "Development of solar power plant at Nasirabad Cantt",
            "Power/Energy Projects/Products",
            "Works",
            "electrical",
        ),
        (
            "Supply of Non-invasive Neonatal Ventilator device",
            "Equipments (Hospital / Lab)",
            "Goods",
            "health",
        ),
        (
            "Procurement of Pressure Plate through PAC",
            "Laboratory and scientific equipment",
            "Goods",
            "lab",
        ),
        ("Conservation of Waterbody", "Civil Works", "Works", "water"),
        ("Renovation of toilet in the chamber of GM", "Civil Works", "Works", "buildings"),
        ("Chartered Accountant Services", "Consultancy", "Services", "consultancy"),
        ("Hiring of vehicles for official use", "Hiring of Vehicles", "Services", "transport"),
        ("Outsourcing of housekeeping services", "Miscellaneous Services", "Services", "facility"),
        ("Supply of fresh vegetables", "Food Products", "Goods", "supplies"),
        ("Re Opening of Request for Empanelment", "Miscellaneous Services", "Services", "other"),
    ],
)
def test_classify(title, product_category, category, expected):
    assert classify(title, product_category, category) == expected


def test_every_sector_has_unique_slug():
    assert len({s.slug for s in SECTORS}) == len(SECTORS)


@pytest.mark.django_db
def test_loader_stores_sector(make_page):
    load_detail_page(make_page((CENTRAL / "detail_02.html").read_text(encoding="utf-8")))
    assert Tender.objects.get().sector == "roads"


# --- map ------------------------------------------------------------------------------


def test_map_regions_match_the_state_names_we_store():
    """Every region on the map can be coloured, and every state we store has a region."""
    names = {s["name"] for s in json.loads(MAP.read_text())["states"]}
    assert names == set(ALL_STATES)


def test_map_includes_ladakh_and_attribution():
    data = json.loads(MAP.read_text())
    assert "Ladakh" in {s["name"] for s in data["states"]}
    assert "DataMeet" in data["attribution"]


# --- API ------------------------------------------------------------------------------


@pytest.fixture
def loaded(make_page, db):
    for p in sorted(CENTRAL.glob("detail_*.html")):
        load_detail_page(make_page(p.read_text(encoding="utf-8")))


@pytest.fixture
def frozen(monkeypatch):
    from django.utils import timezone

    now = timezone.datetime(2026, 10, 2, 9, 0, tzinfo=timezone.get_current_timezone())
    monkeypatch.setattr("api.views.timezone.now", lambda: now)
    return now


@pytest.mark.django_db
def test_sectors_endpoint(loaded, frozen):
    rows = APIClient().get("/api/sectors").json()
    assert [r["slug"] for r in rows] == [s.slug for s in SECTORS]
    by = {r["slug"]: r for r in rows}
    assert (
        by["roads"]["open"] == Tender.objects.filter(sector="roads", closes_at__gte=frozen).count()
    )


@pytest.mark.django_db
def test_map_endpoint(loaded, frozen):
    rows = APIClient().get("/api/map").json()
    assert (
        sum(r["open"] for r in rows)
        == Tender.objects.filter(closes_at__gte=frozen).exclude(state="").count()
    )
    assert all(r["top_sector"] in SECTOR_BY_SLUG for r in rows)
    roads = APIClient().get("/api/map", {"sector": "roads"}).json()
    assert (
        sum(r["open"] for r in roads)
        == Tender.objects.filter(sector="roads", closes_at__gte=frozen).exclude(state="").count()
    )


@pytest.mark.django_db
def test_list_filters_by_sector_and_pin_and_sorts(loaded):
    c = APIClient()
    assert (
        c.get("/api/tenders", {"sector": "roads"}).json()["count"]
        == Tender.objects.filter(sector="roads").count()
    )
    assert (
        c.get("/api/tenders", {"pin": "110"}).json()["count"]
        == Tender.objects.filter(pincode__startswith="110").count()
    )
    values = [r["value_inr"] for r in c.get("/api/tenders", {"sort": "value"}).json()["results"]]
    nums = [float(v) for v in values if v is not None]
    assert nums == sorted(nums, reverse=True)
    newest = [
        r["published_at"] for r in c.get("/api/tenders", {"sort": "newest"}).json()["results"]
    ]
    assert newest == sorted(newest, reverse=True)
    assert "sector" in c.get("/api/tenders").json()["facets"]
    assert c.get("/api/tenders", {"pin": "abc"}).status_code == 400


@pytest.mark.django_db
def test_similar_tenders_postgres_fallback(loaded):
    t = Tender.objects.get(source_tender_id="2026_DDA_928692_1")
    rows = APIClient().get(f"/api/tenders/{t.pk}/similar").json()
    assert t.pk not in [r["id"] for r in rows]
    assert all(r["sector"] == t.sector for r in rows)


@pytest.mark.django_db
def test_site_config(settings):
    settings.GOOGLE_CLIENT_ID = "abc.apps.googleusercontent.com"
    body = APIClient().get("/api/config").json()
    assert body["google_client_id"] == "abc.apps.googleusercontent.com"
    assert body["dev_login"] is False
    assert {"key": "central", "name": "Central Public Procurement Portal (GePNIC)"} in body[
        "sources"
    ]


# --- feedback -------------------------------------------------------------------------


@pytest.mark.django_db
def test_feedback_saved_and_forwarded(settings):
    settings.FEEDBACK_NOTIFY_EMAIL = "owner@example.com"
    r = APIClient().post(
        "/api/feedback",
        {"kind": "bug", "message": "Map does not load on Safari", "email": "x@y.co", "page": "/"},
        format="json",
    )
    assert r.status_code == 201
    fb = Feedback.objects.get()
    assert (fb.kind, fb.email, fb.page) == ("bug", "x@y.co", "/")
    assert mail.outbox[0].to == ["owner@example.com"]
    assert "Safari" in mail.outbox[0].body


@pytest.mark.django_db
def test_feedback_validation_and_honeypot():
    c = APIClient()
    assert (
        c.post("/api/feedback", {"kind": "bug", "message": "hi"}, format="json").status_code == 400
    )
    assert (
        c.post(
            "/api/feedback", {"kind": "nonsense", "message": "hello there"}, format="json"
        ).status_code
        == 400
    )
    bot = c.post(
        "/api/feedback",
        {"kind": "idea", "message": "buy cheap pills", "website": "spam.example"},
        format="json",
    )
    assert bot.status_code == 201
    assert Feedback.objects.count() == 0  # silently dropped


@pytest.mark.django_db
def test_private_waitlist_needs_email():
    c = APIClient()
    assert c.post("/api/feedback", {"kind": "private_waitlist"}, format="json").status_code == 400
    assert (
        c.post(
            "/api/feedback", {"kind": "private_waitlist", "email": "me@x.co"}, format="json"
        ).status_code
        == 201
    )


@pytest.mark.django_db
def test_facets_are_disjunctive_in_postgres(loaded):
    """Picking a sector must not hide the other sectors' counts."""
    body = APIClient().get("/api/tenders", {"sector": "roads"}).json()
    sectors = {b["key"]: b["count"] for b in body["facets"]["sector"]}
    assert len(sectors) > 1
    assert sectors["roads"] == body["count"] == Tender.objects.filter(sector="roads").count()
    # Other facets *do* respect the sector filter.
    states = {b["key"]: b["count"] for b in body["facets"]["state"]}
    assert sum(states.values()) == Tender.objects.filter(sector="roads").exclude(state="").count()
