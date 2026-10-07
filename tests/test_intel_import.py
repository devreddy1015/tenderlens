from datetime import date
from decimal import Decimal

import pytest

from intel.models import DatasetImport, HistoricalAward, PriceIndex
from intel.sources import REGISTRY
from intel.sources.base import (
    AwardRow,
    Source,
    cpv_sector,
    parse_amount,
    register,
    run_import,
    upsert,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def prices():
    for year, value in {2010: 100.0, 2020: 150.0, 2026: 200.0}.items():
        PriceIndex.objects.create(series="cpi", country="IN", year=year, value=value)
        PriceIndex.objects.create(series="fx_per_usd", country="IN", year=year, value=50.0)


def _row(i: int = 1, **kw) -> AwardRow:
    base = dict(
        source_id=f"T{i}",
        title="Construction of CC road and drain in ward 4",
        buyer="Executive Engineer, PWD Division Raipur",
        state="Chhattisgarh",
        category="works",
        estimated_value=Decimal("1000000"),
        award_value=Decimal("900000"),
        bids=[900000, 950000, 0, 1010000],
        winner="M/s Sharma Constructions",
        award_date=date(2020, 5, 1),
    )
    return AwardRow(**{**base, **kw})


@pytest.mark.parametrize(
    "text,expected",
    [
        ("₹ 4,91,87,000.00", Decimal("49187000.00")),
        ("1,874,075", Decimal("1874075")),
        ("12.5 Cr", Decimal("125000000.0")),
        ("3 lakhs", Decimal("300000")),
        ("NA", None),
        ("0.00", None),
        (None, None),
        (2500, Decimal("2500")),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_parse_amount_unit_for_bare_numbers():
    assert parse_amount("30.0", unit="lakh") == Decimal("3000000.0")


@pytest.mark.parametrize(
    "cpv,sector",
    [
        ("45233140-2", "roads"),
        ("45210000", "buildings"),
        ("45232150", "water"),
        ("72000000", "it"),
        ("79710000", "security"),
        ("33100000", "health"),
        ("39130000", "supplies"),
        ("", ""),
    ],
)
def test_cpv_sector(cpv, sector):
    assert cpv_sector(cpv) == sector


def test_upsert_derives_columns_and_is_idempotent(prices):
    stats = upsert([_row()], "test")
    assert stats == {"seen": 1, "inserted": 1, "updated": 0, "skipped": 0, "ratios": 1}
    a = HistoricalAward.objects.get(source="test", source_id="T1")
    assert a.ratio == pytest.approx(0.9)
    assert a.year == 2020 and a.sector == "roads" and a.country == "IN"
    assert a.bids == [900000.0, 950000.0, 1010000.0] and a.num_bidders == 3  # 0 dropped
    assert a.winner_key == "m s sharma constructions"
    assert a.buyer_key == "executive engineer public works department division raipur"
    # 2020 -> 2026 rupees: CPI 150 -> 200.
    assert a.award_inr_real == Decimal("1200000.00")

    stats = upsert([_row(award_value=Decimal("800000"))], "test")
    assert stats["inserted"] == 0 and stats["updated"] == 1
    assert HistoricalAward.objects.get(source_id="T1").ratio == pytest.approx(0.8)
    assert HistoricalAward.objects.count() == 1


def test_upsert_rejects_implausible_ratios_and_empty_rows(prices):
    stats = upsert(
        [
            _row(1, award_value=Decimal("100")),  # ratio 0.0001: a unit error
            _row(2, estimated_value=None, award_value=None),  # nothing to learn
            _row(3, source_id=""),
            _row(4, estimated_value=None),  # award only: kept, no ratio
        ],
        "test",
    )
    assert stats["skipped"] == 2 and stats["inserted"] == 2 and stats["ratios"] == 0
    assert HistoricalAward.objects.get(source_id="T1").ratio is None
    assert HistoricalAward.objects.get(source_id="T4").award_value == Decimal("900000")


def test_upsert_keeps_foreign_titles_unclassified_unless_adapter_sets_sector(prices):
    upsert(
        [
            _row(1, country="PE", currency="PEN", title="Construcción de carretera"),
            _row(2, country="PE", currency="PEN", title="Construcción", sector="roads"),
        ],
        "test",
    )
    assert HistoricalAward.objects.get(source_id="T1").sector == ""
    assert HistoricalAward.objects.get(source_id="T2").sector == "roads"
    # No PEN exchange rate stored: real rupees stay unknown rather than guessed.
    assert HistoricalAward.objects.get(source_id="T2").award_inr_real is None


@pytest.fixture
def fake_source():
    @register
    class Fake(Source):
        key = "fake-test"
        name = "Fake"
        url = "https://example.org"
        license = "CC0"

        def rows(self, ctx):
            yield from (_row(i) for i in range(1, 6))

    yield Fake
    REGISTRY.pop("fake-test")


def test_run_import_records_the_run(prices, fake_source):
    run = run_import("fake-test", limit=3, min_interval=0)
    assert run.status == DatasetImport.Status.SUCCEEDED
    assert (run.rows_seen, run.rows_inserted, run.params["ratios"]) == (3, 3, 3)
    assert run.license == "CC0" and run.finished_at
    assert HistoricalAward.objects.filter(imported=run).count() == 3


def test_run_import_records_failures(prices, fake_source, monkeypatch):
    def boom(self, ctx):
        raise ValueError("bad file")
        yield

    monkeypatch.setattr(fake_source, "rows", boom)
    with pytest.raises(ValueError):
        run_import("fake-test", min_interval=0)
    run = DatasetImport.objects.get(source="fake-test")
    assert run.status == DatasetImport.Status.FAILED and "bad file" in run.error


def test_register_refuses_duplicate_keys(fake_source):
    with pytest.raises(ValueError):

        @register
        class Other(Source):
            key = "fake-test"
