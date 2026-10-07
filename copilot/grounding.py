"""Post-check for [n]-cited answers: every number, amount, percentage and date in a sentence
must appear in the passages that sentence cites. Ported from the LLM kit's grounding.py (kept off GitHub; keep in sync).

Fact extraction and normalisation are DocIntel's (`docintel/grounding.py`): "₹16 lakh" matches
"16,00,000", "7 October 2026" matches "07-Oct-2026", "2.0%" matches "2 %". What is new here is
the citation format: the self-hosted model writes "[2]" markers instead of returning
Anthropic citation blocks, so answers are split into sentences and each sentence is checked
against the passages it names. Standard library only (the copilot can copy it).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from copilot.prompt import CITATION, cited_numbers

MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

DATE_PATTERNS = [
    (
        re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-./]+{_MON}[\s\-.,/]+(\d{{4}})\b", re.I),
        "dmy_name",
    ),
    (re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), "mdy_name"),
    # Indian documents are day-first.
    (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b"), "dmy_num"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
]
MONEY = re.compile(
    r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr\b|l\b)?"
    r"|([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)\b",
    re.I,
)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent|प्रतिशत)", re.I)
NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w])")
MULTIPLIER = {"lakh": 100_000, "lac": 100_000, "l": 100_000, "crore": 10_000_000, "cr": 10_000_000}


def _num(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _mult(unit: str | None) -> int:
    if not unit:
        return 1
    u = unit.lower().rstrip("s")
    return MULTIPLIER.get(u, MULTIPLIER.get(u.rstrip("e"), 1))


@dataclass(frozen=True)
class Fact:
    kind: str  # date | money | percent | number
    value: object
    text: str


def _parse_date(kind: str, m: re.Match) -> date | None:
    try:
        if kind == "dmy_name":
            return date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        if kind == "mdy_name":
            return date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        if kind == "dmy_num":
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if kind == "ymd":
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except (ValueError, KeyError):
        return None
    return None


def facts(text: str) -> list[Fact]:
    """Dates, then money, percentages, then remaining numbers; matched spans are consumed so
    "07-Oct-2026" is one date, not the numbers 7 and 2026. Citation markers are ignored."""
    text = CITATION.sub(lambda m: " " * len(m.group(0)), text)
    out: list[Fact] = []
    taken = [False] * len(text)

    def free(m: re.Match) -> bool:
        return not any(taken[m.start() : m.end()])

    def take(m: re.Match) -> None:
        for i in range(m.start(), m.end()):
            taken[i] = True

    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            if free(m) and (d := _parse_date(kind, m)):
                out.append(Fact("date", d, m.group(0)))
                take(m)
    for m in MONEY.finditer(text):
        if not free(m):
            continue
        digits, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        n = _num(digits)
        if n is not None:
            out.append(Fact("money", n * _mult(unit), m.group(0)))
            take(m)
    for m in PERCENT.finditer(text):
        if free(m) and (n := _num(m.group(1))) is not None:
            out.append(Fact("percent", n.normalize(), m.group(0)))
            take(m)
    for m in NUMBER.finditer(text):
        if free(m) and (n := _num(m.group(1))) is not None:
            out.append(Fact("number", n.normalize(), m.group(0)))
            take(m)
    return out


def _key(f: Fact) -> tuple:
    # A source "₹16,000" supports an answer "16,000"; only dates keep their kind.
    return ("date", f.value) if f.kind == "date" else ("num", Decimal(f.value).normalize())


def values(text: str) -> set:
    return {_key(f) for f in facts(text)}


_ABBREV = re.compile(
    r"(?:\b(?:Rs|No|Nos|Sl|S|p|pp|Dr|Mr|Ms|Smt|Shri|viz|i\.e|e\.g|etc|approx|Cl)\.)$", re.I
)
_BOUNDARY = re.compile(r"(?<=[.!?।])\s+")


def sentences(answer: str) -> list[str]:
    """Split an answer into sentences, keeping each sentence's trailing [n] markers with it
    ("... /-. [2] The fee ..." -> "... /-. [2]", "The fee ..."). "Rs. 5" never splits."""
    out: list[str] = []
    for line in answer.splitlines():
        start = 0
        for m in _BOUNDARY.finditer(line):
            head = line[start : m.start()]
            nxt = line[m.end() : m.end() + 1]
            if _ABBREV.search(head) or nxt.isdigit() or nxt.islower():
                continue
            out.append(head)
            start = m.end()
        out.append(line[start:])
    merged: list[str] = []
    for s in (s.strip() for s in out):
        if not s:
            continue
        lead = re.match(r"^((?:\[[\d,\s–-]+\]\s*)+)(.*)$", s)
        if lead and merged:  # citation that belongs to the previous sentence
            merged[-1] += " " + lead.group(1).strip()
            s = lead.group(2).strip()
            if not s:
                continue
        merged.append(s)
    return merged


@dataclass
class Report:
    ok: bool = True
    checked: int = 0
    sentences: int = 0
    cited_sentences: int = 0
    unsupported: list[str] = field(default_factory=list)  # values not in the cited passages
    uncited_claims: list[str] = field(default_factory=list)  # values with no citation at all
    invalid_citations: list[int] = field(default_factory=list)  # [n] with no passage n
    citations: list[int] = field(default_factory=list)

    @property
    def all_sentences_cited(self) -> bool:
        return self.sentences > 0 and self.cited_sentences == self.sentences


def check(answer: str, passages: dict[int, str]) -> Report:
    """passages: {n: text} exactly as numbered in the prompt.

    A sentence without its own [n] borrows the citations of the next cited sentence (models
    often cite once at the end of a two-sentence answer), else of the previous one; a value
    in an answer that cites nothing at all is an uncited claim and fails.
    """
    sents = sentences(answer)
    cites = [cited_numbers(s) for s in sents]
    rep = Report(sentences=len(sents), cited_sentences=sum(bool(c) for c in cites))
    for c in cites:
        for n in c:
            if n not in rep.citations:
                rep.citations.append(n)
    rep.invalid_citations = [n for n in rep.citations if n not in passages]
    cache: dict[int, set] = {}

    def support(nums: list[int]) -> set:
        out: set = set()
        for n in nums:
            if n in passages:
                if n not in cache:
                    cache[n] = values(passages[n])
                out |= cache[n]
        return out

    for i, s in enumerate(sents):
        fs = facts(s)
        if not fs:
            continue
        own = cites[i] or next((c for c in cites[i + 1 :] if c), None)
        own = own or next((c for c in reversed(cites[:i]) if c), None)
        if not own:
            rep.uncited_claims.append(s[:120])
            continue
        allowed = support(own)
        for f in fs:
            rep.checked += 1
            if _key(f) not in allowed:
                rep.unsupported.append(f.text.strip())
    rep.ok = not (rep.unsupported or rep.uncited_claims or rep.invalid_citations)
    return rep


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"\s+", " ", s).replace("- ", "-").strip()


def values_match(expected: str, answer: str) -> bool:
    """Every value of the expected answer appears in the model's answer as a value
    ("Rs. 9,38,100/-" matches "₹9,38,100"); textual answers (an officer's name) match as a
    normalised substring. DocIntel's exact-match metric."""
    exp = {_key(f) for f in facts(expected)}
    if not exp:
        return norm(expected) in norm(answer)
    return exp <= values(answer)
