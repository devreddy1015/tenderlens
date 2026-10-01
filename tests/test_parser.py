import pytest

from ingest.parsers import gepnic
from tests.conftest import CENTRAL, fixture_text

DETAILS = sorted(CENTRAL.glob("detail_*.html"))


def test_org_index_lists_every_organisation_with_counts():
    orgs = gepnic.parse_org_index(fixture_text("gepnic_central/org_index.html"))
    assert len(orgs) == 252
    assert sum(o.tender_count for o in orgs) == 2549  # "Total" the portal showed that day
    amu = next(o for o in orgs if o.name == "Aligarh Muslim University")
    assert amu.tender_count == 7
    assert "FrontEndTendersByOrganisation" in amu.href and "sp=" in amu.href


def test_state_portal_index_uses_same_layout():
    orgs = gepnic.parse_org_index(fixture_text("gepnic_state/mp_org_index.html"))
    assert len(orgs) > 50
    assert all(o.href.startswith("/nicgep/app") for o in orgs)


def test_org_listing_rows():
    rows = gepnic.parse_org_listing(fixture_text("gepnic_central/org_list_amu.html"))
    assert len(rows) == 7
    first = rows[0]
    assert first.tender_id == "2026_AMU_926330_3"
    assert first.ref_no == "07/ED(SSS)/2026-27"
    assert first.published == "01-Oct-2026 04:00 PM"
    assert first.closes == "07-Oct-2026 11:00 AM"
    assert first.title.startswith("Providing Spare / Emergency Supply Cable")
    assert first.org_chain == "Aligarh Muslim University||Electricity Department||Member-In-Charge"
    assert "FrontEndViewTender" in first.href


def test_large_listing_has_no_pagination_and_unique_ids():
    rows = gepnic.parse_org_listing(fixture_text("gepnic_central/org_list_morth.html"))
    assert len(rows) == 269
    assert len({r.tender_id for r in rows}) == 269


def test_detail_fields():
    d = gepnic.parse_detail(fixture_text("gepnic_central/detail_01.html"))
    assert d["tender_id"] == "2026_AMU_926330_3"
    assert d["org_chain"] == "Aligarh Muslim University||Electricity Department||Member-In-Charge"
    assert d["value"] == "8,00,000"
    assert d["emd"] == "16,000"
    assert d["fee"] == "708"
    assert d["category"] == "Works"
    assert d["product_category"] == "Electrical Works"
    assert d["location"] == "JNMCH, AMU, Aligarh"
    assert d["pincode"] == "202002"
    assert d["published"] == "01-Oct-2026 04:00 PM"
    assert d["closes"] == "07-Oct-2026 11:00 AM"
    assert d["opens"] == "08-Oct-2026 11:00 AM"
    assert d["inviting_authority"] == "Assistant Electrical Engineer (SSS)"
    assert d["documents"] == "Tendernotice_1.pdf"


@pytest.mark.parametrize("path", DETAILS, ids=lambda p: p.name)
def test_every_saved_detail_page_has_required_fields(path):
    d = gepnic.parse_detail(path.read_text(encoding="utf-8"))
    for field in ("tender_id", "title", "org_chain", "published", "closes", "value", "emd"):
        assert d.get(field), f"{path.name} missing {field}"


def test_stale_session_is_detected_everywhere():
    stale = fixture_text("gepnic_central/stale_session.html")
    assert gepnic.is_stale_session(stale)
    for fn in (gepnic.parse_detail, gepnic.parse_org_listing, gepnic.parse_org_index):
        with pytest.raises(gepnic.StaleSession):
            fn(stale)


def test_non_detail_page_raises():
    with pytest.raises(gepnic.NotADetailPage):
        gepnic.parse_detail("<html><body><h1>Maintenance</h1></body></html>")
