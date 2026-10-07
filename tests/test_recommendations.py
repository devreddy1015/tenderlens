"""GET /api/recommendations: open tenders matching the company profile."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from tests.test_workspaces import client_for, make_org, make_tender, make_user
from workspaces.models import BidTrack

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return make_user("owner@example.com")


@pytest.fixture
def org(owner):
    return make_org(
        owner,
        states=["Chhattisgarh"],
        sectors=["roads"],
        annual_turnover_inr=Decimal("10000000"),  # 1 crore -> up to 3 crore
    )


def test_profile_incomplete(owner):
    make_org(owner)
    make_tender()
    body = client_for(owner).get("/api/recommendations").json()
    assert body["profile_incomplete"] is True and body["results"] == [] and body["count"] == 0


def test_matches_profile_with_reasons(owner, org):
    now = timezone.now()
    fits = make_tender(value_inr=Decimal("25000000"), published_at=now - timedelta(days=1))
    no_value = make_tender(value_inr=None, published_at=now - timedelta(days=3))
    make_tender(value_inr=Decimal("40000000"))  # above 3x turnover
    make_tender(state="Odisha")
    make_tender(sector="water")
    make_tender(closes_at=now - timedelta(hours=1))  # closed
    tracked = make_tender()
    BidTrack.objects.create(organization=org, tender=tracked)

    r = client_for(owner).get("/api/recommendations")
    assert r.status_code == 200
    body = r.json()
    assert body["profile_incomplete"] is False
    ids = [t["id"] for t in body["results"]]
    assert ids == [fits.pk, no_value.pk]  # newest first
    assert body["count"] == 2
    first = body["results"][0]
    assert first["reasons"] == [
        "Sector: Roads & Bridges",
        "State: Chhattisgarh",
        "Within your turnover limit",
    ]
    assert body["results"][1]["reasons"] == ["Sector: Roads & Bridges", "State: Chhattisgarh"]
    assert {"title", "closes_at", "value_inr", "buyer"} <= set(first)


def test_states_only_profile_any_sector(owner):
    make_org(owner, states=["Odisha"])
    a = make_tender(state="Odisha", sector="water", value_inr=Decimal("10" * 7))
    make_tender(state="Kerala")
    body = client_for(owner).get("/api/recommendations").json()
    assert [t["id"] for t in body["results"]] == [a.pk]
    assert body["results"][0]["reasons"] == ["State: Odisha"]  # no turnover set


def test_pagination_and_filters(owner, org):
    for _ in range(3):
        make_tender()
    c = client_for(owner)
    body = c.get("/api/recommendations?page_size=2").json()
    assert body["count"] == 3 and len(body["results"]) == 2 and body["next"]
    assert len(c.get("/api/recommendations?page_size=2&page=2").json()["results"]) == 1
    assert c.get("/api/recommendations?page_size=500").status_code == 400
    special = make_tender(title="Bituminous overlay of NH-30")
    body = c.get("/api/recommendations?q=bituminous").json()
    assert [t["id"] for t in body["results"]] == [special.pk]


def test_login_required():
    from rest_framework.test import APIClient

    assert APIClient().get("/api/recommendations").status_code == 403
