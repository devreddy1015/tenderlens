"""Grounded answers: retrieve -> numbered passages -> self-hosted LLM -> [n] citations ->
grounding post-check -> answer or refusal. When the LLM is down, slow past its timeout or
erroring, the answer is EXTRACTIVE (the best-matching sentences of the top passages, cited)
instead of an error: a contractor reading "EMD: Rs. 22,316/- [1]" from the document itself
is better served than by a 500.

ask_events() yields the API's events in order: one "retrieval" (sent before the LLM is
called, so the UI shows the sources at once), "delta"s while the model writes (a draft the
final event may replace), then exactly one "final".
"""

import logging
import re
import time
from collections.abc import Iterator

from django.conf import settings

from copilot import grounding, llm
from copilot.prompt import ABSTAIN, build_messages, clean_answer, strip_think
from copilot.retrieval import Filters, Hit, search

log = logging.getLogger(__name__)

STATUSES = ("answered", "abstained", "rejected", "no_context", "error")


def page_label(h: Hit) -> str:
    return str(h.page_from) if h.page_from == h.page_to else f"{h.page_from}-{h.page_to}"


def passages(hits: list[Hit]) -> list[dict]:
    return [
        {
            "n": i,
            "document_id": h.document_id,
            "filename": h.filename,
            "page": h.page_from,
            "text": h.text,
        }
        for i, h in enumerate(hits, start=1)
    ]


# --- sentences and word matching ------------------------------------------------------

_JOIN_WRAPPED = re.compile(r"(?<![.:;!?।])\n(?=[a-z(])")
_UNIT_SPLIT = re.compile(r"\n+|(?<=[.;!?।])\s+(?=[A-Z(ऀ-ॿ])")
_ABBREV_END = re.compile(r"\b(?:Rs|No|Nos|Sl|S|p|pp|Dr|Mr|Ms|Smt|Shri|viz|Cl)\.$", re.I)
_WORD = re.compile(r"[a-z0-9ऀ-ॿ]+")
STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "many",
        "much",
        "of",
        "on",
        "or",
        "should",
        "shall",
        "the",
        "there",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "within",
        "must",
        "be",
        "any",
        "our",
        "we",
        "you",
        "your",
        "tender",
        "document",
        "documents",
        "per",
    ]
)
# Prompt rule 4's synonyms, for matching without a model.
SYNONYMS = [
    {"emd", "earnest", "bid security"},
    {"tender fee", "cost of tender", "document fee", "fee"},
    {"performance guarantee", "performance security", "performance bank guarantee"},
    {"liquidated damages", "compensation", "delay", "penalty"},
    {"completion", "time allowed", "period of completion", "finish", "how long", "duration"},
    {"turnover", "financial turnover"},
    {"similar work", "similar works", "experience", "similar completed"},
    {"validity", "valid"},
    {"pre-bid", "prebid", "pre bid"},
    {"submission", "last date", "closing", "submitted"},
    {"estimated", "value", "cost"},
]
_VALUE_QUESTION = re.compile(
    r"\b(how much|how many|how long|amount|value|cost|fee|percent|percentage|rate|date|when|"
    r"deadline|last date|period|days|months|turnover|emd|deposit|guarantee|security)\b",
    re.I,
)


def units(text: str) -> list[str]:
    """Sentences, or table rows: lines are joined where a sentence wraps, then split at
    line and sentence ends ("Rs. 5" never splits)."""
    out: list[str] = []
    for part in _UNIT_SPLIT.split(_JOIN_WRAPPED.sub(" ", text)):
        part = " ".join(part.split())
        if not part:
            continue
        if out and _ABBREV_END.search(out[-1]):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _stem(word: str) -> str:
    return word[:6] if len(word) > 6 else word.rstrip("s")


def terms(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1}


def _expand(question: str) -> set[str]:
    q = question.lower()
    out = terms(q)
    for group in SYNONYMS:
        if any(s in q for s in group):
            for s in group:
                out |= terms(s)
    return out


# --- extractive answers ---------------------------------------------------------------


def extractive(question: str, hits: list[Hit], *, max_sentences: int = 2) -> tuple[str, list]:
    """The best-matching sentences of the top passages, each with its [n]. Returns
    (answer, [(n, sentence)]) or (ABSTAIN, []) when nothing matches well enough."""
    want = _expand(question)
    if not want:
        return ABSTAIN, []
    wants_value = bool(_VALUE_QUESTION.search(question))
    scored = []
    for n, h in enumerate(hits[:3], start=1):
        for s in units(h.text):
            if len(s) < 12:
                continue
            overlap = len(want & terms(s))
            if not overlap:
                continue
            score = overlap + (1.0 if wants_value and grounding.facts(s) else 0.0)
            score -= 0.15 * (n - 1) + 0.002 * max(0, len(s) - 250)
            # A table row ("Period of completion 9 months") ranks first, but the bonus does
            # not count towards the threshold, so it cannot turn an abstention into an answer.
            row_bonus = 0.5 if len(s) < 90 else 0.0
            scored.append((score + row_bonus, score, n, s))
    scored.sort(key=lambda t: -t[0])
    if not scored or max(t[1] for t in scored) < 1.5:
        return ABSTAIN, []
    best = scored[0][0]
    picked: list[tuple[int, str]] = []
    for score, _, n, s in scored:
        if len(picked) == max_sentences or score < 0.75 * best:
            break
        if all(s != p for _, p in picked):
            picked.append((n, s[:400]))
    text = " ".join(
        f"{s.rstrip('.')}. [{n}]" if not s.endswith(".") else f"{s} [{n}]" for n, s in picked
    )
    return text, picked


# --- citations ------------------------------------------------------------------------


def best_quote(passage: str, claim: str) -> str:
    """The passage sentence that best supports `claim`: shared values first, then words."""
    want_values, want_terms = grounding.values(claim), terms(claim)
    best, best_score = "", -1.0
    for s in units(passage):
        score = 3 * len(want_values & grounding.values(s)) + len(want_terms & terms(s))
        if score > best_score:
            best, best_score = s, score
    return best[:300]


def citations_for(answer: str, hits: list[Hit]) -> list[dict]:
    claims: dict[int, list[str]] = {}
    for s in grounding.sentences(answer):
        for n in grounding.cited_numbers(s):
            claims.setdefault(n, []).append(s)
    out = []
    for n, sents in claims.items():
        if 1 <= n <= len(hits):
            h = hits[n - 1]
            out.append(
                {
                    "n": n,
                    "document_id": h.document_id,
                    "filename": h.filename,
                    "page": h.page_from,
                    "quote": best_quote(h.text, " ".join(sents)),
                }
            )
    return out


# --- the pipeline ---------------------------------------------------------------------


def _final(status: str, answer: str, t0: float, **kw) -> dict:
    return {
        "type": "final",
        "status": status,
        "answer": answer,
        "citations": kw.get("citations", []),
        "grounding": kw.get("grounding"),
        "model": kw.get("model", ""),
        "mode": kw.get("mode", "llm"),
        "latency_ms": round((time.monotonic() - t0) * 1000),
    }


def judge(question: str, text: str, hits: list[Hit], t0: float, model: str) -> dict:
    """Turn the model's raw text into the final event: abstention, grounded answer, or a
    rejection when a value is not in the passages it cites (or nothing is cited)."""
    text = clean_answer(text)
    if text == ABSTAIN:
        return _final("abstained", ABSTAIN, t0, model=model)
    numbered = {i: h.text for i, h in enumerate(hits, start=1)}
    rep = grounding.check(text, numbered)
    unsupported = [*rep.unsupported, *rep.uncited_claims]
    unsupported += [f"[{n}]" for n in rep.invalid_citations]
    valid = [n for n in rep.citations if n in numbered]
    if not rep.ok or not valid:
        log.warning("copilot: answer rejected by the grounding check: %s", unsupported)
        if not valid and not unsupported:
            unsupported = ["no citation"]
        return _final("rejected", ABSTAIN, t0, grounding={"unsupported": unsupported}, model=model)
    return _final(
        "answered",
        text,
        t0,
        citations=citations_for(text, hits),
        grounding={"unsupported": []},
        model=model,
    )


def extractive_final(question: str, hits: list[Hit], t0: float) -> dict:
    text, picked = extractive(question, hits)
    if not picked:
        return _final("abstained", ABSTAIN, t0, mode="extractive")
    return _final(
        "answered",
        text,
        t0,
        citations=citations_for(text, hits),
        grounding={"unsupported": []},
        mode="extractive",
    )


def ask_events(question: str, filters: Filters, *, use_llm: bool = True) -> Iterator[dict]:
    t0 = time.monotonic()
    try:
        hits = search(question, filters)
    except Exception:
        log.exception("copilot: retrieval failed")
        yield {"type": "retrieval", "passages": []}
        yield _final("error", "Search over your documents failed. Please try again.", t0)
        return
    yield {"type": "retrieval", "passages": passages(hits)}
    if not hits:
        yield _final("no_context", ABSTAIN, t0, mode="extractive")
        return
    if not use_llm:
        yield extractive_final(question, hits, t0)
        return

    messages = build_messages(
        question,
        [{"filename": h.filename, "page": page_label(h), "text": h.text} for h in hits],
    )
    full, sent = "", ""
    try:
        for delta in llm.stream_chat(messages):
            full += delta
            visible = strip_think(full)
            if visible.startswith(sent) and len(visible) > len(sent):
                yield {"type": "delta", "text": visible[len(sent) :]}
                sent = visible
    except llm.LLMUnavailable as exc:
        log.warning("copilot: LLM unavailable (%s); answering extractively", exc)
        yield extractive_final(question, hits, t0)
        return
    if not strip_think(full):  # an empty reply (e.g. all thinking, cut off): use the passages
        yield extractive_final(question, hits, t0)
        return
    yield judge(question, full, hits, t0, settings.LLM_MODEL)


def ask(question: str, filters: Filters, **kw) -> dict:
    """The final event only (for ?stream=false and the evaluation)."""
    final = None
    for ev in ask_events(question, filters, **kw):
        if ev["type"] == "final":
            final = ev
    return final
