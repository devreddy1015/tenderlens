"""CSV export (feature `export`) and the public OCDS 1.1 release package."""

import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from tests.test_workspaces import client_for, make_org, make_tender, make_user
from workspaces import exports

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return make_user("owner@example.com")


def _csv(resp) -> list[dict]:
    text = b"".join(resp.streaming_content).decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.DictReader(io.StringIO(text[1:])))


# --- CSV ----------------------------------------------------------------------------------


def test_csv_export(owner):
    make_org(owner, plan="pro")
    a = make_tender(title="Road resurfacing at Bhilai", value_inr=Decimal("1234567.50"))
    make_tender(title="Supply of laptops", state="Delhi", sector="it")
    r = client_for(owner).get("/api/export/tenders.csv?state=Chhattisgarh")
    assert r.status_code == 200
    assert r["Content-Type"] == "text/csv; charset=utf-8"
    assert r["Content-Disposition"].startswith('attachment; filename="tenderlens-tenders-')
    assert r["X-Total-Count"] == "1" and r["X-Export-Truncated"] == "false"
    rows = _csv(r)
    assert len(rows) == 1
    row = rows[0]
    assert row["tender_id"] == a.source_tender_id and row["title"] == a.title
    assert row["value_inr"] == "1234567.50"
    assert row["source_portal"] == "Central Public Procurement Portal (GePNIC)"
    assert row["source_url"] == a.url
    assert row["tenderlens_url"] == f"http://localhost:8080/tenders/{a.pk}"


def test_csv_formula_injection(owner):
    make_org(owner, plan="pro")
    make_tender(title='=HYPERLINK("http://evil","click")', buyer_raw="+cmd|' /C calc'!A0")
    make_tender(title="@SUM(1+1)", buyer_raw="-2+3", location="\tTab")
    rows = _csv(client_for(owner).get("/api/export/tenders.csv"))
    cells = [v for row in rows for v in row.values()]
    assert not any(v.startswith(("=", "+", "-", "@", "\t")) for v in cells)
    titles = {row["title"] for row in rows}
    assert titles == {'\'=HYPERLINK("http://evil","click")', "'@SUM(1+1)"}


def test_safe_cell():
    assert exports.safe_cell("=1+1") == "'=1+1"
    assert exports.safe_cell("Road") == "Road"
    assert exports.safe_cell(None) == ""
    assert exports.safe_cell(Decimal("10.50")) == "10.50"


def test_csv_needs_export_feature(owner):
    make_org(owner, plan="free")
    r = client_for(owner).get("/api/export/tenders.csv")
    assert r.status_code == 402
    assert r.json()["code"] == "quota_exceeded" and r.json()["limit"] == "export"


def test_csv_login_required():
    assert APIClient().get("/api/export/tenders.csv").status_code == 403


def test_csv_row_cap(owner, monkeypatch):
    make_org(owner, plan="pro")
    for _ in range(3):
        make_tender()
    monkeypatch.setattr(exports, "MAX_CSV_ROWS", 2)
    r = client_for(owner).get("/api/export/tenders.csv")
    assert r["X-Total-Count"] == "3" and r["X-Export-Truncated"] == "true"
    assert len(_csv(r)) == 2


def test_csv_bad_filter(owner):
    make_org(owner, plan="pro")
    assert client_for(owner).get("/api/export/tenders.csv?min_value=abc").status_code == 400


def test_csv_via_api_key(owner):
    make_org(owner, plan="enterprise")
    c = client_for(owner)
    key = c.post("/api/workspace/api-keys", {"name": "x"}).json()["key"]
    make_tender()
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    r = api.get("/api/export/tenders.csv")
    assert r.status_code == 200 and len(_csv(r)) == 1


# --- OCDS ---------------------------------------------------------------------------------

RELEASE_REQUIRED = {"ocid", "id", "date", "tag", "initiationType"}
PACKAGE_REQUIRED = {"uri", "version", "publishedDate", "publisher", "releases"}


def test_ocds_release_package_shape(settings):
    settings.OCDS_PREFIX = "ocds-abc123"
    now = timezone.now()
    t = make_tender(
        value_inr=Decimal("2500000"),
        emd_inr=Decimal("50000"),
        tender_type="Open Tender",
        opens_at=now + timedelta(days=11),
        pincode="490001",
    )
    r = APIClient().get("/api/ocds/releases")
    assert r.status_code == 200
    pkg = r.json()
    assert set(pkg) >= PACKAGE_REQUIRED
    assert pkg["version"] == "1.1" and pkg["publisher"]["name"] == "TenderLens"
    assert "license" not in pkg  # the portals publish under no open licence
    assert r["X-Total-Count"] == "1" and "links" not in pkg
    (rel,) = pkg["releases"]
    assert set(rel) >= RELEASE_REQUIRED
    assert rel["ocid"] == f"ocds-abc123-central-{t.source_tender_id}"
    assert rel["id"].startswith(rel["ocid"] + "-")
    assert rel["tag"] == ["tender"] and rel["initiationType"] == "tender"
    party_ids = {p["id"] for p in rel["parties"]}
    assert rel["buyer"]["id"] in party_ids
    buyer = next(p for p in rel["parties"] if p["id"] == rel["buyer"]["id"])
    assert buyer["roles"] == ["buyer"] and buyer["name"] == "Public Works Department"
    assert buyer["address"] == {
        "region": "Chhattisgarh",
        "postalCode": "490001",
        "countryName": "India",
    }
    tender = rel["tender"]
    assert tender["id"] == t.source_tender_id and tender["title"] == t.title
    assert tender["status"] == "active"
    assert tender["value"] == {"amount": 2500000.0, "currency": "INR"}
    assert tender["tenderPeriod"]["endDate"] == t.closes_at.isoformat()
    assert tender["procurementMethodDetails"] == "Open Tender"
    assert tender["mainProcurementCategory"] == "works"
    # Documents only link to the source portal; nothing is republished.
    (doc,) = tender["documents"]
    assert doc["url"] == t.url and doc["documentType"] == "tenderNotice"


def test_ocds_pagination_and_filters():
    for _ in range(3):
        make_tender()
    make_tender(state="Delhi")
    c = APIClient()
    pkg = c.get("/api/ocds/releases?state=Chhattisgarh&page_size=2").json()
    assert len(pkg["releases"]) == 2 and "next" in pkg["links"] and "prev" not in pkg["links"]
    page2 = c.get(pkg["links"]["next"]).json()
    assert len(page2["releases"]) == 1 and "prev" in page2["links"]
    ocids = {r["ocid"] for r in pkg["releases"] + page2["releases"]}
    assert len(ocids) == 3
    assert c.get("/api/ocds/releases?page=0").status_code == 400


def test_ocds_awards_when_present():
    class FakeAward:
        pk = 7
        bidder_name = "Shree Constructions"
        bidder_key = "shree-constructions"
        amount_inr = Decimal("2300000")
        award_date = timezone.now().date()

    t = make_tender()
    rel = exports.release(t, [FakeAward()])
    assert rel["tag"] == ["tender", "award"]
    (award,) = rel["awards"]
    assert award["suppliers"] == [
        {"id": "supplier-shree-constructions", "name": "Shree Constructions"}
    ]
    assert award["value"] == {"amount": 2300000.0, "currency": "INR"}
    supplier = next(p for p in rel["parties"] if p["roles"] == ["supplier"])
    assert supplier["id"] == "supplier-shree-constructions"
