"""PMGSY history source (intel/sources/pmgsy.py) on a trimmed copy of the real CSV."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from intel.models import DatasetImport, HistoricalAward
from intel.sources import REGISTRY
from intel.sources.base import ImportContext, run_import
from intel.sources.pmgsy import DATASET_URL, DOWNLOAD_URL, Pmgsy, _award_date, _cost, _winner

pytestmark = pytest.mark.django_db

SAMPLE = Path(__file__).parent / "fixtures" / "intel" / "pmgsy" / "sample.csv"


def _rows(**kw) -> dict:
    src = Pmgsy()
    rows = list(src.rows(ImportContext(src, file=str(SAMPLE), min_interval=0, **kw)))
    return {r.source_id: r for r in rows}


def _by(rows: dict, package: str, title_start: str = "") -> list:
    return sorted(
        (
            r
            for k, r in rows.items()
            if k.split(":")[1] == package and r.title.startswith(title_start)
        ),
        key=lambda r: (r.award_date or date.min, r.source_id),
    )


def test_registered_as_history():
    cls = REGISTRY["pmgsy"]
    assert cls is Pmgsy and cls.kind == "history" and "ODC-BY" in cls.license
    assert cls.url == DATASET_URL


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3-4-2002", date(2002, 4, 3)),
        ("27-06-2004", date(2004, 6, 27)),
        ("9-11-2006", date(2006, 11, 9)),
        ("None", None),
        ("", None),
        ("31-02-2010", None),  # impossible
        ("1-1-2000", None),  # before the first sanction year: a placeholder
        ("1-1-2999", None),
        ("2004-10-28", None),  # not the file's format
    ],
)
def test_award_date(text, expected):
    assert _award_date(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("M/s L.N. Agarwal..", "M/s L.N. Agarwal"),
        ("RAJENDRA KUMAR KALAL . .", "RAJENDRA KUMAR KALAL"),
        ("Tomar Builders &amp; Contactors Pvt. Ltd.", "Tomar Builders & Contactors Pvt. Ltd"),
        ("BMS EXPENDITURE", ""),
        ("BMS WORK (BMS EXPENDITURE", ""),
        ("BMSEXPENDITURE", ""),
        ("BMS-07", ""),
        ("BMS TRADEWINGS PRIVATE LIMITED", "BMS TRADEWINGS PRIVATE LIMITED"),
        ("PROJECT AND DESIGN", ""),
        ("None", ""),
        ("0", ""),
        ("..", ""),
        ("q", ""),
        ("PWD Sikkim", "PWD Sikkim"),  # departmental execution is a real executor
    ],
)
def test_winner_cleaning(text, expected):
    assert _winner(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("9.0", Decimal("900000.0")),
        ("182.28", Decimal("18228000.00")),
        ("0.0", None),
        ("None", None),
        ("nan", None),
        ("0.01", None),  # Rs 1,000 for a road: an entry error
    ],
)
def test_cost_is_lakh(text, expected):
    assert _cost(text) == expected


def test_habitation_rows_collapse_into_one_award_per_road():
    rows = _rows()
    # 49 CSV rows (one per habitation) -> 37 awards.
    assert len(rows) == 37
    (road,) = _by(rows, "APVII0218")  # five habitation rows, one road, one contract
    assert road.title == "Gyaragondanapalli - Hallikera (upgradation)"
    assert road.estimated_value == Decimal("18228000.00") and road.award_value is None
    assert road.winner == "Y.Doddaiah" and road.award_date == date(2009, 9, 19)
    assert (road.state, road.district) == ("Andhra Pradesh", "Anantapur")
    assert (road.category, road.sector, road.method, road.country) == (
        "works",
        "roads",
        "open",
        "IN",
    )
    assert road.tender_date is None and road.url == DATASET_URL


def test_a_reawarded_road_keeps_both_awards():
    first, second = _by(rows := _rows(), "AP02X216")
    assert (first.award_date, first.winner) == (date(2013, 11, 21), "Mekala Subbarayudu")
    assert (second.award_date, second.winner) == (
        date(2016, 6, 16),
        "M/s Lakshmi Narasimha Metal Enterprises",
    )
    assert first.source_id != second.source_id and len(rows) == 37


def test_spelling_variants_of_one_award_are_one_row():
    (award,) = _by(_rows(), "AP02X224")
    assert award.winner in {"M/s. Tirumala Constructions", "M/S Thirumala Constructions"}


def test_a_resanctioned_road_uses_the_sanction_before_each_award():
    first, second = _by(_rows(), "AR0301066")
    assert (first.award_date.year, first.estimated_value) == (2010, Decimal("26028000.00"))
    assert (second.award_date.year, second.estimated_value) == (2013, Decimal("24134000.00"))


def test_rows_without_award_date_take_the_sanction_year():
    (road,) = _by(_rows(), "AP02IXLB07", "NH 7")
    assert road.award_date is None and road.year == 2010 and road.winner == ""
    assert road.source_id.endswith(":-")


def test_unnamed_roads_are_not_merged():
    unnamed = _by(_rows(), "AR1206013")
    assert len(unnamed) == 2 and {r.title for r in unnamed} == {"PMGSY rural road"}


def test_states_placeholders_and_entities():
    rows = _rows()
    (jk,) = _by(rows, "JK0103")
    assert jk.state == "Jammu and Kashmir"
    (bms,) = _by(rows, "UP0101")
    assert bms.winner == "" and bms.estimated_value == Decimal("431000.00")
    (amp,) = _by(rows, "AP02X233")
    assert amp.winner == "M/S M.C. Anki Reddy & co"


def test_since_filters_by_year():
    rows = _rows(since=2013)
    assert rows and all(
        (r.award_date.year if r.award_date else r.year) >= 2013 for r in rows.values()
    )
    assert len(rows) == 7


def test_import_end_to_end_and_idempotent():
    run = run_import("pmgsy", file=str(SAMPLE), min_interval=0)
    assert run.status == DatasetImport.Status.SUCCEEDED
    # Two awards have no usable cost (0.0 and 0.01 lakh) and nothing else to learn from.
    assert (run.rows_seen, run.rows_inserted, run.rows_skipped) == (37, 35, 2)
    assert run.params["ratios"] == 0
    assert run.files and run.files[0]["sha256"] and run.files[0]["bytes"] == SAMPLE.stat().st_size

    a = HistoricalAward.objects.get(source="pmgsy", source_id__startswith="28:APVII0218:")
    assert a.ratio is None and a.award_value is None
    assert a.estimated_value == Decimal("18228000.00") and a.year == 2009
    assert a.sector == "roads" and a.winner_key
    undated = HistoricalAward.objects.get(source_id__startswith="28:AP02IXLB07:b2e8")
    assert undated.year == 2010 and undated.award_date is None  # AwardRow.year fallback

    again = run_import("pmgsy", file=str(SAMPLE), min_interval=0)
    assert (again.rows_inserted, again.rows_updated) == (0, 35)
    assert HistoricalAward.objects.filter(source="pmgsy").count() == 35


def test_downloads_through_the_redirect_and_records_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr("intel.sources.base.RAW_DIR", tmp_path)
    signed = "https://s3.example.org/pmgsy.csv?X-Amz-Signature=abc"
    with respx.mock(assert_all_called=True) as router:
        router.get(DOWNLOAD_URL).mock(
            return_value=httpx.Response(302, headers={"Location": signed})
        )
        router.get(signed).mock(return_value=httpx.Response(200, content=SAMPLE.read_bytes()))
        run = run_import("pmgsy", limit=5, min_interval=0)
    assert run.rows_seen == 5
    assert (tmp_path / "pmgsy" / "pmgsy-financial-and-physical-report.csv").exists()
    assert run.files[0]["url"] == DOWNLOAD_URL


def test_unexpected_columns_fail_loudly(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text('"id","state_name"\n1,"Bihar"\n')
    with pytest.raises(ValueError, match="missing columns"):
        run_import("pmgsy", file=str(bad), min_interval=0)
    assert DatasetImport.objects.get(source="pmgsy").status == DatasetImport.Status.FAILED


def test_placeholder_company_does_not_fall_back_to_the_contractor_column(tmp_path):
    header = SAMPLE.read_text().splitlines()[0]
    cols = [c.strip('"') for c in header.split(",")]
    base = dict.fromkeys(cols, "None") | {
        "id": "1",
        "state_name": "West Bengal",
        "state_code": "19",
        "district_name": "Bankura",
        "road_name": "Road A",
        "packages": "WB0101",
        "upgrade_or_new": "New Connectivity",
        "sanctioned_year": "2005-2006",
        "work_award_date": "5-1-2007",
        "total_cost": "120.5",
    }
    rows = [
        base | {"company_name": "PROJECT AND DESIGN", "contractor_name": "Barun-Das"},
        base | {"id": "2", "road_name": "Road B", "contractor_name": "Sri Ram Builders"},
    ]
    path = tmp_path / "pmgsy.csv"
    path.write_text(
        header + "\n" + "\n".join(",".join(f'"{r[c]}"' for c in cols) for r in rows) + "\n"
    )
    src = Pmgsy()
    out = {r.title: r for r in src.rows(ImportContext(src, file=str(path), min_interval=0))}
    assert out["Road A (new connectivity)"].winner == ""
    assert out["Road B (new connectivity)"].winner == "Sri Ram Builders"  # company missing
    assert out["Road A (new connectivity)"].estimated_value == Decimal("12050000.0")
