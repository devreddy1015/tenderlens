from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from intel.models import DatasetImport, HistoricalAward, PriceIndex
from intel.sources import base
from intel.sources.base import run_import
from intel.sources.ted import DATASET_API, TED, parse_date

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures" / "intel" / "ted"
ZIP_2022 = FIXTURES / "ted-contract-award-notices-2022.zip"
ZIP_2008 = FIXTURES / "ted-contract-award-notices-2008.zip"
STORE = "https://data.europa.eu/api/hub/store/data/ted-contract-award-notices-{}.zip"


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    # Never read or write the real download cache (it holds the full yearly files).
    monkeypatch.setattr(base, "RAW_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def prices():
    for year in (2007, 2021, 2022, 2026):
        PriceIndex.objects.create(series="cpi", country="IN", year=year, value=100.0)
        PriceIndex.objects.create(series="fx_per_usd", country="IN", year=year, value=80.0)
        PriceIndex.objects.create(series="fx_per_usd", country="XC", year=year, value=0.8)
        # Poland's own rate is zloty per dollar; TED's euros must not use it.
        PriceIndex.objects.create(series="fx_per_usd", country="PL", year=year, value=4.0)


def _csv_row(**kw) -> dict[str, str]:
    row = {
        "ID_NOTICE_CAN": "202243",
        "TED_NOTICE_URL": "ted.europa.eu/udl?uri=TED:NOTICE:43-2022:TEXT:EN:HTML",
        "YEAR": "2022",
        "DT_DISPATCH": "29/12/21",
        "CANCELLED": "0",
        "CAE_NAME": "Gmina Wrocław",
        "ISO_COUNTRY_CODE": "PL",
        "TYPE_OF_CONTRACT": "W",
        "B_FRA_AGREEMENT": "N",
        "FRA_ESTIMATED": "",
        "B_FRA_CONTRACT": "N",
        "B_DYN_PURCH_SYST": "N",
        "CPV": "45233140",
        "ID_LOT": "1",
        "TOP_TYPE": "OPE",
        "ID_AWARD": "13843104",
        "INFO_ON_NON_AWARD": "",
        "WIN_NAME": "ALBA sp. z o.o.---Budimex S.A.",
        "TITLE": "Remont drogi",
        "NUMBER_OFFERS": "4",
        "AWARD_EST_VALUE_EURO": "200000",
        "AWARD_VALUE_EURO": "150000.50",
        "DT_AWARD": "28/12/21",
    }
    return {**row, **kw}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("28/12/21", date(2021, 12, 28)),
        ("15-DEC-06", date(2006, 12, 15)),
        ("03/02/2015", date(2015, 2, 3)),
        ("2019-07-01", date(2019, 7, 1)),
        ("", None),
        ("31/02/21", None),
    ],
)
def test_parse_date_handles_every_vintage(text, expected):
    assert parse_date(text) == expected


def test_to_row_maps_the_codebook_columns():
    row = TED().to_row(_csv_row(), line=2)
    assert row.source_id == "202243:13843104"
    assert (row.country, row.currency, row.category, row.method) == ("PL", "EUR", "works", "open")
    assert row.sector == "roads"  # CPV 45233140
    assert row.estimated_value == Decimal("200000") and row.award_value == Decimal("150000.50")
    assert row.num_bidders == 4 and row.award_date == date(2021, 12, 28) and row.year == 2022
    assert row.winner == "ALBA sp. z o.o.; Budimex S.A." and row.buyer == "Gmina Wrocław"
    assert row.url == "https://ted.europa.eu/udl?uri=TED:NOTICE:43-2022:TEXT:EN:HTML"


@pytest.mark.parametrize(
    "overrides,field,expected",
    [
        ({"ISO_COUNTRY_CODE": "UK"}, "country", "GB"),
        ({"ISO_COUNTRY_CODE": "EL"}, "country", "GR"),
        ({"TYPE_OF_CONTRACT": "S"}, "category", "services"),
        ({"TYPE_OF_CONTRACT": "U"}, "category", "goods"),
        ({"TOP_TYPE": "RES"}, "method", "limited"),
        ({"TOP_TYPE": "NOC"}, "method", "single"),
        ({"TOP_TYPE": "AWP"}, "method", "single"),
        ({"TOP_TYPE": "COD"}, "method", "other"),
        ({"TOP_TYPE": "NIC"}, "method", "other"),
        ({"NUMBER_OFFERS": ""}, "num_bidders", None),
        ({"NUMBER_OFFERS": "0"}, "num_bidders", None),
        ({"NUMBER_OFFERS": "40000"}, "num_bidders", None),  # would overflow the column
        ({"ID_AWARD": ""}, "source_id", "202243:1"),  # falls back to the lot
        ({"ID_AWARD": "", "ID_LOT": ""}, "source_id", "202243:7"),  # then the line
        ({"DT_AWARD": ""}, "award_date", date(2021, 12, 29)),  # dispatch date instead
        ({"DT_AWARD": "01/01/95"}, "award_date", date(2021, 12, 29)),  # mistyped year
    ],
)
def test_to_row_mapping_edges(overrides, field, expected):
    assert getattr(TED().to_row(_csv_row(**overrides), line=7), field) == expected


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"CANCELLED": "1"}, "cancelled_or_not_awarded"),
        ({"INFO_ON_NON_AWARD": "PROCUREMENT_UNSUCCESSFUL"}, "cancelled_or_not_awarded"),
        ({"B_FRA_AGREEMENT": "Y"}, "framework_or_dps"),
        ({"B_DYN_PURCH_SYST": "Y"}, "framework_or_dps"),
        ({"B_FRA_CONTRACT": "Y"}, "framework_or_dps"),
        ({"FRA_ESTIMATED": "A"}, "framework_or_dps"),
        ({"AWARD_EST_VALUE_EURO": ""}, "no_estimate_or_award"),
        ({"AWARD_VALUE_EURO": "0"}, "no_estimate_or_award"),
        ({"AWARD_VALUE_EURO": "1e15"}, "no_estimate_or_award"),  # typo-sized
        ({"AWARD_VALUE_EURO": "200000.00"}, "award_equals_estimate"),
        ({"AWARD_VALUE_EURO": "2000"}, "ratio_out_of_band"),
        ({"ISO_COUNTRY_CODE": ""}, "no_country"),
    ],
)
def test_to_row_skips_rows_that_would_pollute_the_ratio(overrides, reason):
    source = TED()
    assert source.to_row(_csv_row(**overrides)) is None
    assert source.counts[reason] == 1


def test_read_streams_the_csv_inside_the_zip():
    source = TED()
    rows = list(source.read(ZIP_2022))
    assert len(rows) == 15
    assert dict(source.counts) == {
        "rows": 32,
        "emitted": 15,
        "framework_or_dps": 6,
        "no_estimate_or_award": 5,
        "cancelled_or_not_awarded": 2,
        "award_equals_estimate": 2,
        "ratio_out_of_band": 2,
    }
    by_id = {r.source_id: r for r in rows}
    gb = by_id["202213060:13886978"]  # published as UK
    assert (gb.country, gb.method, gb.num_bidders) == ("GB", "limited", 4)
    # No DT_AWARD in the file: the dispatch date stands in.
    assert by_id["2022476:13843436"].award_date == date(2021, 12, 29)
    old = list(TED().read(ZIP_2008))
    assert [r.award_date for r in old][:2] == [date(2007, 10, 25), date(2007, 12, 14)]


def _mock_store(*years: int):
    for year, path in {2008: ZIP_2008, 2022: ZIP_2022}.items():
        route = respx.get(STORE.format(year))
        if year in years:
            route.mock(return_value=httpx.Response(200, content=path.read_bytes()))
        else:
            route.mock(side_effect=AssertionError(f"{year} should not be downloaded"))


@respx.mock
def test_run_import_end_to_end(raw_dir, prices):
    respx.get(DATASET_API).mock(
        return_value=httpx.Response(200, content=(FIXTURES / "datasets-ted-csv.json").read_bytes())
    )
    _mock_store(2008, 2022)
    run = run_import("ted", since=2007, min_interval=0)
    assert run.status == DatasetImport.Status.SUCCEEDED
    assert (run.rows_seen, run.rows_inserted, run.params["ratios"]) == (18, 18, 18)
    assert [f["url"].rsplit("-", 1)[-1] for f in run.files] == ["2008.zip", "2022.zip"]
    assert all(len(f["sha256"]) == 64 for f in run.files)
    assert (raw_dir / "ted" / "ted-contract-award-notices-2022.zip").exists()

    a = HistoricalAward.objects.get(source="ted", source_id="202243:13843104")
    assert (a.country, a.currency, a.sector, a.year) == ("PL", "EUR", "buildings", 2021)
    assert a.ratio == pytest.approx(124906.71 / 277851.55, rel=1e-5)
    # Euros convert at the euro area's rate (0.8/USD), not Poland's zloty rate.
    assert a.award_inr_real == Decimal("12490671.00")
    assert a.imported_id == run.id and a.url.startswith("https://ted.europa.eu/")

    # Idempotent: a second run updates the same rows from the cached files.
    again = run_import("ted", since=2007, min_interval=0)
    assert (again.rows_inserted, again.rows_updated) == (0, 18)
    assert HistoricalAward.objects.filter(source="ted").count() == 18


@respx.mock
def test_since_skips_earlier_years(raw_dir, prices):
    respx.get(DATASET_API).mock(
        return_value=httpx.Response(200, content=(FIXTURES / "datasets-ted-csv.json").read_bytes())
    )
    _mock_store(2022)
    run = run_import("ted", since=2010, min_interval=0)
    assert run.rows_inserted == 15 and len(run.files) == 1


@respx.mock
def test_year_urls_falls_back_to_the_store_pattern(raw_dir):
    respx.get(DATASET_API).mock(return_value=httpx.Response(503))
    ctx = base.ImportContext(TED(), min_interval=0)
    urls = TED().year_urls(ctx)
    assert sorted(urls) == list(range(2006, 2024))
    assert urls[2022] == STORE.format(2022)


@respx.mock
def test_year_urls_reads_the_catalogue():
    respx.get(DATASET_API).mock(
        return_value=httpx.Response(200, content=(FIXTURES / "datasets-ted-csv.json").read_bytes())
    )
    urls = TED().year_urls(base.ImportContext(TED(), min_interval=0))
    # Yearly award files only (no contract notices, no multi-year bundles); the 2006 store
    # zip is preferred over the legacy .csv.gz link.
    assert urls == {2006: STORE.format(2006), 2008: STORE.format(2008), 2022: STORE.format(2022)}


def test_file_option_reads_a_local_zip(prices):
    run = run_import("ted", file=str(ZIP_2008), min_interval=0)
    assert run.rows_inserted == 3 and run.files == []
    assert set(HistoricalAward.objects.values_list("country", flat=True)) == {"ES", "PL"}
