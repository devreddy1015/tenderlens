"""Elasticsearch index, document mapping and search queries.

title is analysed with the English analyser (stemming: "roads" finds "road") plus an
edge n-gram sub-field for partial words ("constr" finds "construction"). Misspellings
are handled by fuzziness=AUTO on the main query.
"""

import contextlib
import logging
from functools import lru_cache

from django.conf import settings
from elasticsearch import Elasticsearch, NotFoundError, helpers

log = logging.getLogger(__name__)

VALUE_RANGES = [
    {"key": "under_10_lakh", "to": 1_000_000},
    {"key": "10_lakh_to_1_crore", "from": 1_000_000, "to": 10_000_000},
    {"key": "1_to_10_crore", "from": 10_000_000, "to": 100_000_000},
    {"key": "over_10_crore", "from": 100_000_000},
]

INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "filter": {
                "autocomplete_filter": {"type": "edge_ngram", "min_gram": 2, "max_gram": 15}
            },
            "analyzer": {
                "autocomplete": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding", "autocomplete_filter"],
                },
                "autocomplete_search": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        },
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "long"},
            "source": {"type": "keyword"},
            "source_tender_id": {"type": "keyword"},
            "ref_no": {"type": "keyword", "fields": {"text": {"type": "text"}}},
            "title": {
                "type": "text",
                "analyzer": "english",
                "fields": {
                    # Unstemmed copy for typo matching: fuzziness runs on analysed terms,
                    # and stemming ("conservation" -> "conserv") pushes a misspelling
                    # ("consrvation" -> "consrvat") beyond the 2-edit limit.
                    "plain": {"type": "text", "analyzer": "standard"},
                    "auto": {
                        "type": "text",
                        "analyzer": "autocomplete",
                        "search_analyzer": "autocomplete_search",
                    },
                },
            },
            "buyer": {"type": "keyword"},
            "buyer_id": {"type": "long"},
            "buyer_text": {"type": "text", "analyzer": "english"},
            "org_chain": {"type": "text"},
            "state": {"type": "keyword"},
            "pincode": {"type": "keyword"},
            "sector": {"type": "keyword"},
            "category": {"type": "keyword"},
            "product_category": {"type": "keyword"},
            "location": {"type": "text"},
            "value_inr": {"type": "double"},
            "emd_inr": {"type": "double"},
            "published_at": {"type": "date"},
            "closes_at": {"type": "date"},
        },
    },
}


@lru_cache(maxsize=1)
def client() -> Elasticsearch:
    return Elasticsearch(settings.ES_URL, request_timeout=10, retry_on_timeout=True, max_retries=2)


def available() -> bool:
    if not settings.ES_ENABLED:
        return False
    try:
        return bool(client().ping())
    except Exception:
        return False


def ensure_index(recreate: bool = False) -> None:
    es = client()
    if recreate:
        es.indices.delete(index=settings.ES_INDEX, ignore_unavailable=True)
    if not es.indices.exists(index=settings.ES_INDEX):
        es.indices.create(index=settings.ES_INDEX, body=INDEX_BODY)


def to_doc(t) -> dict:
    buyer = t.buyer_entity.canonical_name if t.buyer_entity_id else t.buyer_raw
    return {
        "id": t.id,
        "source": t.source,
        "source_tender_id": t.source_tender_id,
        "ref_no": t.ref_no,
        "title": t.title,
        "buyer": buyer,
        "buyer_id": t.buyer_entity_id,
        "buyer_text": f"{buyer} {t.buyer_raw}",
        "org_chain": t.org_chain,
        "state": t.state or None,
        "pincode": t.pincode or None,
        "sector": t.sector or None,
        "category": t.category or None,
        "product_category": t.product_category or None,
        "location": t.location,
        "value_inr": float(t.value_inr) if t.value_inr is not None else None,
        "emd_inr": float(t.emd_inr) if t.emd_inr is not None else None,
        "published_at": t.published_at.isoformat(),
        "closes_at": t.closes_at.isoformat(),
    }


def index_one(tender) -> None:
    client().index(index=settings.ES_INDEX, id=str(tender.id), document=to_doc(tender))


def delete_one(tender_id: int) -> None:
    with contextlib.suppress(NotFoundError):
        client().delete(index=settings.ES_INDEX, id=str(tender_id))


def bulk_index(tenders) -> int:
    actions = (
        {"_index": settings.ES_INDEX, "_id": str(t.id), "_source": to_doc(t)} for t in tenders
    )
    ok, _ = helpers.bulk(client(), actions, chunk_size=500, refresh="wait_for")
    return ok


def similar(tender, size: int = 6) -> list[int]:
    """Open tenders like this one: similar title words *within the same sector*.

    Without the sector filter, rare words like the buyer's name in the title ("FACT
    Udyogamandal") dominate, and "similar" becomes "same buyer, any kind of work".
    """
    ids: list[int] = []
    if tender.sector and tender.sector != "other":
        ids = _similar(tender, size, [{"term": {"sector": tender.sector}}])
    if len(ids) < size:
        ids += [i for i in _similar(tender, size, []) if i not in ids][: size - len(ids)]
    return ids


def _similar(tender, size: int, extra_filters: list) -> list[int]:
    resp = client().search(
        index=settings.ES_INDEX,
        size=size,
        source=False,
        query={
            "bool": {
                "must": [
                    {
                        "more_like_this": {
                            "fields": ["title"],
                            "like": [{"_index": settings.ES_INDEX, "_id": str(tender.id)}],
                            "min_term_freq": 1,
                            "min_doc_freq": 2,
                            "max_query_terms": 20,
                        }
                    }
                ],
                "filter": [{"range": {"closes_at": {"gte": "now"}}}, *extra_filters],
            }
        },
    )
    return [int(h["_id"]) for h in resp["hits"]["hits"]]


def text_query(q: str, *, relaxed: bool = False) -> dict:
    """Ranking, highest first: every word in the title (stemmed, then with typos) ->
    every word as a title prefix -> most words anywhere (buyer, location, ...).

    Without the title-first clauses a rare word in a buyer name ("Estate Maintenance
    Section") outranks tenders that are actually about maintenance. relaxed=True is the
    fallback when nothing matches: any one word is enough.
    """
    loose = {
        "multi_match": {
            "query": q,
            "fields": ["title.plain^2", "buyer_text", "location", "org_chain^0.5"],
            "fuzziness": "AUTO",
            "prefix_length": 1,
            "minimum_should_match": "1" if relaxed else "2<75%",
        }
    }
    return {
        "bool": {
            "should": [
                {"match": {"title": {"query": q, "operator": "and", "boost": 4}}},
                {
                    "match": {
                        "title.plain": {
                            "query": q,
                            "fuzziness": "AUTO",
                            "prefix_length": 1,
                            "operator": "and",
                            "boost": 3,
                        }
                    }
                },
                {"match": {"title.auto": {"query": q, "operator": "and", "boost": 2}}},
                loose,
                {"term": {"source_tender_id": {"value": q, "boost": 20}}},
                {"term": {"ref_no": {"value": q, "boost": 20}}},
            ],
            "minimum_should_match": 1,
        }
    }


FACET_FIELDS = ("state", "sector", "category", "value_range")


def facet_filters(params: dict) -> dict[str, dict]:
    """Filters that belong to a facet group, keyed by that group."""
    out: dict[str, dict] = {}
    for field in ("state", "sector", "category"):
        if params.get(field):
            out[field] = {"term": {field: params[field]}}
    rng = {}
    if params.get("min_value") is not None:
        rng["gte"] = float(params["min_value"])
    if params.get("max_value") is not None:
        rng["lte"] = float(params["max_value"])
    if rng:
        out["value_range"] = {"range": {"value_inr": rng}}
    return out


def build_query(params: dict, *, relaxed: bool = False) -> dict:
    """Text query plus the filters that are *not* facets. Facet filters go into
    post_filter (see _search) so each facet can be counted without its own filter."""
    must, filters = [], []
    q = (params.get("q") or "").strip()
    if q:
        must.append(text_query(q, relaxed=relaxed))
    if params.get("pin"):
        filters.append({"prefix": {"pincode": params["pin"]}})
    if params.get("buyer"):
        filters.append({"term": {"buyer_id": int(params["buyer"])}})
    if params.get("source"):
        filters.append({"term": {"source": params["source"]}})
    if params.get("closes_before"):
        filters.append({"range": {"closes_at": {"lte": params["closes_before"]}}})
    if params.get("closes_after"):
        filters.append({"range": {"closes_at": {"gte": params["closes_after"]}}})
    return {"bool": {"must": must or [{"match_all": {}}], "filter": filters}}


def _facet_aggs(ff: dict[str, dict]) -> dict:
    """Disjunctive facets: each group is counted with every *other* group's filter
    applied, so after picking "Roads" the sector list still shows the other sectors."""
    inner = {
        "state": {"terms": {"field": "state", "size": 40}},
        "sector": {"terms": {"field": "sector", "size": 20}},
        "category": {"terms": {"field": "category", "size": 20}},
        "value_range": {"range": {"field": "value_inr", "ranges": VALUE_RANGES}},
    }
    aggs = {}
    for name, agg in inner.items():
        others = [f for k, f in ff.items() if k != name]
        aggs[name] = {"filter": {"bool": {"filter": others}}, "aggs": {"b": agg}}
    return aggs


def search(params: dict, *, page: int = 1, page_size: int = 20) -> dict:
    res = _search(params, page, page_size, relaxed=False)
    q = (params.get("q") or "").strip()
    if res["total"] == 0 and len(q.split()) > 1:
        res = _search(params, page, page_size, relaxed=True)
        res["relaxed"] = True
    return res


def _search(params: dict, page: int, page_size: int, *, relaxed: bool) -> dict:
    sort_by = params.get("sort") or "relevance"
    if sort_by == "newest":
        sort = [{"published_at": "desc"}]
    elif sort_by == "value":
        sort = [{"value_inr": {"order": "desc", "missing": "_last"}}, {"closes_at": "asc"}]
    elif sort_by == "closing" or not params.get("q"):
        sort = [{"closes_at": "asc"}]
    else:
        sort = [{"_score": "desc"}, {"closes_at": "asc"}]
    ff = facet_filters(params)
    resp = client().search(
        index=settings.ES_INDEX,
        query=build_query(params, relaxed=relaxed),
        post_filter={"bool": {"filter": list(ff.values())}},
        from_=(page - 1) * page_size,
        size=page_size,
        sort=sort,
        track_total_hits=True,
        source=False,
        aggs=_facet_aggs(ff),
    )
    aggs = resp["aggregations"]
    return {
        "total": resp["hits"]["total"]["value"],
        "ids": [int(h["_id"]) for h in resp["hits"]["hits"]],
        "relaxed": False,
        "facets": {
            name: [{"key": b["key"], "count": b["doc_count"]} for b in aggs[name]["b"]["buckets"]]
            for name in FACET_FIELDS
        },
    }
