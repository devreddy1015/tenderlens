"""Hybrid retrieval over document chunks, Postgres only.

    fts            full-text search (GIN over a generated tsvector), any-word query, ts_rank
    dense          pgvector cosine distance over e5 embeddings (HNSW, iterative scan)
    hybrid         Reciprocal Rank Fusion of fts top 50 and dense top 50, k = 60
    hybrid_rerank  hybrid top 30 -> cross-encoder (RERANKER_MODEL) -> top k

Full text catches exact tokens (tender IDs, clause numbers, "EMD") that embeddings blur;
embeddings catch paraphrases ("bid security" ~ "earnest money") that word matching misses.
RRF uses ranks only, so ts_rank scores and cosine distances never need a common scale.

Organisation scoping is not optional: every query joins the document table and filters on
organization_id, so one customer's documents can never appear in another's answers.
"""

from dataclasses import dataclass, field

from django.conf import settings
from django.db import connection, transaction

from copilot import embeddings

MODES = ("fts", "dense", "hybrid", "hybrid_rerank")
FTS_K = 50
DENSE_K = 50
RRF_K = 60
RERANK_CANDIDATES = 30
FINAL_K = 5
# ts_rank weights for labels {D, C, B, A}: -, chunk context (the tender's name), passage,
# heading. Within one tender's documents every chunk has the same context, so it cannot tell
# passages apart and is given no weight there; across documents it picks out the tender.
# Context as heavy as the passage measured best on the eval corpus (fts global recall@5:
# 0.2 -> 86.3%, 0.4 -> 93.4%, 1.0 -> 93.8% but MRR 0.731 -> 0.607).
GLOBAL_WEIGHTS = [0.1, 0.4, 0.4, 1.0]
SCOPED_WEIGHTS = [0.1, 0.0, 0.4, 1.0]


@dataclass
class Filters:
    organization_id: int
    tender_id: int | None = None
    document_ids: list[int] | None = None


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    filename: str
    tender_id: int | None
    page_from: int
    page_to: int
    heading: str
    text: str
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)
    # The document's context line (Chunk.context): for the reranker only, never quoted.
    context: str = ""


def _where(f: Filters) -> tuple[str, list]:
    if not f.organization_id:
        raise ValueError("retrieval must be scoped to an organisation")
    where, params = ["d.organization_id = %s", "d.status = 'ready'"], [f.organization_id]
    if f.tender_id is not None:
        where.append("d.tender_id = %s")
        params.append(f.tender_id)
    if f.document_ids is not None:
        where.append("d.id = ANY(%s)")
        params.append(list(f.document_ids))
    return " AND ".join(where), params


def fts(query: str, f: Filters, k: int = FTS_K) -> list[int]:
    """Any-word match (a question rarely has every word in one passage), ranked by ts_rank
    with length normalisation. plainto_tsquery stems and drops stop words; its '&' become '|'."""
    where, params = _where(f)
    weights = SCOPED_WEIGHTS if _scoped(f) else GLOBAL_WEIGHTS
    sql = f"""
        WITH q AS (SELECT replace(plainto_tsquery('english', %s)::text, ' & ', ' | ')::tsquery AS q)
        SELECT c.id FROM copilot_chunk c JOIN copilot_document d ON d.id = c.document_id, q
        WHERE {where} AND c.search_vector @@ q.q
        ORDER BY ts_rank(%s::float4[], c.search_vector, q.q, 1) DESC, c.id
        LIMIT %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [query, *params, weights, k])
        return [r[0] for r in cur.fetchall()]


def _vector_literal(vec) -> str:
    return "[" + ",".join(f"{float(x):.7g}" for x in vec) + "]"


def dense(query: str, f: Filters, k: int = DENSE_K, *, model: str | None = None) -> list[int]:
    where, params = _where(f)
    vec = _vector_literal(embeddings.embed_query(query, model))
    # relaxed_order lets the HNSW walk continue until k rows pass the filters (otherwise a
    # filtered search can return fewer than k); the materialised CTE restores exact order.
    sql = f"""
        WITH hits AS MATERIALIZED (
            SELECT c.id, c.embedding <=> %s::vector AS dist
            FROM copilot_chunk c JOIN copilot_document d ON d.id = c.document_id
            WHERE {where} AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
        )
        SELECT id FROM hits ORDER BY dist, id
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL hnsw.ef_search = 100")
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, [vec, *params, vec, k])
        return [r[0] for r in cur.fetchall()]


def rrf(*ranked_lists: list[int], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: score = sum over lists of 1 / (k + rank), rank from 1."""
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, cid in enumerate(lst, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def load_hits(ids: list[int], organization_id: int) -> dict[int, Hit]:
    if not ids:
        return {}
    sql = """
        SELECT c.id, c.document_id, d.filename, d.tender_id, c.page_from, c.page_to,
               c.heading, c.text, c.context
        FROM copilot_chunk c JOIN copilot_document d ON d.id = c.document_id
        WHERE c.id = ANY(%s) AND d.organization_id = %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [list(ids), organization_id])
        return {r[0]: Hit(*r[:8], context=r[8]) for r in cur.fetchall()}


def _rerank_text(h: Hit, *, scoped: bool) -> str:
    """Inside one tender the context is the same for every passage and only dilutes them
    (it cost the reranker 0.005 MRR scoped), so it is added for global questions only."""
    return "\n".join(p for p in (None if scoped else h.context, h.heading, h.text) if p)


def _scoped(f: Filters) -> bool:
    return f.tender_id is not None or bool(f.document_ids)


def search(
    query: str,
    filters: Filters,
    *,
    mode: str | None = None,
    k: int = FINAL_K,
    model: str | None = None,
    reranker: str | None = None,
) -> list[Hit]:
    """Top-k chunks for a question. The default mode is hybrid, or hybrid_rerank when a
    RERANKER_MODEL is configured."""
    reranker = reranker if reranker is not None else settings.RERANKER_MODEL
    mode = mode or ("hybrid_rerank" if reranker else "hybrid")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == "hybrid_rerank" and not reranker:
        raise ValueError("hybrid_rerank needs a reranker model (RERANKER_MODEL)")
    query = " ".join(query.split())[:1000]
    if not query:
        return []
    ranks: dict[int, dict[str, int]] = {}

    def note(name: str, lst: list[int]) -> None:
        for r, cid in enumerate(lst, start=1):
            ranks.setdefault(cid, {})[name] = r

    if mode == "fts":
        ids = fts(query, filters, max(k, FTS_K))
        note("fts", ids)
        scored = [(cid, 1.0 / r) for r, cid in enumerate(ids, start=1)]
    elif mode == "dense":
        ids = dense(query, filters, max(k, DENSE_K), model=model)
        note("dense", ids)
        scored = [(cid, 1.0 / r) for r, cid in enumerate(ids, start=1)]
    else:
        lexical, semantic = fts(query, filters), dense(query, filters, model=model)
        note("fts", lexical)
        note("dense", semantic)
        scored = rrf(lexical, semantic)

    if mode == "hybrid_rerank":
        cands = [cid for cid, _ in scored[:RERANK_CANDIDATES]]
        hits = load_hits(cands, filters.organization_id)
        cands = [c for c in cands if c in hits]
        rs = embeddings.rerank_scores(
            query, [_rerank_text(hits[c], scoped=_scoped(filters)) for c in cands], reranker
        )
        scored = sorted(zip(cands, rs, strict=True), key=lambda kv: -kv[1])
    else:
        hits = load_hits([cid for cid, _ in scored[:k]], filters.organization_id)

    out = []
    for cid, score in scored[:k]:
        if cid in hits:
            h = hits[cid]
            h.score, h.ranks = score, ranks.get(cid, {})
            out.append(h)
    return out
