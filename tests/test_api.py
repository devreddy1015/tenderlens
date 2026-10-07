from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from ingest.loader import load_detail_page
from ingest.models import CrawlRun
from tenders.models import BuyerAlias, Tender
from tests.conftest import CENTRAL

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def loaded(make_page):
    for p in sorted(CENTRAL.glob("detail_*.html")):
        load_detail_page(make_page(p.read_text(encoding="utf-8")))
    return Tender.objects.count()


def test_list_paginated(api, loaded):
    r = api.get("/api/tenders", {"page_size": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == loaded == 18
    assert len(body["results"]) == 5
    assert body["next"] and body["previous"] is None
    assert body["search_backend"] == "postgres"
    closes = [t["closes_at"] for t in body["results"]]
    assert closes == sorted(closes)
    r2 = api.get(body["next"])
    assert r2.json()["previous"]


def test_filters(api, loaded):
    def count(**params):
        return api.get("/api/tenders", params).json()["count"]

    assert count(state="Delhi") == Tender.objects.filter(state="Delhi").count() > 0
    assert count(category="Works") == Tender.objects.filter(category="Works").count()
    assert count(min_value=10_000_000) == Tender.objects.filter(value_inr__gte=10_000_000).count()
    cutoff = "2026-10-08T00:00:00+05:30"
    assert count(closes_before=cutoff) == Tender.objects.filter(closes_at__lte=cutoff).count()
    assert count(q="toilet") == 1
    assert count(q="2026_DDA_928692_1") == 1


def test_buyer_filter_returns_every_spelling_variant(api, loaded):
    t = Tender.objects.filter(source_tender_id="2026_AMU_926330_3").get()
    entity = t.buyer_entity
    # A second spelling of the same department, as another portal might write it.
    variant = Tender.objects.get(source_tender_id="2026_AMU_928368_1")
    BuyerAlias.objects.create(
        alias="AMU || Electricity Deptt.", entity=entity, score=95, method="fuzzy"
    )
    Tender.objects.filter(pk=variant.pk).update(
        buyer_raw="AMU || Electricity Deptt.", buyer_entity=entity
    )
    r = api.get("/api/tenders", {"buyer": entity.id}).json()
    raws = {row["buyer_raw"] for row in r["results"]}
    assert raws == {t.buyer_raw, "AMU || Electricity Deptt."}


def test_invalid_params_are_400(api):
    assert api.get("/api/tenders", {"min_value": -5}).status_code == 400
    assert api.get("/api/tenders", {"closes_before": "tomorrow"}).status_code == 400
    assert api.get("/api/tenders", {"page_size": 1000}).status_code == 400


def test_facets_from_postgres(api, loaded):
    facets = api.get("/api/tenders").json()["facets"]
    assert sum(b["count"] for b in facets["category"]) == loaded
    assert {b["key"] for b in facets["value_range"]} == {
        "under_10_lakh",
        "10_lakh_to_1_crore",
        "1_to_10_crore",
        "over_10_crore",
    }


def test_detail(api, loaded):
    t = Tender.objects.get(source_tender_id="2026_AMU_926330_3")
    r = api.get(f"/api/tenders/{t.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["value_inr"] == "800000.00"
    assert body["buyer"]["canonical_name"] == "Aligarh Muslim University || Electricity Department"
    assert body["org_chain"].endswith("Member-In-Charge")
    assert api.get("/api/tenders/999999").status_code == 404


def test_buyer(api, loaded):
    t = Tender.objects.get(source_tender_id="2026_AMU_926330_3")
    r = api.get(f"/api/buyers/{t.buyer_entity_id}")
    assert r.status_code == 200
    body = r.json()
    same = Tender.objects.filter(buyer_entity_id=t.buyer_entity_id)
    assert body["tender_count"] == same.count()
    assert float(body["total_value_inr"]) == float(sum(x.value_inr or 0 for x in same))
    assert body["aliases"][0]["alias"] == t.buyer_raw
    assert api.get("/api/buyers/999999").status_code == 404


def test_stats(api, loaded, monkeypatch):
    fake_now = timezone.datetime(2026, 10, 2, 9, 0, tzinfo=timezone.get_current_timezone())
    monkeypatch.setattr("api.views.timezone.now", lambda: fake_now)
    CrawlRun.objects.create(source="central", status="succeeded", new=18, finished=fake_now)
    body = api.get("/api/stats").json()
    assert body["total_tenders"] == 18
    week = Tender.objects.filter(
        closes_at__gte=fake_now, closes_at__lt=fake_now + timedelta(days=7)
    )
    assert body["closing_this_week"] == week.count() > 0
    assert sum(r["count"] for r in body["by_state"]) == body["open_tenders"]
    assert body["last_crawl"]["new"] == 18


def test_health(api, db):
    r = api.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"
    assert "elasticsearch" not in body["checks"]  # Postgres is the search engine
    assert body["status"] == "ok"
    assert "runs_24h" in body["crawl"] and "open_dead_letters" in body["crawl"]


def test_openapi_schema_documents_every_endpoint(api):
    r = api.get("/api/schema/", HTTP_ACCEPT="application/json")
    assert r.status_code == 200
    import json

    paths = json.loads(r.content)["paths"].keys()
    for p in ("/api/tenders", "/api/tenders/{id}", "/api/buyers/{id}", "/api/stats", "/health"):
        assert p in paths, p


def test_openapi_schema_has_no_warnings():
    """`check --deploy` (the production migrate gate) fails on drf-spectacular warnings, so
    enum-name and operationId collisions must stay resolved."""
    from drf_spectacular.drainage import GENERATOR_STATS
    from drf_spectacular.generators import SchemaGenerator

    GENERATOR_STATS.reset()
    schema = SchemaGenerator().get_schema(request=None, public=True)
    assert not GENERATOR_STATS._warn_cache, list(GENERATOR_STATS._warn_cache)
    enums = schema["components"]["schemas"]
    assert "MembershipRoleEnum" in enums and "BidTrackStatusEnum" in enums
    ops = [op["operationId"] for item in schema["paths"].values() for op in item.values()]
    assert len(ops) == len(set(ops))
