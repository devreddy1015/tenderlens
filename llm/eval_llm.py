"""Evaluate any OpenAI-compatible endpoint on grounded tender Q&A, one or two side by side.

    uv run python eval_llm.py --endpoint base=http://127.0.0.1:8081/v1
    uv run python eval_llm.py --endpoint base=http://127.0.0.1:8081/v1 \
        --endpoint ft=http://127.0.0.1:8082/v1 --split test

Items come from DocIntel's eval set (questions.jsonl + the PDFs). The passages are what
production would send: the tender's chunks ranked by BM25 for the question, top --k, best
first, in the exact prompt format of prompt.py. Three kinds of item:

  answerable   the passage holding the answer is among the k (injected in the last slot
               when BM25 missed it, so this measures the model, not retrieval);
  unanswerable DocIntel's "none" questions (plausible, not in the tender);
  no-gold      an answerable question with every passage that holds the answer removed:
               the distractors are on-topic, so this is the hard abstention test.

Metrics, per endpoint:
  exact value match   answerable items whose answer contains every expected value
                      ("Rs. 9,38,100/-" == "₹9,38,100"), DocIntel's metric;
  valid citation      answered items where every sentence ends with [n] and every n exists;
  grounding           answered items where every number/date is in the passages cited;
  abstention accuracy items where the model abstained exactly when it should;
  confident-wrong     answered (no abstention, no "not mentioned" hedge) and wrong;
  served correct      answerable items that are right AND pass the grounding post-check,
                      i.e. what the copilot would show; served wrong is the dangerous
                      complement (wrong but passes the post-check).

The questions are tuned on nothing: --split test uses tenders that build_dataset.py never
trains on. Results go to out/eval/<run>/<endpoint>.jsonl (resumable) and summary.json.
"""

import argparse
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from corpus import (
    DEFAULT_EVAL_DIR,
    DEFAULT_PDF_DIR,
    bm25_rank,
    contains_evidence,
    load_questions,
    load_tenders,
)
from grounding import check, values_match
from prompt import ABSTAIN, REQUEST_PARAMS, build_messages, clean_answer, is_abstention

HERE = Path(__file__).resolve().parent

# Phrases a model uses when it hedges instead of abstaining with the exact sentence. Such an
# answer is not "confident" (the copilot shows the hedge), so it is not counted as
# confident-wrong, but it is not a correct abstention either.
_HEDGE = re.compile(
    r"\b(?:not (?:mentioned|specified|stated|provided|given|available|found|included)"
    r"|(?:do|does|did) not (?:mention|specify|state|contain|provide|say|include)"
    r"|no (?:information|mention|details?)|couldn'?t find|could not find|cannot find)\b"
    r"|उल्लेख नहीं|नहीं मिल|नहीं दी गई|नहीं है",
    re.I,
)


@dataclass
class Item:
    id: str
    kind: str  # answerable | unanswerable | no_gold
    tender_id: str
    fact: str
    question: str
    expected: str
    passages: list[dict]
    gold: list[int] = field(default_factory=list)  # 1-based passage numbers holding the answer
    gold_injected: bool = False

    @property
    def should_abstain(self) -> bool:
        return self.kind != "answerable"


def _holds_answer(text: str, q: dict) -> bool:
    return contains_evidence(text, q.get("evidence")) or (
        bool(q.get("answer")) and values_match(q["answer"], text)
    )


def build_items(
    split: str = "test",
    k: int = 4,
    no_gold_share: float = 0.25,
    pdf_dir: Path = DEFAULT_PDF_DIR,
    eval_dir: Path = DEFAULT_EVAL_DIR,
    seed: int = 7,
) -> tuple[list[Item], Counter]:
    """Deterministic: the same split/k/share always gives the same items in the same order."""
    rng = random.Random(seed)
    tenders = {t.tender_id: t for t in load_tenders(pdf_dir, eval_dir)}
    chunks = {tid: t.chunks() for tid, t in tenders.items()}
    skipped: Counter = Counter()
    items: list[Item] = []
    for q in load_questions(eval_dir):
        if split != "all" and q.get("split") != split:
            continue
        ch = chunks.get(q["tender_id"])
        if not ch:
            skipped["no_pdf"] += 1
            continue
        order = bm25_rank(ch, q["question"])
        base = {
            "tender_id": q["tender_id"],
            "fact": q.get("fact", ""),
            "question": q["question"],
        }
        if not q["answerable"]:
            top = order[:k]
            items.append(
                Item(
                    q["id"],
                    "unanswerable",
                    expected="",
                    passages=[ch[i].passage for i in top],
                    **base,
                )
            )
            continue
        gold_ids = [i for i in order if contains_evidence(ch[i].text, q["evidence"])]
        if not gold_ids:
            skipped["evidence_not_extracted"] += 1  # e.g. a fact only on an un-OCR'd page
            continue
        top = order[:k]
        injected = not any(i in gold_ids for i in top)
        if injected:
            top = [*top[: k - 1], gold_ids[0]]
        items.append(
            Item(
                q["id"],
                "answerable",
                expected=q["answer"],
                passages=[ch[i].passage for i in top],
                gold=[n for n, i in enumerate(top, 1) if i in gold_ids],
                gold_injected=injected,
                **base,
            )
        )
        if rng.random() < no_gold_share:
            rest = [i for i in order if not _holds_answer(ch[i].text, q)]
            if len(rest) >= 2:
                items.append(
                    Item(
                        q["id"] + ":no_gold",
                        "no_gold",
                        expected="",
                        passages=[ch[i].passage for i in rest[:k]],
                        **base,
                    )
                )
    return items, skipped


def probe_items(k: int = 4) -> list[Item]:
    """Ten train-split items covering every failure mode we care about, for prompt work
    (tuning on train keeps the test numbers honest)."""
    items, _ = build_items("train", k=k, no_gold_share=0.3)
    want = [
        ("answerable", "emd"),
        ("answerable", "turnover"),
        ("answerable", "similar_works"),
        ("answerable", "liquidated_damages"),
        ("answerable", "prebid"),
        ("answerable", "officer"),
        ("answerable", "advance"),
        ("answerable", "defect_liability"),
        ("unanswerable", "none"),
        ("no_gold", None),
    ]
    out, used = [], set()
    for kind, fact in want:
        for it in items:
            if it.kind == kind and (fact is None or it.fact == fact) and it.tender_id not in used:
                out.append(it)
                used.add(it.tender_id)
                break
    return out


def stratified_sample(items: list[Item], n: int, seed: int = 11) -> list[Item]:
    """n items with each kind in proportion (at least 5 of each), original order kept."""
    rng = random.Random(seed)
    by_kind: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        by_kind[it.kind].append(i)
    pick: list[int] = []
    for idx in by_kind.values():
        want = min(len(idx), max(5, round(n * len(idx) / len(items))))
        pick += rng.sample(idx, want)
    return [items[i] for i in sorted(pick)]


# --- calling the endpoint -----------------------------------------------------------------


class Endpoint:
    def __init__(
        self, name: str, base_url: str, model: str | None, api_key: str | None, timeout: float
    ):
        self.name, self.base_url = name, base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(timeout=timeout, headers=headers)
        self.model = model or self._first_model()

    def _first_model(self) -> str:
        try:
            r = self.http.get(f"{self.base_url}/models")
            r.raise_for_status()
            return r.json()["data"][0]["id"]
        except (httpx.HTTPError, KeyError, IndexError):
            return "default"

    def ask(self, messages: list[dict], extra: dict | None = None) -> dict:
        body = {"model": self.model, "messages": messages, **REQUEST_PARAMS, **(extra or {})}
        last: Exception | None = None
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                r = self.http.post(f"{self.base_url}/chat/completions", json=body)
                r.raise_for_status()
                data = r.json()
                data["_latency_ms"] = round((time.perf_counter() - t0) * 1000)
                return data
            except httpx.HTTPError as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{self.name}: {last}")


# --- scoring ------------------------------------------------------------------------------


def score(item: Item, raw: str) -> dict:
    answer = clean_answer(raw)
    abstained = is_abstention(answer) and answer.strip() == ABSTAIN
    hedged = not abstained and bool(_HEDGE.search(answer))
    rep = (
        None if abstained else check(answer, {n: p["text"] for n, p in enumerate(item.passages, 1)})
    )
    valid_citation = bool(rep and rep.all_sentences_cited and not rep.invalid_citations)
    grounded = bool(rep and rep.ok and rep.citations)
    value_match = (
        (not abstained) and item.kind == "answerable" and values_match(item.expected, answer)
    )
    if item.should_abstain:
        correct = abstained
        wrong = not abstained and not hedged
    else:
        correct = value_match
        wrong = not abstained and not hedged and not value_match
    cites_gold = bool(rep and item.gold and set(rep.citations) & set(item.gold))
    return {
        "answer": answer,
        "think_leak": "<think>" in raw or "</think>" in raw,
        "abstained": abstained,
        "hedged": hedged,
        "value_match": value_match,
        "valid_citation": valid_citation,
        "grounded": grounded,
        "cites_gold": cites_gold,
        "unsupported": rep.unsupported if rep else [],
        "uncited": rep.uncited_claims if rep else [],
        "invalid_citations": rep.invalid_citations if rep else [],
        "correct": correct,
        "confident_wrong": wrong,
    }


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def summarise(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["kind"] == "answerable"]
    abst = [r for r in rows if r["kind"] != "answerable"]
    answered = [r for r in rows if not r["abstained"]]
    lat = [r["latency_ms"] for r in rows if r.get("latency_ms")]
    pp = [r["pp_tps"] for r in rows if r.get("pp_tps")]
    tg = [r["tg_tps"] for r in rows if r.get("tg_tps")]
    by_fact: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in ans:
        by_fact[r["fact"]][0] += r["value_match"]
        by_fact[r["fact"]][1] += 1
    served_ok = sum(r["value_match"] and r["grounded"] for r in ans)
    served_wrong = sum(
        (not r["abstained"]) and r["grounded"] and not r["hedged"] and not r["correct"]
        for r in rows
    )
    return {
        "items": len(rows),
        "answerable": len(ans),
        "should_abstain": len(abst),
        "exact_value_match": _rate(sum(r["value_match"] for r in ans), len(ans)),
        "valid_citation_rate": _rate(sum(r["valid_citation"] for r in answered), len(answered)),
        "grounding_rate": _rate(sum(r["grounded"] for r in answered), len(answered)),
        "abstention_accuracy": _rate(
            sum(r["abstained"] == (r["kind"] != "answerable") for r in rows), len(rows)
        ),
        "abstain_recall": _rate(sum(r["abstained"] for r in abst), len(abst)),
        "false_abstentions": sum(r["abstained"] for r in ans),
        "hedged": sum(r["hedged"] for r in rows),
        "confident_wrong": sum(r["confident_wrong"] for r in rows),
        "served_correct": _rate(served_ok, len(ans)),
        "served_wrong": served_wrong,
        "think_leaks": sum(r["think_leak"] for r in rows),
        "latency_ms_p50": round(statistics.median(lat)) if lat else None,
        "latency_ms_p95": round(statistics.quantiles(lat, n=20)[-1]) if len(lat) >= 20 else None,
        "prompt_tokens_mean": round(
            statistics.mean(r["prompt_tokens"] for r in rows if r.get("prompt_tokens"))
        )
        if any(r.get("prompt_tokens") for r in rows)
        else None,
        "completion_tokens_mean": round(
            statistics.mean(r["completion_tokens"] for r in rows if r.get("completion_tokens")), 1
        )
        if any(r.get("completion_tokens") for r in rows)
        else None,
        "prompt_tps_mean": round(statistics.mean(pp), 1) if pp else None,
        "gen_tps_mean": round(statistics.mean(tg), 1) if tg else None,
        "by_fact": {f: f"{a}/{n}" for f, (a, n) in sorted(by_fact.items())},
    }


def run_endpoint(ep: Endpoint, items: list[Item], out: Path, verbose: bool) -> list[dict]:
    """One JSONL row per item; rows already in the file are kept, so a cut-off run resumes."""
    done: dict[str, dict] = {}
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["id"]] = row
    rows = []
    with out.open("a") as fh:
        for i, it in enumerate(items, 1):
            if it.id in done:
                rows.append(done[it.id])
                continue
            data = ep.ask(build_messages(it.question, it.passages))
            raw = data["choices"][0]["message"].get("content") or ""
            usage, timings = data.get("usage") or {}, data.get("timings") or {}
            row = {
                "id": it.id,
                "kind": it.kind,
                "fact": it.fact,
                "tender_id": it.tender_id,
                "question": it.question,
                "expected": it.expected,
                "gold": it.gold,
                "gold_injected": it.gold_injected,
                "raw": raw,
                **score(it, raw),
                "latency_ms": data["_latency_ms"],
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "pp_tps": round(timings["prompt_per_second"], 1)
                if timings.get("prompt_per_second")
                else None,
                "tg_tps": round(timings["predicted_per_second"], 1)
                if timings.get("predicted_per_second")
                else None,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            rows.append(row)
            flag = "OK " if row["correct"] else ("HEDGE" if row["hedged"] else "BAD")
            print(
                f"[{ep.name} {i}/{len(items)}] {flag} {it.kind:12} {it.fact:20} "
                f"{row['latency_ms'] / 1000:5.1f}s  {row['answer'][:110]!r}",
                flush=True,
            )
            if verbose and not row["correct"]:
                print(
                    f"    expected={it.expected!r} gold={it.gold} unsupported={row['unsupported']}"
                )
    return rows


def table(summaries: dict[str, dict]) -> str:
    names = list(summaries)
    keys = [
        "items",
        "exact_value_match",
        "valid_citation_rate",
        "grounding_rate",
        "abstention_accuracy",
        "abstain_recall",
        "false_abstentions",
        "hedged",
        "confident_wrong",
        "served_correct",
        "served_wrong",
        "think_leaks",
        "latency_ms_p50",
        "latency_ms_p95",
        "prompt_tokens_mean",
        "completion_tokens_mean",
        "prompt_tps_mean",
        "gen_tps_mean",
    ]
    lines = ["| metric | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
    for key in keys:
        lines.append(f"| {key} | " + " | ".join(str(summaries[n].get(key)) for n in names) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--endpoint",
        action="append",
        required=True,
        help="name=base_url (OpenAI-compatible, e.g. base=http://127.0.0.1:8081/v1); give two to compare",
    )
    ap.add_argument(
        "--model", action="append", help="model id per endpoint (default: first of /models)"
    )
    ap.add_argument(
        "--api-key-env", default="LLM_API_KEY", help="env var holding a bearer key, if any"
    )
    ap.add_argument("--split", default="test", choices=["test", "train", "all"])
    ap.add_argument("--k", type=int, default=4, help="passages per question (copilot default)")
    ap.add_argument("--no-gold-share", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=0, help="first N items only (smoke runs)")
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="a fixed stratified sample of N items (every kind, many tenders) for slow CPUs",
    )
    ap.add_argument("--probe", action="store_true", help="the 10 train-split prompt-tuning items")
    ap.add_argument("--run", default=None, help="results folder name (default: split-k)")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    ap.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    if a.probe:
        items, skipped = probe_items(a.k), Counter()
    else:
        items, skipped = build_items(a.split, a.k, a.no_gold_share, a.pdf_dir, a.eval_dir)
    if a.sample:
        items = stratified_sample(items, a.sample)
    if a.limit:
        items = items[: a.limit]
    kinds = Counter(it.kind for it in items)
    print(f"{len(items)} items {dict(kinds)}; skipped {dict(skipped)}", flush=True)

    run = a.run or ("probe" if a.probe else f"{a.split}-k{a.k}")
    out_dir = HERE / "out" / "eval" / run
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "items.jsonl").write_text(
        "".join(json.dumps(asdict(it), ensure_ascii=False) + "\n" for it in items)
    )
    summaries: dict[str, dict] = {}
    results: dict[str, list[dict]] = {}
    for i, spec in enumerate(a.endpoint):
        name, _, url = spec.partition("=")
        if not url:
            name, url = f"ep{i + 1}", spec
        model = a.model[i] if a.model and i < len(a.model) else None
        ep = Endpoint(name, url, model, os.environ.get(a.api_key_env), a.timeout)
        rows = run_endpoint(ep, items, out_dir / f"{name}.jsonl", a.verbose)
        results[name] = rows
        summaries[name] = {"model": ep.model, "base_url": url, **summarise(rows)}
    if len(results) == 2:
        x, y = (results[n] for n in results)
        flips = Counter(
            ("fixed" if b["correct"] else "broke")
            for a_, b in zip(x, y, strict=True)
            if a_["correct"] != b["correct"]
        )
        summaries["_diff"] = dict(flips)
    meta = {
        "split": "train (probe)" if a.probe else a.split,
        "sample": a.sample,
        "k": a.k,
        "no_gold_share": a.no_gold_share,
        "items": dict(kinds),
        "skipped": dict(skipped),
    }
    (out_dir / "summary.json").write_text(
        json.dumps({"meta": meta, **summaries}, indent=1, ensure_ascii=False)
    )
    print()
    print(table({n: s for n, s in summaries.items() if not n.startswith("_")}))
    for n, s in summaries.items():
        if not n.startswith("_"):
            print(f"\n{n} by fact (value match): {s['by_fact']}")
    if "_diff" in summaries:
        print(f"\nper-item changes {list(results)[0]} -> {list(results)[1]}: {summaries['_diff']}")
    print(f"\nwrote {out_dir}")


if __name__ == "__main__":
    sys.exit(main())
