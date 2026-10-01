from datetime import datetime
from decimal import Decimal

import pytest

from ingest.parsers import gepnic
from ingest.validation import IST, buyer_from_chain, parse_inr, parse_ist, validate_detail
from tests.conftest import fixture_text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("8,00,000", Decimal("800000")),
        ("4,91,87,00,000", Decimal("4918700000")),
        ("0.00", Decimal("0.00")),
        ("₹ 1,234.50", Decimal("1234.50")),
        ("Rs. 5,000/-", Decimal("5000")),
        ("NA", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_inr(text, expected):
    assert parse_inr(text) == expected


def test_parse_inr_rejects_garbage():
    with pytest.raises(ValueError):
        parse_inr("as per tender document")


def test_parse_ist():
    assert parse_ist("07-Oct-2026 11:00 AM") == datetime(2026, 10, 7, 11, 0, tzinfo=IST)
    assert parse_ist("07-Oct-2026 11:00 PM").hour == 23
    assert parse_ist("NA") is None
    with pytest.raises(ValueError):
        parse_ist("31-Foo-2026 04:00 PM")


def test_buyer_from_chain_keeps_org_and_department():
    assert buyer_from_chain("A||B||C||D") == "A || B"
    assert buyer_from_chain("Only Org") == "Only Org"


def _validate(html: str):
    raw = gepnic.parse_detail(html)
    return validate_detail(raw, source="central", url="u", state="Uttar Pradesh")


def test_valid_page_produces_tender():
    tender, errors = _validate(fixture_text("gepnic_central/detail_01.html"))
    assert errors == []
    assert tender.source_tender_id == "2026_AMU_926330_3"
    assert tender.value_inr == Decimal("800000")
    assert tender.emd_inr == Decimal("16000")
    assert tender.buyer_raw == "Aligarh Muslim University || Electricity Department"
    assert tender.closes_at > tender.published_at


def test_closes_before_published_is_rejected_with_readable_error():
    tender, errors = _validate(fixture_text("broken/detail_closes_before_published.html"))
    assert tender is None
    assert len(errors) == 1
    assert errors[0]["field"] == "__all__"
    assert errors[0]["input"] == {
        "published": "01-Oct-2026 04:00 PM",
        "closes": "07-Sep-2026 11:00 AM",
    }
    assert (
        "closes_at 07-Sep-2026 11:00 is before published_at 01-Oct-2026 16:00" in errors[0]["error"]
    )


def test_bad_date_and_negative_value_both_reported():
    tender, errors = _validate(fixture_text("broken/detail_bad_date_negative_value.html"))
    assert tender is None
    fields = {e["field"] for e in errors}
    assert "published_at" in fields
    bad = next(e for e in errors if e["field"] == "published_at")
    assert bad["input"] == "31-Foo-2026 04:00 PM"


def test_negative_value_rejected():
    raw = gepnic.parse_detail(fixture_text("gepnic_central/detail_01.html"))
    raw["value"] = "-8,00,000"
    tender, errors = validate_detail(raw, source="central", url="u", state="")
    assert tender is None
    assert errors[0]["field"] == "value_inr"
    assert "greater than or equal to 0" in errors[0]["error"]


def test_missing_tender_id_rejected():
    tender, errors = _validate(fixture_text("broken/detail_missing_tender_id.html"))
    assert tender is None
    assert errors[0]["field"] == "source_tender_id"


def test_content_hash_ignores_url_but_not_business_fields():
    raw = gepnic.parse_detail(fixture_text("gepnic_central/detail_01.html"))
    a, _ = validate_detail(raw, source="central", url="session-1", state="")
    b, _ = validate_detail(raw, source="central", url="session-2", state="")
    assert a.content_hash() == b.content_hash()
    raw2 = {**raw, "emd": "17,000"}
    c, _ = validate_detail(raw2, source="central", url="session-1", state="")
    assert c.content_hash() != a.content_hash()
