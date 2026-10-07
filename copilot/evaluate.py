"""Evaluation harness (ported from DocIntel's evaluate.py), run by `manage.py copilot_eval`.

Retrieval (no LLM): for each answerable question, is a chunk holding the evidence in the top 5
(recall@5), and how high is the first one (MRR@10)? Compared across fts / dense / hybrid /
hybrid_rerank, both scoped (the question's own document, like asking from a tender page) and
global (every document; the question names the work, and a chunk only counts if it is the
right tender's: "Bid validity 90 days" appears in many notices).

Answers (--answers llm|extractive): exact match on the expected values, grounding rate,
abstention accuracy, and "confident wrong" answers, the number that matters most.

Bid Brief: per-field accuracy of the rule-based extractors against the same gold answers.

A chunk counts as relevant when it contains every evidence fragment after case and
whitespace normalisation, so the labels survive re-chunking.
"""

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from copilot import answer, grounding
from copilot.brief import document_fields
from copilot.retrieval import Filters, search

# Gold "fact" names in questions.jsonl -> Bid Brief keys.
FACT_TO_BRIEF = {
    "estimated_cost": "estimated_value",
    "fee": "tender_fee",
    "closing": "bid_submission_end",
    "completion": "completion_period",
    "validity": "bid_validity",
    "emd": "emd",
    "similar_works": "similar_work",
    "turnover": "min_turnover",
    "performance_guarantee": "performance_security",
    "liquidated_damages": "liquidated_damages",
    "prebid": "prebid_meeting",
}


def load_questions(path: Path, split: str | None = None) -> list[dict]:
    qs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [q for q in qs if split is None or q.get("split") == split]


def relevant(text: str, q: dict) -> bool:
    frags = q.get("evidence") or []
    if isinstance(frags, str):
        frags = [frags]
    t = grounding.norm(text)
    return bool(frags) and all(grounding.norm(f) in t for f in frags)


@dataclass
class RetrievalScores:
    mode: str
    scope: str
    n: int
    recall_at_5: float
    mrr_at_10: float
    ms_per_query: float


def eval_retrieval(
    questions: list[dict],
    doc_of: dict[str, int],
    org_id: int,
    modes: list[str],
    *,
    scoped: bool,
    model: str | None = None,
    reranker: str | None = None,
) -> list[RetrievalScores]:
    answerable = [q for q in questions if q["answerable"] and q["tender_id"] in doc_of]
    out = []
    for mode in modes:
        hit5 = rr = 0.0
        t0 = time.perf_counter()
        for q in answerable:
            doc_id = doc_of[q["tender_id"]]
            f = Filters(org_id, document_ids=[doc_id] if scoped else None)
            text = q["question"] if scoped else q.get("global_question", q["question"])
            hits = search(text, f, mode=mode, k=10, model=model, reranker=reranker or "")
            ranks = [
                i
                for i, h in enumerate(hits, start=1)
                if h.document_id == doc_id and relevant(h.text, q)
            ]
            if ranks and ranks[0] <= 5:
                hit5 += 1
            if ranks:
                rr += 1.0 / ranks[0]
        n = max(1, len(answerable))
        ms = (time.perf_counter() - t0) * 1000 / n
        out.append(RetrievalScores(mode, "scoped" if scoped else "global", n, hit5 / n, rr / n, ms))
    return out


def retrieval_table(scores: list[RetrievalScores]) -> str:
    lines = [
        "| Retriever | Scope | Recall@5 | MRR@10 | ms / query |",
        "|---|---|---:|---:|---:|",
    ]
    for s in scores:
        lines.append(
            f"| {s.mode} | {s.scope} | {s.recall_at_5:.1%} | {s.mrr_at_10:.3f} "
            f"| {s.ms_per_query:.0f} |"
        )
    return "\n".join(lines)


def eval_answers(questions, doc_of, org_id, *, use_llm: bool) -> dict:
    em = answered = grounded = correct_abstain = false_abstain = wrong = 0
    rows = []
    qs = [q for q in questions if q["tender_id"] in doc_of]
    t0 = time.perf_counter()
    for q in qs:
        final = answer.ask(
            q["question"], Filters(org_id, document_ids=[doc_of[q["tender_id"]]]), use_llm=use_llm
        )
        abstained = final["status"] != "answered"
        row = {"id": q["id"], "status": final["status"], "answer": final["answer"]}
        if q["answerable"]:
            if abstained:
                false_abstain += 1
            else:
                answered += 1
                ok = grounding.values_match(q["answer"], final["answer"])
                em += ok
                wrong += not ok
                grounded += final["grounding"] is not None and not final["grounding"]["unsupported"]
                row["correct"] = ok
        else:
            correct_abstain += abstained
            wrong += not abstained
        rows.append(row)
    n_ans = sum(q["answerable"] for q in qs)
    n = len(qs)
    return {
        "mode": "llm" if use_llm else "extractive",
        "n": n,
        "answerable": n_ans,
        "exact_match": em / n_ans if n_ans else None,
        "grounding_rate": grounded / answered if answered else None,
        "abstention_accuracy": (correct_abstain + n_ans - false_abstain) / n if n else None,
        "false_abstentions": false_abstain,
        "confident_wrong": wrong,
        "s_per_question": (time.perf_counter() - t0) / max(1, n),
        "rows": rows,
    }


def eval_brief(questions, docs_by_tender) -> dict:
    """Per-key accuracy of the Bid Brief against the gold answers. similar_work is scored on
    its amounts (its value is the whole clause)."""
    per_key: dict[str, list[int]] = {}
    for tid, doc in docs_by_tender.items():
        fields = document_fields(doc)
        for q in questions:
            key = FACT_TO_BRIEF.get(q.get("fact", ""))
            if q["tender_id"] != tid or not key or not q["answerable"]:
                continue
            f = fields.get(key)
            if f is None:
                ok = False
            elif key == "similar_work":
                want = {Decimal(x.value) for x in grounding.facts(q["answer"]) if x.kind == "money"}
                ok = want <= set(f.amounts)
            else:
                ok = grounding.values_match(q["answer"], f.value)
            per_key.setdefault(key, [0, 0])
            per_key[key][0] += ok
            per_key[key][1] += 1
    total = [sum(v[0] for v in per_key.values()), sum(v[1] for v in per_key.values())]
    return {"per_key": per_key, "correct": total[0], "total": total[1]}
