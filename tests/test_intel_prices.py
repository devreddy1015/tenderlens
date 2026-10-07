import io
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from intel import prices
from intel.models import PriceIndex

pytestmark = pytest.mark.django_db


def _wdi(indicator: str, rows: list[tuple[str, int, float | None]]) -> list:
    return [
        {"page": 1, "pages": 1, "per_page": 20000, "total": len(rows)},
        [
            {
                "indicator": {"id": indicator},
                "country": {"id": c, "value": c},
                "countryiso3code": "",
                "date": str(y),
                "value": v,
            }
            for c, y, v in rows
        ],
    ]


@respx.mock
def test_refresh_stores_cpi_and_fx_and_skips_nulls():
    respx.get(url__regex=r".*/indicator/FP\.CPI\.TOTL.*").mock(
        return_value=httpx.Response(
            200,
            json=_wdi("FP.CPI.TOTL", [("IN", 2020, 180.0), ("IN", 2021, None), ("US", 2020, 118)]),
        )
    )
    respx.get(url__regex=r".*/indicator/PA\.NUS\.FCRF.*").mock(
        return_value=httpx.Response(200, json=_wdi("PA.NUS.FCRF", [("IN", 2020, 74.1)]))
    )
    assert prices.refresh(["in"]) == 3
    assert PriceIndex.objects.get(series="cpi", country="IN", year=2020).value == 180.0
    assert not PriceIndex.objects.filter(year=2021).exists()
    # Idempotent: a second run updates, never duplicates.
    prices.refresh(["IN"])
    assert PriceIndex.objects.count() == 3


@respx.mock
def test_refresh_rejects_an_error_payload():
    respx.get(url__regex=r".*").mock(
        return_value=httpx.Response(200, json=[{"message": [{"id": "120", "value": "bad"}]}])
    )
    with pytest.raises(ValueError):
        prices.refresh(["XX"])


def _index(series, country, values: dict[int, float]):
    for year, value in values.items():
        PriceIndex.objects.create(series=series, country=country, year=year, value=value)


def test_deflator_inflates_inr_and_converts_foreign_currency():
    _index("cpi", "IN", {2000: 50.0, 2024: 200.0})
    _index("fx_per_usd", "IN", {2000: 45.0, 2024: 83.0})
    _index("fx_per_usd", "UA", {2000: 5.0})
    d = prices.Deflator.load(target_year=2024)
    assert d.to_inr_real(100, "INR", "IN", 2000) == Decimal("400.00")
    # USD at the 2000 rupee rate, then India's CPI.
    assert d.to_inr_real(1, "USD", "IN", 2000) == Decimal("180.00")
    # Local currency -> USD at that year's rate -> INR -> inflate.
    assert d.to_inr_real(10, "UAH", "UA", 2000) == Decimal("360.00")


def test_deflator_extrapolates_missing_recent_years_and_refuses_unknowns():
    _index("cpi", "IN", {2021: 100.0, 2022: 110.0, 2023: 121.0, 2024: 133.1})
    d = prices.Deflator.load(target_year=2026)
    # 10% a year carried forward two years.
    assert d.inflation_factor(2024) == pytest.approx(1.21)
    assert d.to_inr_real(100, "EUR", "FR", 2024) is None  # no FR exchange rate stored
    assert d.to_inr_real(None, "INR", "IN", 2024) is None
    assert d.to_inr_real(5, "INR", "IN", None) is None


def test_deflator_converts_euros_at_the_euro_area_rate():
    # TED publishes Polish contracts in euros; Poland's own WDI rate is zloty per dollar.
    _index("cpi", "IN", {2022: 100.0})
    _index("fx_per_usd", "IN", {2022: 80.0})
    _index("fx_per_usd", "XC", {2022: 0.8})
    _index("fx_per_usd", "PL", {2022: 4.0})
    d = prices.Deflator.load(target_year=2022)
    assert d.to_inr_real(100, "EUR", "PL", 2022) == Decimal("10000.00")
    assert d.to_inr_real(100, "PLN", "PL", 2022) == Decimal("2000.00")


def test_rate_countries_adds_currency_areas():
    assert prices.rate_countries(["pl", "PE", ""], ["EUR", "PEN", None]) == ["PE", "PL", "XC"]


def _award(i: int, **kw):
    from intel.models import HistoricalAward

    base = dict(
        source="test",
        source_id=f"A{i}",
        country="PE",
        currency="PEN",
        estimated_value=Decimal("400"),
        award_value=Decimal("300"),
        year=2024,
    )
    return HistoricalAward.objects.create(**{**base, **kw})


def test_reprice_fills_rows_imported_before_their_rates():
    from intel.models import HistoricalAward

    _index("cpi", "IN", {2024: 100.0})
    _index("fx_per_usd", "IN", {2024: 80.0})
    rows = [_award(i) for i in range(3)] + [_award(9, currency="INR", country="IN")]
    assert all(r.award_inr_real is None for r in rows)  # created before PE rates existed

    _index("fx_per_usd", "PE", {2024: 4.0})
    d = prices.Deflator.load(target_year=2024)
    assert prices.reprice(batch=2, deflator=d) == 4  # pages of 2: every row visited
    a = HistoricalAward.objects.get(source_id="A1")
    assert (a.estimated_inr_real, a.award_inr_real) == (Decimal("8000.00"), Decimal("6000.00"))
    assert HistoricalAward.objects.get(source_id="A9").award_inr_real == Decimal("300.00")
    # Nothing changed since: nothing written.
    assert prices.reprice(deflator=d) == 0

    # A queryset limits the work; rows whose rate disappears go back to unknown.
    PriceIndex.objects.filter(country="PE").delete()
    d = prices.Deflator.load(target_year=2024)
    assert prices.reprice(HistoricalAward.objects.filter(source_id="A0"), deflator=d) == 1
    assert HistoricalAward.objects.get(source_id="A0").award_inr_real is None
    assert HistoricalAward.objects.get(source_id="A1").award_inr_real == Decimal("6000.00")


@respx.mock
def test_intel_prices_command_refreshes_every_rate_needed_then_reprices():
    from django.core.management import call_command

    from intel.models import HistoricalAward

    year = date.today().year
    cpi = respx.get(url__regex=r".*/indicator/FP\.CPI\.TOTL.*").mock(
        return_value=httpx.Response(200, json=_wdi("FP.CPI.TOTL", [("IN", year, 100.0)]))
    )
    fx = respx.get(url__regex=r".*/indicator/PA\.NUS\.FCRF.*").mock(
        return_value=httpx.Response(
            200,
            json=_wdi("PA.NUS.FCRF", [("IN", year, 80.0), ("XC", year, 0.8), ("PE", year, 4.0)]),
        )
    )
    _award(1, year=year)
    _award(2, country="PL", currency="EUR", year=year)
    call_command("intel_prices", "--reprice", stdout=io.StringIO())
    # Countries in the data, the euro area for EUR rows, and always India and the US.
    assert "/country/IN;PE;PL;US;XC/" in str(fx.calls.last.request.url)
    assert cpi.called
    assert HistoricalAward.objects.get(source_id="A1").award_inr_real == Decimal("6000.00")
    assert HistoricalAward.objects.get(source_id="A2").award_inr_real == Decimal("30000.00")
