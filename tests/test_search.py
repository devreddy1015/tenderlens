"""Tender search on Postgres (tenders/search.py): ranking, typos, partial words, IDs, facets."""

import pytest
from django.db import connection
from rest_framework.test import APIClient

from ingest.loader import load_detail_page
from tenders import search
from tenders.models import Tender
from tests.conftest import CENTRAL

pytestmark = pytest.mark.django_db


@pytest.fixture
def loaded(make_page):
    for p in sorted(CENTRAL.glob("detail_*.html")):
        load_detail_page(make_page(p.read_text(encoding="utf-8")))
    search.refresh_words()  # the hourly task in production
    return Tender.objects.count()


def ids_for(**params):
    return [t.pk for t in search.search(params)["results"]]


def titles_for(q):
    return [t.title for t in search.search({"q": q})["results"]]


def test_search_vector_is_generated_on_write(loaded):
    """The loader's raw upsert fills the generated column: there is no index to sync."""
    assert loaded == 18
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM tender WHERE search_vector IS NOT NULL")
        assert cur.fetchone()[0] == 18


@pytest.mark.parametrize(
    "query,expected_word",
    [
        ("toilet", "toilet"),  # exact
        ("toilets", "toilet"),  # english stemming
        ("toliet", "toilet"),  # misspelling (typo correction)
        ("conserv", "conservation"),  # partial word (prefix match)
        ("consrvation monumnt", "monument"),  # two misspellings
        ("solar plant", "solar"),
        ("bridge", "bridge"),
    ],
)
def test_misspelled_and_partial_queries_find_tender(loaded, query, expected_word):
    titles = titles_for(query)
    assert titles, f"no hits for {query!r}"
    assert expected_word in titles[0].lower()


def test_correction_is_reported(loaded):
    res = search.search({"q": "toliet"})
    assert res["corrected"] == "toilet"
    assert search.search({"q": "toilet"})["corrected"] is None


def test_tender_id_query_is_exact(loaded):
    ids = ids_for(q="2026_DDA_928692_1")
    assert Tender.objects.get(pk=ids[0]).source_tender_id == "2026_DDA_928692_1"
    lower = ids_for(q="2026_dda_928692_1")  # case-insensitive
    assert lower[0] == ids[0]


def test_reference_number_query_finds_tender(loaded):
    t = Tender.objects.exclude(ref_no="").first()
    assert ids_for(q=t.ref_no)[0] == t.pk


def test_facets_match_database(loaded):
    res = search.search({})
    assert res["total"] == 18
    by_state = {b["key"]: b["count"] for b in res["facets"]["state"]}
    for state, n in by_state.items():
        assert Tender.objects.filter(state=state).count() == n
    by_cat = {b["key"]: b["count"] for b in res["facets"]["category"]}
    assert sum(by_cat.values()) == 18
    over_10cr = next(b for b in res["facets"]["value_range"] if b["key"] == "over_10_crore")
    assert over_10cr["count"] == Tender.objects.filter(value_inr__gte=100_000_000).count()


def test_filters_combine_with_query(loaded):
    delhi = ids_for(state="Delhi")
    assert delhi and all(Tender.objects.get(pk=i).state == "Delhi" for i in delhi)
    big = ids_for(min_value=10_000_000)
    assert set(big) == set(
        Tender.objects.filter(value_inr__gte=10_000_000).values_list("id", flat=True)
    )
    t = Tender.objects.filter(title__icontains="toilet").first()
    assert ids_for(q="toilet", state=t.state)
    other = Tender.objects.exclude(state=t.state).exclude(state="").first()
    assert all(
        Tender.objects.get(pk=i).state == other.state
        for i in ids_for(q="toilet", state=other.state)
    )


def test_api_search(loaded):
    body = APIClient().get("/api/tenders", {"q": "toliet"}).json()
    assert body["search_backend"] == "postgres"
    assert body["corrected"] == "toilet"
    assert "toilet" in body["results"][0]["title"].lower()
    assert body["facets"]["state"]


def test_title_match_outranks_buyer_name_match(loaded):
    """'maintenance' appears in buyer names too; tenders *about* maintenance come first."""
    ids = ids_for(q="maintenence")  # misspelt
    assert ids
    assert "maintenance" in Tender.objects.get(pk=ids[0]).title.lower()
    ids = ids_for(q="maintenance")
    assert "maintenance" in Tender.objects.get(pk=ids[0]).title.lower()


def test_relaxed_fallback_when_no_title_has_every_word(loaded):
    strict = search.search({"q": "toilet zebra"})
    assert strict["relaxed"] is True
    assert strict["total"] >= 1
    assert search.search({"q": "toilet"})["relaxed"] is False


def test_nonsense_finds_nothing(loaded):
    res = search.search({"q": "qwxzv"})
    assert res["total"] == 0 and res["results"] == []
    assert search.search({"q": '"" -'})["total"] == 0  # no searchable words


def test_websearch_syntax(loaded):
    toilets = set(ids_for(q="toilet"))
    assert set(ids_for(q='"toilet block"')) <= toilets
    assert not set(ids_for(q="toilet -toilet"))
    either = set(ids_for(q="toilet or bridge"))
    assert toilets | set(ids_for(q="bridge")) == either


def test_sorts(loaded):
    newest = search.search({"sort": "newest"}, page_size=50)["results"]
    assert [t.published_at for t in newest] == sorted(
        (t.published_at for t in newest), reverse=True
    )
    closing = search.search({"sort": "closing"}, page_size=50)["results"]
    assert [t.closes_at for t in closing] == sorted(t.closes_at for t in closing)
    by_value = [t.value_inr for t in search.search({"sort": "value"}, page_size=50)["results"]]
    known = [v for v in by_value if v is not None]
    assert known == sorted(known, reverse=True)
    assert by_value[: len(known)] == known  # unknown values last


def test_pagination(loaded):
    first = search.search({}, page=1, page_size=5)
    second = search.search({}, page=2, page_size=5)
    assert first["total"] == second["total"] == 18
    assert not set(first["ids"]) & set(second["ids"])


def test_facets_are_disjunctive(loaded):
    res = search.search({"sector": "roads"})
    sectors = {b["key"]: b["count"] for b in res["facets"]["sector"]}
    assert len(sectors) > 1
    assert sectors["roads"] == res["total"] == Tender.objects.filter(sector="roads").count()
    states = {b["key"]: b["count"] for b in res["facets"]["state"]}
    assert sum(states.values()) == Tender.objects.filter(sector="roads").exclude(state="").count()


def test_similar_prefers_same_sector(loaded, monkeypatch):
    t = Tender.objects.get(source_tender_id="2026_DDA_928692_1")
    # The fixtures' tenders close in October 2026; "open" is relative to a fixed day.
    when = min(Tender.objects.values_list("closes_at", flat=True))
    monkeypatch.setattr("tenders.search.timezone.now", lambda: when)
    rows = search.similar(t)
    assert rows and t.pk not in [r.pk for r in rows]
    same = [r for r in rows if r.sector == t.sector]
    assert rows[: len(same)] == same  # same-sector results come first
