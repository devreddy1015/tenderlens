"""Build the chat-format fine-tuning set for the tender copilot LLM.

    uv run python build_dataset.py                          # templates only, seconds
    uv run python build_dataset.py --extra-pdf-dir ~/tenders   # + real PDFs (rule-extracted)
    uv run python build_dataset.py --teacher http://gpu-box:8000/v1 --teacher-model qwen3-32b

Every example is exactly what the copilot sends in production (prompt.py's system prompt, the
numbered passages, the question) plus the answer we want: one short sentence per fact, each
ending with the [n] of the passage that states it, values copied verbatim, or the exact
abstention sentence. Sources:

  labelled   DocIntel's eval facts for the TRAIN tenders, asked with the training wording
             (`train_question` and paraphrases, never the eval wording) in English and Hindi;
  rules      for tenders without labels (real PDFs), values a regex finds next to their
             anchor phrase ("Earnest Money ... Rs. 45,717/-");
  abstain    the same questions with every passage holding the answer removed (on-topic
             distractors), plus DocIntel's unanswerable questions: the reply is ABSTAIN;
  partial    two-fact questions where one fact is missing: answer one, name the other.

Every answer, template or teacher, must pass grounding.check (each number/date appears in a
passage it cites) or it is dropped. Splits are BY TENDER: the eval's test tenders are never
used, and a slice of the training tenders is held out as validation.
Output: out/dataset/{train,val}.jsonl ({"messages": [...], "meta": {...}}) and stats.json.
"""

import argparse
import hashlib
import json
import os
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx

from corpus import (
    DEFAULT_EVAL_DIR,
    DEFAULT_PDF_DIR,
    Chunk,
    Tender,
    bm25_rank,
    contains_evidence,
    load_questions,
    load_tenders,
)
from grounding import check, values_match
from prompt import (
    ABSTAIN,
    REQUEST_PARAMS,
    SYSTEM_PROMPT,
    build_messages,
    clean_answer,
    is_abstention,
)

HERE = Path(__file__).resolve().parent

# --- question and answer templates ------------------------------------------------------
# label_en/label_hi name the fact in a sentence; q_en/q_hi are the training wordings (the eval
# wording in questions.jsonl["question"] is deliberately absent); a_en/a_hi the answer, with
# {v} the value exactly as the document writes it and {c} the citation.


@dataclass(frozen=True)
class Fact:
    label_en: str
    label_hi: str
    q_en: tuple[str, ...]
    q_hi: tuple[str, ...]
    a_en: str
    a_hi: str


FACTS: dict[str, Fact] = {
    "estimated_cost": Fact(
        "estimated cost",
        "अनुमानित लागत",
        (
            "What is the estimated cost put to tender?",
            "What is the tender's estimated cost?",
            "Estimated value of this work?",
        ),
        ("इस निविदा की अनुमानित लागत क्या है?", "कार्य की अनुमानित लागत कितनी है?"),
        "The estimated cost put to tender is {v} {c}.",
        "निविदा की अनुमानित लागत {v} है {c}।",
    ),
    "fee": Fact(
        "tender fee",
        "निविदा शुल्क",
        (
            "What is the non-refundable tender fee?",
            "How much is the tender fee?",
            "What do I pay for the tender document?",
        ),
        ("निविदा शुल्क कितना है?", "टेंडर फीस कितनी देनी होगी?"),
        "The tender fee is {v} {c}.",
        "निविदा शुल्क {v} है {c}।",
    ),
    "closing": Fact(
        "last date for bid submission",
        "बोली जमा करने की अंतिम तिथि",
        (
            "What is the last date for bid submission?",
            "By when must bids be submitted?",
            "Bid submission deadline?",
        ),
        ("बोली जमा करने की अंतिम तिथि क्या है?", "टेंडर जमा करने की आखिरी तारीख क्या है?"),
        "The last date for bid submission is {v} {c}.",
        "बोली जमा करने की अंतिम तिथि {v} है {c}।",
    ),
    "completion": Fact(
        "period of completion",
        "कार्य पूरा करने की अवधि",
        (
            "What is the period of completion?",
            "How long is allowed to complete the work?",
            "What is the time allowed for the work?",
        ),
        ("कार्य पूरा करने की अवधि क्या है?", "काम कितने समय में पूरा करना है?"),
        "The period of completion is {v} {c}.",
        "कार्य पूरा करने की अवधि {v} है {c}।",
    ),
    "validity": Fact(
        "bid validity period",
        "बोली की वैधता अवधि",
        (
            "What is the bid validity period?",
            "For how long must the bid remain valid?",
            "How many days are bids valid?",
        ),
        ("बोली की वैधता अवधि क्या है?", "बोली कितने दिनों तक वैध रहनी चाहिए?"),
        "Bids must remain valid for {v} {c}.",
        "बोली {v} तक वैध रहनी चाहिए {c}।",
    ),
    "emd": Fact(
        "EMD",
        "बयाना राशि (EMD)",
        (
            "What is the EMD amount?",
            "How much earnest money do I need to deposit?",
            "EMD for this tender?",
        ),
        ("बयाना राशि (EMD) कितनी है?", "इस टेंडर में ईएमडी कितनी जमा करनी होगी?"),
        "The EMD (earnest money deposit) is {v} {c}.",
        "बयाना राशि (EMD) {v} है {c}।",
    ),
    "similar_works": Fact(
        "similar works experience",
        "समान कार्यों के अनुभव की शर्त",
        (
            "What similar works experience is required?",
            "What past work must a bidder have done?",
            "Which similar completed works qualify a bidder?",
        ),
        ("समान कार्यों का कितना अनुभव चाहिए?", "बोलीदाता के पास किस तरह के पूर्ण कार्य होने चाहिए?"),
        "The bidder must have completed {v} {c}.",
        "बोलीदाता ने {v} पूरे किए हों {c}।",
    ),
    "turnover": Fact(
        "required average annual turnover",
        "आवश्यक औसत वार्षिक टर्नओवर",
        (
            "What is the required average annual turnover?",
            "What turnover must the bidder show?",
            "Minimum annual financial turnover needed?",
        ),
        ("न्यूनतम औसत वार्षिक टर्नओवर कितना होना चाहिए?", "बोलीदाता का टर्नओवर कितना होना चाहिए?"),
        "The required average annual financial turnover is {v} {c}.",
        "आवश्यक औसत वार्षिक वित्तीय टर्नओवर {v} है {c}।",
    ),
    "performance_guarantee": Fact(
        "performance guarantee",
        "परफॉर्मेंस गारंटी",
        (
            "What percentage is the performance guarantee?",
            "How much performance security is needed?",
            "What is the performance guarantee amount?",
        ),
        ("परफॉर्मेंस गारंटी कितनी देनी होगी?", "कार्य निष्पादन प्रतिभूति कितने प्रतिशत है?"),
        "The performance guarantee is {v} {c}.",
        "परफॉर्मेंस गारंटी {v} है {c}।",
    ),
    "security_deposit": Fact(
        "security deposit rate",
        "सिक्योरिटी डिपॉजिट की दर",
        (
            "What is the security deposit rate?",
            "How much security deposit is deducted?",
            "What is deducted from bills as security deposit?",
        ),
        ("सिक्योरिटी डिपॉजिट कितना काटा जाएगा?", "प्रतिभूति जमा की दर क्या है?"),
        "The security deposit is recovered at {v} {c}.",
        "सिक्योरिटी डिपॉजिट {v} की दर से काटा जाएगा {c}।",
    ),
    "defect_liability": Fact(
        "defect liability period",
        "दोष दायित्व अवधि",
        (
            "After how many months is the security deposit refunded?",
            "What is the defect liability period?",
            "How long is the defect liability period?",
        ),
        ("दोष दायित्व अवधि कितनी है?", "सिक्योरिटी डिपॉजिट कितने महीने बाद लौटाया जाएगा?"),
        "The defect liability period is {v} {c}.",
        "दोष दायित्व अवधि {v} है {c}।",
    ),
    "liquidated_damages": Fact(
        "compensation for delay",
        "देरी के लिए मुआवज़ा",
        (
            "What is the compensation for delay?",
            "What are the liquidated damages for late completion?",
            "What penalty applies if the work is delayed?",
        ),
        ("काम में देरी पर कितना जुर्माना है?", "देरी के लिए मुआवज़े की दर क्या है?"),
        "Compensation for delay is {v} {c}.",
        "देरी के लिए मुआवज़ा {v} है {c}।",
    ),
    "prebid": Fact(
        "pre-bid meeting date",
        "प्री-बिड बैठक की तिथि",
        (
            "What is the date of the pre-bid meeting?",
            "When is the pre-bid meeting?",
            "Pre-bid meeting date?",
        ),
        ("प्री-बिड बैठक कब है?", "प्री-बिड मीटिंग की तारीख क्या है?"),
        "The pre-bid meeting is on {v} {c}.",
        "प्री-बिड बैठक {v} को है {c}।",
    ),
    "advance": Fact(
        "mobilisation advance",
        "मोबिलाइज़ेशन अग्रिम",
        (
            "How much mobilisation advance can be given?",
            "Is any mobilisation advance allowed?",
            "What advance is paid to the contractor?",
        ),
        ("मोबिलाइज़ेशन अग्रिम कितना मिल सकता है?", "ठेकेदार को कितना अग्रिम दिया जाता है?"),
        "Mobilisation advance can be given {v} {c}.",
        "मोबिलाइज़ेशन अग्रिम {v} तक दिया जा सकता है {c}।",
    ),
    "officer": Fact(
        "officer inviting bids",
        "बोलियाँ आमंत्रित करने वाला अधिकारी",
        (
            "Who is the officer inviting tender?",
            "Who has invited these bids?",
            "Which authority issued this tender notice?",
        ),
        ("बोलियाँ कौन आमंत्रित कर रहा है?", "यह निविदा किस अधिकारी ने जारी की है?"),
        "The bids are invited by {v} {c}.",
        "बोलियाँ {v} द्वारा आमंत्रित की गई हैं {c}।",
    ),
}

# Hindi answers for values that are phrases, not amounts: keep the document's English words
# (rule 6: amounts and dates as written), only the frame is Hindi.
PARTIAL_EN = "The documents do not mention the {label}."
PARTIAL_HI = "दस्तावेज़ों में {label} का उल्लेख नहीं है।"

# --- rule extraction for unlabelled tenders (real PDFs) ----------------------------------
_RS = r"(Rs\.?\s*[\d,]+(?:\.\d+)?\s*/-|₹\s*[\d,]+(?:\.\d+)?(?:\s*/-)?)"
_DATE = r"(\d{1,2}[-./](?:\d{1,2}|[A-Z][a-z]{2})[-./]\d{4}(?:\s+\d{1,2}[:.]\d{2}(?:\s*[AP]M)?)?)"
RULES: dict[str, tuple[str, re.Pattern]] = {
    "emd": (
        "earnest money",
        re.compile(r"(?:earnest money(?: deposit)?|\bEMD\b|bid security)[^.\n]{0,80}?" + _RS, re.I),
    ),
    "fee": (
        "fee",
        re.compile(r"(?:tender|document|bid) (?:document )?(?:fee|cost)[^.\n]{0,60}?" + _RS, re.I),
    ),
    "estimated_cost": (
        "estimated",
        re.compile(r"estimated (?:cost|value)[^.\n]{0,80}?" + _RS, re.I),
    ),
    "completion": (
        "completion",
        re.compile(
            r"(?:period of completion|completion period|time allowed)[^.\n]{0,50}?(\d+\s*(?:months?|days))",
            re.I,
        ),
    ),
    "validity": ("valid", re.compile(r"valid(?:ity)?[^.\n]{0,40}?(\d+\s*days)", re.I)),
    "closing": (
        "last date",
        re.compile(r"(?:last date|bid submission end date)[^\n]{0,80}?" + _DATE, re.I),
    ),
}


def rule_facts(chunks: list[Chunk]) -> dict[str, tuple[str, str]]:
    """fact -> (value, anchor) for the first chunk where the rule fires; one value per fact,
    and only when every match in the tender agrees (a corrigendum changing the EMD is skipped)."""
    out: dict[str, tuple[str, str]] = {}
    for fact, (anchor, rx) in RULES.items():
        vals = {" ".join(m.group(1).split()) for c in chunks for m in rx.finditer(c.text)}
        if len(vals) == 1:
            out[fact] = (vals.pop(), anchor)
    return out


# --- example assembly ---------------------------------------------------------------------


def est_tokens(messages: list[dict]) -> int:
    """Conservative token estimate (Qwen tokenizer: ~3.5 chars/token for English tender text,
    fewer for Devanagari); train_qlora.py measures exactly and drops what still overflows."""
    text = "".join(m["content"] for m in messages)
    return int(max(len(text.split()) * 1.3, len(text) / 3.2)) + 12 * len(messages)


def pick_passages(
    rng: random.Random,
    chunks: list[Chunk],
    rank_query: str,
    gold: list[int],
    k: int,
    exclude: set[int] = frozenset(),
) -> tuple[list[Chunk], list[int]]:
    """Top-k by BM25 like production; gold chunks forced in (at a random slot when BM25
    missed them, so the model learns to find the answer anywhere, not just at [1])."""
    order = [i for i in bm25_rank(chunks, rank_query) if i not in exclude]
    top = order[:k]
    for g in gold:
        if g in top:
            continue
        free = [j for j, i in enumerate(top) if i not in gold]
        if len(top) < k or not free:
            top.insert(rng.randrange(len(top) + 1), g)
        else:
            top[rng.choice(free)] = g
    # BM25 usually ranks the answer first; production's fused ranking often does not. Half the
    # examples are shuffled so the model reads every passage instead of learning "cite [1]".
    if rng.random() < 0.5:
        rng.shuffle(top)
    return [chunks[i] for i in top], [n for n, i in enumerate(top, 1) if i in gold]


def fit(messages_fn, passages: list[Chunk], keep: set[int], max_tokens: int):
    """Drop non-gold passages from the end until the example fits max_tokens (min 2)."""
    ps = list(passages)
    while True:
        msgs = messages_fn(ps)
        if est_tokens(msgs) <= max_tokens or len(ps) <= 2:
            return msgs, ps
        drop = next((j for j in range(len(ps) - 1, -1, -1) if id(ps[j]) not in keep), None)
        if drop is None:
            return msgs, ps
        ps.pop(drop)


def cite(ns: list[int]) -> str:
    return "".join(f"[{n}]" for n in ns)


class Teacher:
    """Any OpenAI-compatible endpoint; its answer replaces the template only when it passes
    the same checks the template does (grounded, cites a gold passage, right value)."""

    def __init__(self, base_url: str, model: str, api_key: str | None):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.url, self.model = base_url.rstrip("/") + "/chat/completions", model
        self.http = httpx.Client(timeout=600, headers=headers)

    def answer(self, messages: list[dict]) -> str | None:
        body = {"model": self.model, "messages": messages[:2], **REQUEST_PARAMS}
        try:
            r = self.http.post(self.url, json=body)
            r.raise_for_status()
            return clean_answer(r.json()["choices"][0]["message"].get("content") or "")
        except (httpx.HTTPError, KeyError, IndexError):
            return None


def acceptable(
    answer: str, passages: list[Chunk], gold_n: list[int], expected: list[str] | None
) -> bool:
    """expected None = must abstain; else each expected value must appear, grounded in a cited
    gold passage, every sentence cited."""
    if expected is None:
        return answer.strip() == ABSTAIN
    if is_abstention(answer):
        return False
    rep = check(answer, {n: c.text for n, c in enumerate(passages, 1)})
    if not (rep.ok and rep.citations and set(rep.citations) & set(gold_n)):
        return False
    return all(values_match(v, answer) for v in expected)


@dataclass
class Builder:
    rng: random.Random
    k: int
    max_tokens: int
    hindi_share: float
    teacher: Teacher | None
    stats: Counter

    def emit(
        self,
        out: list,
        tender: Tender,
        chunks,
        question,
        rank_query,
        gold,
        answer_fn,
        expected,
        meta,
        exclude=frozenset(),
    ):
        passages, _ = pick_passages(self.rng, chunks, rank_query, gold, self.k, set(exclude))
        gold_ids = {id(chunks[g]) for g in gold}

        def mk(ps):
            return build_messages(question, [c.passage for c in ps])

        msgs, passages = fit(mk, passages, gold_ids, self.max_tokens)
        gold_n = [n for n, c in enumerate(passages, 1) if id(c) in gold_ids]
        # in the order of `gold` (one per fact), so a two-fact answer cites each fact's passage
        by_fact = [n for g in gold for n, c in enumerate(passages, 1) if c is chunks[g]]
        answer = answer_fn(by_fact)
        if not acceptable(answer, passages, gold_n, expected):
            self.stats[f"dropped_failed_check:{meta['kind']}:{meta['fact'].split('+')[0]}"] += 1
            return
        source = "template"
        if self.teacher:
            t = self.teacher.answer(msgs)
            if t and acceptable(t, passages, gold_n, expected):
                answer, source = t, "teacher"
            else:
                self.stats["teacher_rejected"] += 1
        msgs = [*msgs, {"role": "assistant", "content": answer}]
        meta = {
            **meta,
            "tender_id": tender.tender_id,
            "source": source,
            "passages": len(passages),
            "est_tokens": est_tokens(msgs),
        }
        out.append({"messages": msgs, "meta": meta})
        self.stats[f"kind:{meta['kind']}"] += 1
        self.stats[f"lang:{meta['lang']}"] += 1


def tender_examples(
    b: Builder, tender: Tender, labels: dict[str, dict], unanswerable: list[dict]
) -> list:
    chunks = tender.chunks()
    out: list = []
    if not chunks:
        return out
    # fact -> (value as written, evidence fragments)
    known: dict[str, tuple[str, list[str]]] = {}
    for fact, q in labels.items():
        known[fact] = (q["answer"], q["evidence"])
    if not labels:
        for fact, (v, anchor) in rule_facts(chunks).items():
            known[fact] = (v, [anchor, v])
    gold_of = {
        fact: [i for i, c in enumerate(chunks) if contains_evidence(c.text, ev)]
        for fact, (_, ev) in known.items()
    }
    for fact, (value, _ev) in known.items():
        spec, gold = FACTS.get(fact), gold_of[fact]
        if not spec or not gold:
            b.stats["no_gold_chunk"] += 1
            continue
        gold = gold[:1]  # the first statement; a second copy may be a summary table
        src = "labelled" if labels else "rules"
        rank_q = spec.q_en[0]
        for q in spec.q_en:
            b.emit(
                out,
                tender,
                chunks,
                q,
                q,
                gold,
                lambda ns, v=value, s=spec: s.a_en.format(v=v, c=cite(ns[:1])),
                [value],
                {"kind": "answer", "fact": fact, "lang": "en", "from": src},
            )
        for q in spec.q_hi:
            if b.rng.random() < b.hindi_share * 2:
                b.emit(
                    out,
                    tender,
                    chunks,
                    q,
                    rank_q,
                    gold,
                    lambda ns, v=value, s=spec: s.a_hi.format(v=v, c=cite(ns[:1])),
                    [value],
                    {"kind": "answer", "fact": fact, "lang": "hi", "from": src},
                )
        # abstention: every chunk that holds the value or the evidence is removed
        holders = {
            i for i, c in enumerate(chunks) if values_match(value, c.text) or i in gold_of[fact]
        }
        if len(chunks) - len(holders) >= 2 and b.rng.random() < 0.6:
            hi = b.rng.random() < b.hindi_share
            q = b.rng.choice(spec.q_hi if hi else spec.q_en)
            b.emit(
                out,
                tender,
                chunks,
                q,
                rank_q,
                [],
                lambda ns: ABSTAIN,
                None,
                {
                    "kind": "abstain_distractor",
                    "fact": fact,
                    "lang": "hi" if hi else "en",
                    "from": src,
                },
                exclude=holders,
            )
    # two facts in one question, both present / one missing
    facts = [f for f in known if FACTS.get(f) and gold_of[f]]
    b.rng.shuffle(facts)
    for f1, f2 in zip(facts[::2], facts[1::2], strict=False):
        s1, s2 = FACTS[f1], FACTS[f2]
        v1, v2 = known[f1][0], known[f2][0]
        g1, g2 = gold_of[f1][:1], gold_of[f2][:1]
        q = f"What are the {s1.label_en} and the {s2.label_en}?"
        if g1 != g2:
            b.emit(
                out,
                tender,
                chunks,
                q,
                q,
                g1 + g2,
                lambda ns, a=s1, b_=s2, x=v1, y=v2: (
                    (
                        a.a_en.format(v=x, c=cite(ns[:1]))
                        + " "
                        + b_.a_en.format(v=y, c=cite(ns[-1:]))
                    )
                    if len(ns) == 2
                    else ""
                ),
                [v1, v2],
                {"kind": "answer_two", "fact": f"{f1}+{f2}", "lang": "en", "from": "labelled"},
            )
        holders2 = {i for i, c in enumerate(chunks) if values_match(v2, c.text) or i in gold_of[f2]}
        if g1[0] not in holders2:
            b.emit(
                out,
                tender,
                chunks,
                q,
                q,
                g1,
                lambda ns, a=s1, b_=s2, x=v1: (
                    a.a_en.format(v=x, c=cite(ns[:1])) + " " + PARTIAL_EN.format(label=b_.label_en)
                ),
                [v1],
                {"kind": "partial", "fact": f"{f1}+{f2}", "lang": "en", "from": "labelled"},
                exclude=holders2,
            )
    for q in unanswerable:
        b.emit(
            out,
            tender,
            chunks,
            q["question"],
            q["question"],
            [],
            lambda ns: ABSTAIN,
            None,
            {"kind": "abstain_unanswerable", "fact": "none", "lang": "en", "from": "labelled"},
        )
    return out


def val_tenders(tender_ids: list[str], share: float) -> set[str]:
    """A fixed, hash-ordered slice of the training tenders (at least one)."""
    ranked = sorted(tender_ids, key=lambda t: hashlib.sha256(t.encode()).hexdigest())
    return set(ranked[: max(1, round(share * len(ranked)))])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    ap.add_argument(
        "--extra-pdf-dir",
        type=Path,
        action="append",
        default=[],
        help="more tender PDFs (one folder per tender); facts by rules, split by hash",
    )
    ap.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    ap.add_argument("--out", type=Path, default=HERE / "out" / "dataset")
    ap.add_argument("--k", type=int, default=4, help="passages per example before fitting")
    ap.add_argument(
        "--max-tokens", type=int, default=1900, help="fit under the 2048 training window"
    )
    ap.add_argument("--hindi-share", type=float, default=0.3)
    ap.add_argument("--val-share", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--teacher", help="OpenAI-compatible base URL of a stronger model")
    ap.add_argument("--teacher-model", default="default")
    ap.add_argument("--teacher-key-env", default="TEACHER_API_KEY")
    a = ap.parse_args()

    rng = random.Random(a.seed)
    teacher = (
        Teacher(a.teacher, a.teacher_model, os.environ.get(a.teacher_key_env))
        if a.teacher
        else None
    )
    stats: Counter = Counter()
    b = Builder(rng, a.k, a.max_tokens, a.hindi_share, teacher, stats)

    questions = load_questions(a.eval_dir)
    labels: dict[str, dict[str, dict]] = {}
    unans: dict[str, list[dict]] = {}
    for q in questions:
        if q["answerable"]:
            labels.setdefault(q["tender_id"], {})[q["fact"]] = q
        else:
            unans.setdefault(q["tender_id"], []).append(q)
    tenders = load_tenders(a.pdf_dir, a.eval_dir)
    for d in a.extra_pdf_dir:
        tenders += load_tenders(d, a.eval_dir)

    val = val_tenders([t.tender_id for t in tenders if t.split != "test"], a.val_share)
    splits: dict[str, list] = {"train": [], "val": []}
    tender_split: dict[str, str] = {}
    for t in tenders:
        if t.split == "test":
            tender_split[t.tender_id] = "test (excluded)"
            continue
        split = "val" if t.tender_id in val else "train"
        tender_split[t.tender_id] = split
        ex = tender_examples(b, t, labels.get(t.tender_id, {}), unans.get(t.tender_id, []))
        splits[split].extend(ex)
        print(f"{t.tender_id:28} {split:5} {len(ex):4} examples", flush=True)

    a.out.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        rng.shuffle(rows)
        with (a.out / f"{name}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    toks = [r["meta"]["est_tokens"] for rows in splits.values() for r in rows]
    summary = {
        "train": len(splits["train"]),
        "val": len(splits["val"]),
        "tenders": Counter(tender_split.values()),
        "val_tenders": sorted(t for t, s in tender_split.items() if s == "val"),
        "est_tokens_mean": round(sum(toks) / len(toks)) if toks else 0,
        "est_tokens_max": max(toks, default=0),
        "est_tokens_total_train": sum(r["meta"]["est_tokens"] for r in splits["train"]),
        **dict(sorted(stats.items())),
        "system_prompt_chars": len(SYSTEM_PROMPT),
    }
    (a.out / "stats.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
