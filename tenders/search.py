"""Tender search on Postgres: full-text ranking, typo correction, ID lookup and facets.

The search document is the generated `tender.search_vector` column (migration
0004_postgres_search): title (stemmed and as written) and IDs weigh A, the buyer C,
location and organisation chain D. A query is matched in stages; the first that finds
anything answers:

  1. every word, websearch syntax ("quoted phrase", or, -not), each word a prefix
     ("constr" finds "construction") and stemmed ("toilets" finds "toilet"); an exact tender
     ID / reference number ranks first
  2. the same after correcting words that occur nowhere in the data ("toliet" -> "toilet"):
     nearest words of the `tender_word` list by pg_trgm distance, accepted within
     Elasticsearch's AUTO fuzziness (1 edit for 3-5 letters, 2 for longer words)
  3. a multi-word query: any one word (relaxed=True)

Ranking is ts_rank_cd with weights that make a title match outrank a buyer-name match, so
"maintenance" lists maintenance work before the Estate Maintenance Section's other tenders.
Facets are disjunctive: each group is counted with every *other* group's filter applied, so
after picking "Roads" the sector list still shows the other sectors.
"""

import re
from dataclasses import dataclass

from django.db import connection
from django.db.models import BooleanField, Count, F, FloatField, Q, QuerySet
from django.db.models.expressions import RawSQL
from django.utils import timezone

from tenders.models import Tender

VECTOR = "tender.search_vector"
# ts_rank_cd weights for labels {D, C, B, A}: location/org chain, buyer, -, title/IDs.
RANK = f"ts_rank_cd('{{0.05, 0.2, 0.4, 1.0}}'::float4[], {VECTOR}, %s::tsquery)"

# One user term (a word or a "quoted phrase") parsed and stemmed by websearch_to_tsquery,
# then every lexeme of it made a prefix match. The pattern matches a quoted lexeme in the
# tsquery's text form, where an embedded quote is doubled.
PREFIX_TERM = (
    r"regexp_replace(websearch_to_tsquery('english', %s)::text,"
    r" '''((?:[^'']|'''')+)''', '''\1'':*', 'g')::tsquery"
)
MAX_TERMS = 16

# (key, from, to): from inclusive, to exclusive, None open-ended. Values are INR.
VALUE_RANGES = [
    ("under_10_lakh", None, 1_000_000),
    ("10_lakh_to_1_crore", 1_000_000, 10_000_000),
    ("1_to_10_crore", 10_000_000, 100_000_000),
    ("over_10_crore", 100_000_000, None),
]
FACET_FIELDS = ("state", "sector", "category", "value_range")
# The request parameters that make up each facet group's own filter.
FACET_PARAMS = {
    "state": ("state",),
    "sector": ("sector",),
    "category": ("category",),
    "value_range": ("min_value", "max_value"),
}
FACET_SIZE = 40

ORDER = {
    "closing": ("closes_at", "id"),
    "newest": ("-published_at", "id"),
    "value": (F("value_inr").desc(nulls_last=True), "closes_at", "id"),
}


@dataclass(frozen=True)
class TextMatch:
    """How the text query was matched."""

    tsquery: str  # tsquery text; "" when the query has no searchable words
    exact: tuple[int, ...] = ()  # tenders whose ID / reference number equals the query
    relaxed: bool = False
    corrected: str | None = None  # the query after typo correction, when that was needed


# --- query parsing ----------------------------------------------------------------------

_TOKEN = re.compile(r'(-?)"([^"]*)"?|(\S+)')
_WORD = re.compile(r"[^\W\d_]+")


def parse(q: str) -> tuple[list[list[str]], list[str]]:
    """websearch syntax -> (clauses, negated terms). Every clause must match; a clause is
    one term or several joined by "or". Terms are words or quoted phrases (kept quoted so
    websearch_to_tsquery turns them into phrase queries)."""
    clauses: list[list[str]] = []
    negated: list[str] = []
    join_next = False
    for m in _TOKEN.finditer(q):
        neg, phrase, word = m.group(1), m.group(2), m.group(3)
        if phrase is not None:
            if not _WORD.search(phrase) and not any(c.isdigit() for c in phrase):
                continue
            term = f'"{phrase}"'
        elif word.lower() == "or":
            join_next = bool(clauses)
            continue
        elif word.startswith("-") and len(word) > 1:
            neg, term = "-", word[1:]
        else:
            term = word
        if neg:
            negated.append(term)
        elif join_next:
            clauses[-1].append(term)
        else:
            clauses.append([term])
        join_next = False
    return clauses, negated


def to_tsquery(clauses: list[list[str]], negated: list[str], *, relaxed: bool = False) -> str:
    """The tsquery (as text) for parsed terms. relaxed: any one positive term matches."""
    params: list[str] = []

    def term(t: str) -> str:
        params.append(t)
        return PREFIX_TERM

    budget = MAX_TERMS
    kept: list[list[str]] = []
    for clause in clauses:
        if budget <= 0:
            break
        kept.append(clause[:budget])
        budget -= len(kept[-1])
    if relaxed:
        alternatives = [t for clause in kept for t in clause]
        parts = ["(" + " || ".join(term(t) for t in alternatives) + ")"] if alternatives else []
    else:
        parts = ["(" + " || ".join(term(t) for t in clause) + ")" for clause in kept]
    parts += [f"!!({term(t)})" for t in negated[:4]]
    if not parts:
        return ""
    with connection.cursor() as cur:
        cur.execute(f"SELECT ({' && '.join(parts)})::text", params)
        return cur.fetchone()[0] or ""


def exact_ids(q: str) -> tuple[int, ...]:
    """Tenders whose tender ID or reference number is exactly the query (case-insensitive)."""
    q = q.strip().strip('"').strip()
    if len(q) < 3 or any(c.isspace() for c in q):
        return ()
    rows = Tender.objects.filter(Q(source_tender_id__iexact=q) | Q(ref_no__iexact=q))
    return tuple(rows.order_by("id").values_list("id", flat=True)[:20])


# --- typo correction --------------------------------------------------------------------

_CORRECT_SQL = """
WITH q(word) AS (SELECT DISTINCT unnest(%s::text[]))
SELECT q.word, (
    SELECT c.word FROM (
        SELECT w.word, w.ndoc FROM tender_word w ORDER BY w.word <-> q.word LIMIT 100
    ) c
    WHERE levenshtein_less_equal(c.word, q.word, 2)
          <= CASE WHEN length(q.word) >= 6 THEN 2 ELSE 1 END
    ORDER BY levenshtein_less_equal(c.word, q.word, 2), c.ndoc DESC, c.word
    LIMIT 1
)
FROM q
WHERE cardinality(ts_lexize('english_stem', q.word)) > 0  -- not a stop word
  -- unknown: no indexed word starts with it, or with its stem ("roads" -> "road")
  AND NOT EXISTS (
      SELECT 1 FROM tender_word w WHERE w.word >= q.word AND w.word < q.word || '{'
  )
  AND NOT EXISTS (
      SELECT 1 FROM tender_word w
      WHERE w.word >= (ts_lexize('english_stem', q.word))[1]
        AND w.word < (ts_lexize('english_stem', q.word))[1] || '{'
  )
"""


def correct(q: str) -> str:
    """q with each word that occurs nowhere in the data replaced by the closest word that
    does, if one is close enough. Only plain a-z words of 3+ letters are corrected."""
    words = sorted(
        {w.lower() for w in _WORD.findall(q) if len(w) >= 3 and w.isascii() and w.isalpha()}
        - {"or"}
    )
    if not words:
        return q
    with connection.cursor() as cur:
        cur.execute(_CORRECT_SQL, [words])
        fixes = {word: fix for word, fix in cur.fetchall() if fix}
    if not fixes:
        return q
    return _WORD.sub(lambda m: fixes.get(m.group(0).lower(), m.group(0)), q)


# --- querysets --------------------------------------------------------------------------


def _text_condition(text: TextMatch):
    if not text.tsquery and not text.exact:
        return Q(pk__in=[])
    sql, params = [], []
    if text.tsquery:
        sql.append(f"{VECTOR} @@ %s::tsquery")
        params.append(text.tsquery)
    if text.exact:
        sql.append("tender.id = ANY(%s)")
        params.append(list(text.exact))
    return RawSQL("(" + " OR ".join(sql) + ")", params, output_field=BooleanField())


def filtered(params: dict, text: TextMatch | None, *, skip: tuple[str, ...] = ()) -> QuerySet:
    """Tenders matching the text and every filter except the parameters in `skip`."""
    qs = Tender.objects.all()
    if text is not None:
        qs = qs.filter(_text_condition(text))
    for field in ("state", "sector", "category", "source"):
        if params.get(field) and field not in skip:
            qs = qs.filter(**{field: params[field]})
    if params.get("pin"):
        qs = qs.filter(pincode__startswith=params["pin"])
    if params.get("buyer"):
        qs = qs.filter(buyer_entity_id=params["buyer"])
    if params.get("min_value") is not None and "min_value" not in skip:
        qs = qs.filter(value_inr__gte=params["min_value"])
    if params.get("max_value") is not None and "max_value" not in skip:
        qs = qs.filter(value_inr__lte=params["max_value"])
    if params.get("closes_before"):
        qs = qs.filter(closes_at__lte=params["closes_before"])
    if params.get("closes_after"):
        qs = qs.filter(closes_at__gte=params["closes_after"])
    return qs


def ordered(qs: QuerySet, params: dict, text: TextMatch | None) -> QuerySet:
    sort = params.get("sort") or "relevance"
    if sort in ORDER:
        return qs.order_by(*ORDER[sort])
    if text is None or not (text.tsquery or text.exact):
        return qs.order_by(*ORDER["closing"])
    keys = []
    if text.exact:
        qs = qs.annotate(
            _exact=RawSQL("tender.id = ANY(%s)", [list(text.exact)], output_field=BooleanField())
        )
        keys.append(F("_exact").desc())
    if text.tsquery:
        qs = qs.annotate(_rank=RawSQL(RANK, [text.tsquery], output_field=FloatField()))
        keys.append("-_rank")
    return qs.order_by(*keys, "closes_at", "id")


def match(params: dict) -> TextMatch | None:
    """Pick the matching stage for params["q"] (see the module docstring); None without q."""
    q = (params.get("q") or "").strip()
    if not q:
        return None
    exact = exact_ids(q)
    clauses, negated = parse(q)
    strict = TextMatch(to_tsquery(clauses, negated), exact)
    if filtered(params, strict).exists():
        return strict

    fixed = correct(q)
    if fixed != q:
        clauses, negated = parse(fixed)
        text = TextMatch(to_tsquery(clauses, negated), exact, corrected=fixed)
        if filtered(params, text).exists():
            return text
    if sum(len(c) for c in clauses) > 1:
        return TextMatch(
            to_tsquery(clauses, negated, relaxed=True),
            exact,
            relaxed=True,
            corrected=fixed if fixed != q else None,
        )
    return strict


def queryset(params: dict) -> QuerySet:
    """Every tender search() would list, in the same order (for exports)."""
    text = match(params)
    return ordered(filtered(params, text), params, text).select_related("buyer_entity")


def facets(params: dict, text: TextMatch | None) -> dict[str, list[dict]]:
    def terms(field: str) -> list[dict]:
        qs = filtered(params, text, skip=FACET_PARAMS[field]).exclude(**{field: ""})
        rows = qs.values(field).annotate(n=Count("id")).order_by("-n", field)[:FACET_SIZE]
        return [{"key": r[field], "count": r["n"]} for r in rows]

    def in_range(lo, hi) -> Q:
        cond = Q(value_inr__isnull=False)
        if lo is not None:
            cond &= Q(value_inr__gte=lo)
        if hi is not None:
            cond &= Q(value_inr__lt=hi)
        return cond

    base = filtered(params, text, skip=FACET_PARAMS["value_range"])
    counts = base.aggregate(
        **{key: Count("id", filter=in_range(lo, hi)) for key, lo, hi in VALUE_RANGES}
    )
    return {
        "state": terms("state"),
        "sector": terms("sector"),
        "category": terms("category"),
        "value_range": [{"key": key, "count": counts[key]} for key, _, _ in VALUE_RANGES],
    }


def search(params: dict, *, page: int = 1, page_size: int = 20) -> dict:
    """One page of results plus facets.

    Returns {"total", "results": [Tender], "ids", "relaxed", "corrected", "facets"}.
    """
    text = match(params)
    qs = filtered(params, text)
    total = qs.count()
    start = (page - 1) * page_size
    rows = list(ordered(qs, params, text).select_related("buyer_entity")[start : start + page_size])
    return {
        "total": total,
        "results": rows,
        "ids": [t.pk for t in rows],
        "relaxed": bool(text and text.relaxed),
        "corrected": text.corrected if text else None,
        "facets": facets(params, text),
    }


def similar(tender: Tender, size: int = 6) -> list[Tender]:
    """Open tenders like this one: the same sector first, by title similarity (pg_trgm);
    then other sectors' tenders whose titles are similar enough (the `%` operator).

    Same sector first because the rare words of a title are often the buyer's name
    ("FACT Udyogamandal"), and "similar" would otherwise mean "same buyer, any work".
    """
    base = (
        Tender.objects.select_related("buyer_entity")
        .filter(closes_at__gte=timezone.now())
        .exclude(pk=tender.pk)
    )
    score = RawSQL("similarity(tender.title, %s)", [tender.title], output_field=FloatField())
    rows: list[Tender] = []
    if tender.sector and tender.sector != "other":
        same = base.filter(sector=tender.sector).annotate(_sim=score)
        rows = list(same.order_by("-_sim", "closes_at", "id")[:size])
    if len(rows) < size:
        alike = RawSQL("tender.title %% %s", [tender.title], output_field=BooleanField())
        others = base.exclude(pk__in=[r.pk for r in rows]).filter(alike).annotate(_sim=score)
        rows += list(others.order_by("-_sim", "closes_at", "id")[: size - len(rows)])
    return rows


def refresh_words() -> None:
    """Rebuild the word list typo correction draws from (after crawls add tenders)."""
    with connection.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY tender_word")
