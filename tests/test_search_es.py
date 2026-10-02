"""Search against a real Elasticsearch (skipped when ES_URL is unreachable)."""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from ingest.loader import load_detail_page
from tenders import search
from tenders.models import Tender
from tests.conftest import CENTRAL

pytestmark = [pytest.mark.django_db, pytest.mark.es]


@pytest.fixture
def es_index(settings, make_page):
    settings.ES_ENABLED = True
    settings.ES_INDEX = "tenders_test"
    if not search.available():
        pytest.skip("elasticsearch not reachable")
    search.ensure_index(recreate=True)
    for p in sorted(CENTRAL.glob("detail_*.html")):
        load_detail_page(make_page(p.read_text(encoding="utf-8")))  # indexes via on_commit task
    search.client().indices.refresh(index=settings.ES_INDEX)
    yield
    search.client().indices.delete(index="tenders_test", ignore_unavailable=True)


def ids_for(**params):
    return search.search(params)["ids"]


def titles_for(q):
    return [Tender.objects.get(pk=i).title for i in ids_for(q=q)]


@pytest.mark.django_db(transaction=True)
def test_upsert_indexes_document(es_index):
    assert search.client().count(index=settings.ES_INDEX)["count"] == 18


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "query,expected_word",
    [
        ("toilet", "toilet"),  # exact
        ("toilets", "toilet"),  # english stemming
        ("toliet", "toilet"),  # misspelling (fuzziness AUTO)
        ("conserv", "conservation"),  # partial word (edge n-grams)
        ("consrvation monumnt", "monument"),  # two misspellings
        ("solar plant", "solar"),
        ("bridge", "bridge"),
    ],
)
def test_misspelled_and_partial_queries_find_tender(es_index, query, expected_word):
    titles = titles_for(query)
    assert titles, f"no hits for {query!r}"
    assert expected_word in titles[0].lower()


@pytest.mark.django_db(transaction=True)
def test_tender_id_query_is_exact(es_index):
    ids = ids_for(q="2026_DDA_928692_1")
    assert Tender.objects.get(pk=ids[0]).source_tender_id == "2026_DDA_928692_1"


@pytest.mark.django_db(transaction=True)
def test_facets_match_database(es_index):
    res = search.search({})
    assert res["total"] == 18
    by_state = {b["key"]: b["count"] for b in res["facets"]["state"]}
    for state, n in by_state.items():
        assert Tender.objects.filter(state=state).count() == n
    by_cat = {b["key"]: b["count"] for b in res["facets"]["category"]}
    assert sum(by_cat.values()) == 18
    over_10cr = next(b for b in res["facets"]["value_range"] if b["key"] == "over_10_crore")
    assert over_10cr["count"] == Tender.objects.filter(value_inr__gte=100_000_000).count()


@pytest.mark.django_db(transaction=True)
def test_filters_combine_with_query(es_index):
    delhi = ids_for(state="Delhi")
    assert delhi and all(Tender.objects.get(pk=i).state == "Delhi" for i in delhi)
    big = ids_for(min_value=10_000_000)
    assert set(big) == set(
        Tender.objects.filter(value_inr__gte=10_000_000).values_list("id", flat=True)
    )


@pytest.mark.django_db(transaction=True)
def test_api_uses_elasticsearch_when_available(es_index):
    body = APIClient().get("/api/tenders", {"q": "toliet"}).json()
    assert body["search_backend"] == "elasticsearch"
    assert "toilet" in body["results"][0]["title"].lower()
    assert body["facets"]["state"]


@pytest.mark.django_db(transaction=True)
def test_title_match_outranks_buyer_name_match(es_index):
    """'maintenance' appears in buyer names too; tenders *about* maintenance come first."""
    ids = ids_for(q="maintenence")  # misspelt
    assert ids
    assert "maintenance" in Tender.objects.get(pk=ids[0]).title.lower()


@pytest.mark.django_db(transaction=True)
def test_relaxed_fallback_when_no_title_has_every_word(es_index):
    strict = search.search({"q": "toilet zebra"})
    assert strict["relaxed"] is True
    assert strict["total"] >= 1
    assert search.search({"q": "toilet"})["relaxed"] is False


@pytest.mark.django_db(transaction=True)
def test_facets_are_disjunctive_in_elasticsearch(es_index):
    res = search.search({"sector": "roads"})
    sectors = {b["key"]: b["count"] for b in res["facets"]["sector"]}
    assert len(sectors) > 1
    assert sectors["roads"] == res["total"] == Tender.objects.filter(sector="roads").count()
    states = {b["key"]: b["count"] for b in res["facets"]["state"]}
    assert sum(states.values()) == Tender.objects.filter(sector="roads").exclude(state="").count()


@pytest.mark.django_db(transaction=True)
def test_similar_prefers_same_sector(es_index):
    t = Tender.objects.get(source_tender_id="2026_DDA_928692_1")
    ids = search.similar(t)
    same = [i for i in ids if Tender.objects.get(pk=i).sector == t.sector]
    assert ids and same[: len(same)] == ids[: len(same)]  # same-sector results come first
