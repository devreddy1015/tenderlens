"""Putting amounts from 2000 and from other currencies into today's rupees.

Series come from the World Bank's World Development Indicators API (free, no key, one
call per indicator): FP.CPI.TOTL (consumer prices, 2010 = 100) and PA.NUS.FCRF (official
exchange rate, local currency per US dollar, period average).

The conversion is deliberately simple: convert to US dollars at that year's rate, to
rupees at that year's rupee rate, then inflate with India's CPI to the current year. The
price model works in award / estimate ratios, which need none of this; real rupees only
feed the size feature (log estimate) and what the UI shows, so a simple, documented rule
beats a clever one.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import httpx

from intel.models import PriceIndex

log = logging.getLogger(__name__)

WDI_URL = "https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"
INDICATORS = {PriceIndex.Series.CPI: "FP.CPI.TOTL", PriceIndex.Series.FX_PER_USD: "PA.NUS.FCRF"}
FIRST_YEAR = 1995
# Years missing at the end of a series (WDI lags a year or two) are extrapolated with the
# average growth of this many preceding years.
EXTRAPOLATE_FROM_YEARS = 3
# Currencies shared by several countries: their rate comes from the currency area's WDI
# aggregate, not from the buyer's country. TED publishes every country's amounts in EUR,
# and Poland's PA.NUS.FCRF is zloty per dollar, so EUR / PL's rate would be off ~4x.
# (WDI "XC" = Euro area: euro per US dollar, the same value WDI gives each member.)
CURRENCY_AREAS = {"EUR": "XC"}


def fetch_wdi(indicator: str, countries: list[str], *, client: httpx.Client | None = None):
    """[(country ISO-2, year, value)] for every non-null observation since FIRST_YEAR."""
    url = WDI_URL.format(countries=";".join(sorted(countries)), indicator=indicator)
    params = {"format": "json", "per_page": 20000, "date": f"{FIRST_YEAR}:{date.today().year}"}
    own = client is None
    client = client or httpx.Client(timeout=60, headers={"User-Agent": "TenderLens/1.0"})
    try:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    finally:
        if own:
            client.close()
    # [meta, rows]; an unknown country code returns [{"message": [...]}] instead.
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        raise ValueError(f"unexpected WDI response for {indicator}: {str(payload)[:200]}")
    out = []
    for row in payload[1]:
        if row.get("value") is None:
            continue
        code = (row.get("country") or {}).get("id", "")
        if len(code) == 2 and str(row.get("date", "")).isdigit():
            out.append((code.upper(), int(row["date"]), float(row["value"])))
    return out


def refresh(countries: list[str] | None = None, *, client: httpx.Client | None = None) -> int:
    """Upserts CPI and exchange rates for the given countries (default: India and the US).
    Returns the number of observations stored."""
    countries = sorted({c.upper() for c in (countries or [])} | {"IN", "US"})
    stored = 0
    for series, indicator in INDICATORS.items():
        # The API accepts ~60 codes per call comfortably; chunk to stay well inside it.
        for i in range(0, len(countries), 50):
            for country, year, value in fetch_wdi(indicator, countries[i : i + 50], client=client):
                PriceIndex.objects.update_or_create(
                    series=series,
                    country=country,
                    year=year,
                    defaults={"value": value, "source": "worldbank-wdi"},
                )
                stored += 1
    log.info("price index refreshed: %s observations for %s countries", stored, len(countries))
    return stored


def _extend(values: dict[int, float], until: int) -> dict[int, float]:
    """Fills years after the last observation by compounding the recent average growth."""
    if not values:
        return values
    out = dict(values)
    last = max(out)
    prior = [y for y in range(last - EXTRAPOLATE_FROM_YEARS, last) if y in out and out[y] > 0]
    growth = (out[last] / out[prior[0]]) ** (1 / (last - prior[0])) if prior else 1.0
    for year in range(last + 1, until + 1):
        out[year] = out[year - 1] * growth
    return out


@dataclass
class Deflator:
    """In-memory view of PriceIndex. `to_inr_real` answers None when a needed series is
    missing rather than guessing."""

    target_year: int = field(default_factory=lambda: date.today().year)
    cpi: dict[str, dict[int, float]] = field(default_factory=dict)
    fx: dict[str, dict[int, float]] = field(default_factory=dict)

    @classmethod
    def load(cls, target_year: int | None = None) -> "Deflator":
        d = cls(target_year=target_year or date.today().year)
        for row in PriceIndex.objects.all().values_list("series", "country", "year", "value"):
            series, country, year, value = row
            book = d.cpi if series == PriceIndex.Series.CPI else d.fx
            book.setdefault(country, {})[year] = value
        d.cpi = {c: _extend(v, d.target_year) for c, v in d.cpi.items()}
        d.fx = {c: _extend(v, d.target_year) for c, v in d.fx.items()}
        return d

    def _rate(self, country: str, year: int) -> float | None:
        series = self.fx.get(country) or {}
        if year in series:
            return series[year]
        # Before the first observation, the earliest one is the best available guess.
        return series[min(series)] if series and year < min(series) else None

    def inflation_factor(self, year: int) -> float | None:
        """India's CPI(target year) / CPI(year)."""
        cpi = self.cpi.get("IN") or {}
        year = max(year, min(cpi)) if cpi else year
        if year not in cpi or self.target_year not in cpi:
            return None
        return cpi[self.target_year] / cpi[year]

    def to_inr_real(
        self, amount: Decimal | float | None, currency: str, country: str, year: int | None
    ) -> Decimal | None:
        if amount is None or year is None:
            return None
        amount = float(amount)
        currency = (currency or "").upper()
        if currency == "INR":
            inr = amount
        else:
            if currency == "USD":
                usd = amount
            else:
                # The country's own currency, or a shared one (EUR) at the area's rate.
                local_per_usd = self._rate(CURRENCY_AREAS.get(currency, country.upper()), year)
                if not local_per_usd:
                    return None
                usd = amount / local_per_usd
            inr_per_usd = self._rate("IN", year)
            if not inr_per_usd:
                return None
            inr = usd * inr_per_usd
        factor = self.inflation_factor(year)
        if factor is None:
            return None
        return Decimal(str(round(inr * factor, 2)))


def rate_countries(countries, currencies) -> list[str]:
    """The WDI codes whose series convert these rows: their countries plus the currency
    areas of shared currencies (EUR -> XC)."""
    codes = {c.upper() for c in countries if c}
    codes |= {CURRENCY_AREAS[c.upper()] for c in currencies if c and c.upper() in CURRENCY_AREAS}
    return sorted(codes)


def reprice(queryset=None, *, batch: int = 5000, deflator: Deflator | None = None) -> int:
    """Recomputes estimated_inr_real / award_inr_real from the stored amounts. Real rupees
    are fixed at upsert time, so rows imported before their country's exchange rate (or a
    newer CPI year) was stored keep None or stale values until this runs. Walks the rows in
    primary-key order (keyset pages, no long-lived cursor) and writes only rows that
    changed. Returns how many changed."""
    from intel.models import HistoricalAward

    deflator = deflator or Deflator.load()
    qs = queryset if queryset is not None else HistoricalAward.objects.all()
    qs = qs.order_by("pk").only(
        "pk",
        "currency",
        "country",
        "year",
        "estimated_value",
        "award_value",
        "estimated_inr_real",
        "award_inr_real",
    )
    changed, last = 0, 0
    while True:
        page = list(qs.filter(pk__gt=last)[:batch])
        if not page:
            break
        last = page[-1].pk
        dirty = []
        for row in page:
            est = deflator.to_inr_real(row.estimated_value, row.currency, row.country, row.year)
            award = deflator.to_inr_real(row.award_value, row.currency, row.country, row.year)
            if est != row.estimated_inr_real or award != row.award_inr_real:
                row.estimated_inr_real, row.award_inr_real = est, award
                dirty.append(row)
        if dirty:
            HistoricalAward.objects.bulk_update(dirty, ["estimated_inr_real", "award_inr_real"])
            changed += len(dirty)
    log.info("repriced %s rows", changed)
    return changed
