import gzip
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from intel.models import DatasetImport, HistoricalAward, PriceIndex
from intel.sources import base
from intel.sources.base import run_import
from intel.sources.ocds import OCDSSource, Peru, fold, ipv4_client

pytestmark = pytest.mark.django_db

FIXTURE = Path(__file__).parent / "fixtures" / "intel" / "peru" / "2026.jsonl.gz"
DOWNLOAD = "https://data.open-contracting.org/en/publication/135/download"
CDN = "https://fastly.data.open-contracting.org/downloads/peru_oece_bulk/4263/{}.jsonl.gz"


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "RAW_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def prices():
    for year in (2025, 2026):
        PriceIndex.objects.create(series="cpi", country="IN", year=year, value=100.0)
        PriceIndex.objects.create(series="fx_per_usd", country="IN", year=year, value=80.0)
        PriceIndex.objects.create(series="fx_per_usd", country="PE", year=year, value=4.0)


def _records() -> list[dict]:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


class Generic(OCDSSource):
    """An unregistered publication with standard lots, CPV items and no Peru quirks."""

    key = "ocds-test"
    name = "test"
    url = "https://example.org"
    license = "CC0"
    publication = 1
    country = "MD"
    currency = "MDL"
    first_year = 2020


def _release(**tender_kw) -> dict:
    tender = {
        "title": "Reparatia drumului",
        "value": {"amount": 300, "currency": "MDL"},
        "procurementMethod": "open",
        "mainProcurementCategory": "works",
        "numberOfTenderers": 4,
        "datePublished": "2021-03-01T00:00:00Z",
        "items": [{"id": "i1", "classification": {"scheme": "CPV", "id": "45233140-2"}}],
        "lots": [
            {"id": "L1", "value": {"amount": 100, "currency": "MDL"}},
            {"id": "L2", "value": {"amount": 200, "currency": "MDL"}},
        ],
        **tender_kw,
    }
    return {
        "ocid": "ocds-x-1",
        "buyer": {"id": "b1", "name": "Primaria Chisinau"},
        "parties": [{"id": "b1", "roles": ["buyer"], "address": {"region": "CHISINAU"}}],
        "tender": tender,
        "awards": [
            {
                "id": "a1",
                "status": "active",
                "date": "2021-05-01",
                "value": {"amount": 90, "currency": "MDL"},
                "relatedLots": ["L1"],
                "suppliers": [{"name": "Drumuri SRL"}],
            },
            {
                "id": "a2",
                "status": "active",
                "date": "2021-05-02",
                "value": {"amount": 150, "currency": "MDL"},
                "relatedLots": ["L2"],
                "suppliers": [{"name": "Asfalt SA"}, {"name": "Beton SRL"}],
            },
        ],
    }


def test_lot_level_awards_match_their_own_lot_estimate():
    rows = list(Generic().release_rows(_release()))
    assert [(r.source_id, r.estimated_value, r.award_value) for r in rows] == [
        ("ocds-x-1:a1", Decimal("100"), Decimal("90")),
        ("ocds-x-1:a2", Decimal("200"), Decimal("150")),
    ]
    a2 = rows[1]
    # The tender-wide bidder count is not the count for one lot.
    assert a2.num_bidders is None
    assert (a2.country, a2.currency, a2.category, a2.method) == ("MD", "MDL", "works", "open")
    assert (a2.sector, a2.state, a2.winner) == ("roads", "Chisinau", "Asfalt SA; Beton SRL")
    assert a2.award_date == date(2021, 5, 2) and a2.tender_date == date(2021, 3, 1)


def test_single_lot_keeps_the_bidder_count():
    release = _release(lots=[{"id": "L1", "value": {"amount": 100, "currency": "MDL"}}])
    release["awards"] = release["awards"][:1]
    release["awards"][0].pop("relatedLots")
    (row,) = Generic().release_rows(release)
    assert (row.estimated_value, row.num_bidders) == (Decimal("100"), 4)


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda r: r["awards"][1].pop("relatedLots"), "ambiguous_scope"),
        (lambda r: r["awards"][1].update(relatedLots=["L1"]), "ambiguous_scope"),
        (lambda r: r["awards"][1].update(relatedLots=["L1", "L2"]), "ambiguous_scope"),
        (lambda r: r["tender"].pop("value"), "no_estimate"),
        (lambda r: r["tender"]["value"].update(currency="GBP"), "other_currency"),
        (lambda r: r.update(awards=[]), "no_award"),
        (lambda r: [a.update(status="cancelled") for a in r["awards"]], "no_award"),
    ],
)
def test_ambiguous_or_unusable_records_are_skipped(mutate, reason):
    release = _release()
    mutate(release)
    source = Generic()
    assert list(source.release_rows(release)) == []
    assert source.counts[reason] == 1


def test_per_row_checks():
    release = _release()
    release["awards"][0]["value"]["currency"] = "USD"  # award in another currency
    release["awards"][1]["value"]["amount"] = 1  # 1/200: out of band
    source = Generic()
    assert list(source.release_rows(release)) == []
    assert source.counts["currency_mismatch"] == 1 and source.counts["ratio_out_of_band"] == 1
    assert [r.source_id for r in Generic().release_rows(_release(), since=2022)] == []


def test_peru_fixture_records():
    source = Peru()
    rows = [row for record in _records() for row in source.release_rows(record)]
    assert source.counts["records"] == 12
    assert {k: source.counts[k] for k in ("emitted", "ambiguous_scope", "no_award")} == {
        "emitted": 8,
        "ambiguous_scope": 2,  # an item awarded twice; items not adding up to the value
        "no_award": 1,
    }
    assert source.counts["no_estimate"] == 1 and source.counts["ratio_out_of_band"] == 1
    by_id = {r.source_id: r for r in rows}

    works = by_id["ocds-dgv273-seacev3-1181800:1181800-1762914"]
    assert (works.country, works.currency, works.category, works.method) == (
        "PE",
        "PEN",
        "works",
        "open",  # Licitación Pública Abreviada
    )
    assert (works.estimated_value, works.award_value) == (
        Decimal("2280624.88"),
        Decimal("2280431.61"),
    )
    assert works.num_bidders == 20 and works.state == "Lima" and works.winner == "CONSORCIO VEGAS"
    assert works.title.startswith("CONTRATACION PARA LA EJECUCION DE OBRA")  # not the code
    assert works.award_date == date(2026, 2, 3)

    # Two items, two suppliers: each award against its own item's estimate.
    milk = by_id["ocds-dgv273-seacev3-1184803:1184803-20611819367"]
    assert (milk.estimated_value, milk.num_bidders) == (Decimal("117180.0"), None)
    assert milk.title == "LECHE EVAPORADA ENTERA POR 410 GR"
    # One of two items awarded: the estimate is that item's, not the tender's 48,000.
    partial = by_id["ocds-dgv273-seacev3-2026-1952-58:1187138-10701062537"]
    assert partial.estimated_value == Decimal("24000.0")

    methods = {r.source_id.split(":")[0][-7:]: r.method for r in rows}
    assert methods["1184562"] == "reverse_auction"
    assert methods["1184359"] == "qcbs"  # Concurso Público: scored, not lowest price
    assert methods["1254831"] == "single"
    assert by_id["ocds-dgv273-seacev3-1254783:1254783-L0000005736"].currency == "USD"


@pytest.mark.parametrize(
    "text,category,sector",
    [
        ("Mejoramiento de la carretera vecinal", "works", "roads"),
        ("Construcción del puente Huallaga", "works", "roads"),
        ("Supervisión de la obra de la carretera", "services", "consultancy"),
        ("Elaboración del expediente técnico", "services", "consultancy"),
        ("Ampliación del sistema de agua potable y alcantarillado", "works", "water"),
        ("Electrificación rural", "works", "electrical"),
        ("Adquisición de equipos de cómputo", "goods", "it"),
        ("Adquisición de medicamentos", "goods", "health"),
        ("Servicio de vigilancia", "services", "security"),
        ("Servicio de limpieza", "services", "facility"),
        ("Construcción de la institución educativa", "works", "buildings"),
        ("Servicio de medición de caudales", "services", "other"),  # not "médico"
        ("Adquisición de uniformes", "goods", "supplies"),
        ("Mejoramiento de local comunal", "works", "buildings"),
    ],
)
def test_spanish_sector_keywords(text, category, sector):
    assert Peru().sector(text, category, []) == sector


@pytest.mark.parametrize(
    "details,method",
    [
        ("Licitación Pública", "open"),
        ("Adjudicación Simplificada", "open"),
        ("Subasta Inversa Electrónica", "reverse_auction"),
        ("Contratación Directa", "single"),
        ("Concurso Público", "qcbs"),
        ("Selección de Consultores Individuales", "qcbs"),
        ("Adjudicación Directa Selectiva", "limited"),
        ("Adjudicación de Menor Cuantía", "limited"),
        ("Comparación de Precios", "limited"),
        ("Convenio", "other"),
        ("Contratación Internacional", "other"),
    ],
)
def test_peru_methods(details, method):
    assert Peru().method({"procurementMethodDetails": details}) == method


def test_fold_strips_accents():
    assert fold("ELECTRIFICACIÓN Rural") == "electrificacion rural"


def test_read_unwraps_records_and_survives_bad_lines(tmp_path):
    path = tmp_path / "x.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"ocid": "ocds-x-1", "compiledRelease": _release()}) + "\n")
        fh.write("{not json\n\n")
    source = Generic()
    assert len(list(source.read(path))) == 2
    assert source.counts["bad_json"] == 1


def test_ipv4_client_keeps_headers_and_timeouts():
    client = ipv4_client(httpx.Client(headers={"User-Agent": "TenderLens-test"}, timeout=7))
    assert client.headers["User-Agent"] == "TenderLens-test"
    assert client.timeout.read == 7 and client.follow_redirects
    assert client._transport._pool._local_address == "0.0.0.0"


@respx.mock
def test_run_import_end_to_end(raw_dir, prices, monkeypatch):
    monkeypatch.setattr(Peru, "last_year", 2026)
    respx.get(DOWNLOAD, params={"name": "2025.jsonl.gz"}).mock(return_value=httpx.Response(404))
    respx.get(DOWNLOAD, params={"name": "2026.jsonl.gz"}).mock(
        return_value=httpx.Response(302, headers={"Location": CDN.format(2026)})
    )
    respx.get(CDN.format(2026)).mock(
        side_effect=[httpx.ConnectError("reset"), httpx.Response(200, content=FIXTURE.read_bytes())]
    )
    run = run_import("peru", since=2025, min_interval=0)
    assert run.status == DatasetImport.Status.SUCCEEDED
    assert (run.rows_seen, run.rows_inserted, run.params["ratios"]) == (8, 8, 8)
    assert len(run.files) == 1 and (raw_dir / "peru" / "2026.jsonl.gz").exists()
    a = HistoricalAward.objects.get(source_id="ocds-dgv273-seacev3-1184562:1184562-20350218689")
    assert a.ratio == pytest.approx(174900 / 176000) and a.year == 2026
    assert a.award_inr_real == Decimal("3498000.00")  # PEN 174,900 / 4 * 80
    usd = HistoricalAward.objects.get(source_id__endswith=":1254783-L0000005736")
    assert usd.award_inr_real == Decimal("880000.00")

    again = run_import("peru", since=2026, min_interval=0)  # from the cache
    assert (again.rows_inserted, again.rows_updated) == (0, 8)
