"""Bid Brief: the facts a contractor needs before bidding, pulled out of the tender documents
by rules, each with its page and the sentence it came from. No LLM: it runs in milliseconds
on CPU, costs nothing per document, and cannot invent a value.

Each extractor finds a label ("Earnest Money Deposit", "Last date for bid submission") and
then the first value of the right kind after it (an amount, a date, a period, a percentage),
inside a short window that stops at the next sentence or at another field's label, so a
missing value is reported as missing instead of borrowed from the next row. Values are
returned exactly as the document writes them ("Rs. 22,316/-", "03-Oct-2026 03:00 PM").

Indian formats: ₹ / Rs. / INR / Rupees, lakh and crore, dd-mm-yyyy, 07-Oct-2026,
7th October 2026, "within 30 days", "9 (nine) months", percentages.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

from copilot import grounding
from copilot.chunking import running_lines
from copilot.extract import Page

# --- value patterns -------------------------------------------------------------------

_AMOUNT = r"\d[\d,]*(?:\.\d+)?"
_UNIT = r"(?:\s*(?:lakhs?|lacs?|crores?|cr\.?)(?![a-z]))?"
MONEY = re.compile(
    rf"(?:₹|\bRs\.?|\bINR|\bRupees)\s*{_AMOUNT}(?:\s*/-)?{_UNIT}(?:\s*/-)?"
    rf"|\b{_AMOUNT}\s*(?:lakhs?|lacs?|crores?)\b",
    re.I,
)
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_TIME = r"(?:\s*(?:at\s*)?\(?\s*\d{1,2}[:.]\d{2}\s*(?:[AP]\.M\.|[AP]M\b|hrs\b|hours\b)?\)?)?"
DATE = re.compile(
    rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?[\s\-./]+{_MON}[\s\-.,/]+\d{{4}}"
    rf"|{_MON}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    rf"|\d{{1,2}}[/\-.]\d{{1,2}}[/\-.]\d{{4}}"
    rf"|\d{{4}}-\d{{2}}-\d{{2}}){_TIME}",
    re.I,
)
_NUMWORD = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|eighteen|"
    r"twenty[- ]four|thirty|forty[- ]five|sixty|ninety|one hundred (?:and )?(?:twenty|eighty)"
)
PERIOD = re.compile(
    rf"\b(?:\d{{1,4}}|{_NUMWORD})\s*(?:\(\s*[a-z][a-z\- ]*\)\s*)?(?:calendar\s+|working\s+)?"
    r"(?:days?|weeks?|months?|years?)\b",
    re.I,
)
PERCENT = re.compile(r"\d+(?:\.\d+)?\s*(?:%|per\s*cent\b|percent\b)", re.I)
PCT_OR_MONEY = re.compile(f"{PERCENT.pattern}|{MONEY.pattern}", re.I)
# "(50% of the estimated cost)" or "of the tendered value" right after a value belongs with it.
_QUALIFIER = re.compile(
    r"\s*\([^()]{2,80}\)|\s+of\s+(?:the\s+)?(?:tendered|contract|bid|order|estimated|accepted)"
    r"\s+(?:value|amount|cost)",
    re.I,
)

# --- fields ---------------------------------------------------------------------------


@dataclass
class Spec:
    key: str
    label: str
    labels: str  # regex alternatives for the field's label in the document
    value: re.Pattern
    window: int = 160
    qualifier: bool = False  # keep a "(... of the estimated cost)" that follows the value
    span_to_last: bool = False  # value runs to the last match in the sentence ("0.5% ... 10%")


SPECS = [
    Spec(
        "emd",
        "EMD (bid security)",
        r"earnest\s+money(?:\s+deposit)?|\bEMD\b|\bbid\s+security|बयाना\s+राशि",
        MONEY,
    ),
    Spec(
        "tender_fee",
        "Tender fee",
        r"tender\s+(?:document\s+|processing\s+)?fee|cost\s+of\s+(?:the\s+)?(?:tender|bid)\s+"
        r"documents?|document\s+fee",
        MONEY,
    ),
    Spec(
        "estimated_value",
        "Estimated value",
        r"estimated\s+(?:cost|value|amount)(?:\s+of\s+(?:the\s+)?work)?(?:\s+put\s+to\s+tender)?"
        r"|tender\s+value|value\s+of\s+(?:the\s+)?(?:work|contract)|approximate\s+value",
        MONEY,
    ),
    Spec(
        "bid_submission_end",
        "Bid submission deadline",
        r"last\s+date(?:\s+(?:and|&)\s+time)?(?:\s+\S+){0,4}?\s+(?:for|of)\s+(?:receipt\s+of\s+|online\s+)?"
        r"(?:bids?\s+)?(?:\S+\s+){0,4}?(?:submission|receipt)|bid\s+submission\s+end\s+date|closing\s+date"
        r"(?:\s+(?:and|&)\s+time)?|due\s+date\s+(?:of|for)\s+submission|अंतिम\s+तिथि",
        DATE,
    ),
    Spec(
        "bid_opening",
        "Bid opening",
        r"(?:technical\s+)?bid\s+opening\s+date|date\s+(?:(?:and|&)\s+time\s+)?of\s+(?:technical\s+)?"
        r"(?:bid\s+)?opening|opening\s+of\s+(?:technical\s+)?bids?|bids?\s+(?:shall|will)\s+be\s+"
        r"opened\s+on",
        DATE,
    ),
    Spec(
        "prebid_meeting",
        "Pre-bid meeting",
        r"pre[\s-]?bid\s+(?:meeting|conference)",
        DATE,
    ),
    Spec(
        "completion_period",
        "Completion period",
        r"(?:period|time)\s+of\s+(?:\S+\s+){0,2}?completion|completion\s+(?:period|time)|time\s+allowed"
        r"(?:\s+for\s+completion)?|contract\s+period|shall\s+be\s+completed\s+within",
        PERIOD,
        window=80,
    ),
    Spec(
        "bid_validity",
        "Bid validity",
        r"bid\s+validity(?:\s+period)?|validity\s+of\s+(?:the\s+)?(?:bids?|offers?)"
        r"|(?:bids?|offers?)\s+shall\s+(?:remain\s+)?valid(?:\s+for)?",
        PERIOD,
        window=80,
    ),
    Spec(
        "min_turnover",
        "Minimum annual turnover",
        r"(?:average\s+)?annual\s+(?:financial\s+)?turnover|financial\s+turnover|\bturnover\b",
        MONEY,
        window=200,
        qualifier=True,
    ),
    Spec(
        "similar_work",
        "Similar work experience",
        r"similar\s+(?:completed\s+)?works?",
        MONEY,
        window=200,
        qualifier=True,
    ),
    Spec(
        "performance_security",
        "Performance security",
        r"performance\s+(?:security|(?:bank\s+)?guarantee)",
        PCT_OR_MONEY,
        window=120,
        qualifier=True,
    ),
    Spec(
        "liquidated_damages",
        "Liquidated damages",
        r"liquidated\s+damages|compensation\s+for\s+delay|compensation\s+(?:at\s+the\s+rate|@)"
        r"|penalty\s+for\s+(?:delay|late)",
        PERCENT,
        window=200,
        span_to_last=True,
    ),
]
KEYS = [
    *(s.key for s in SPECS[:8]),
    "min_turnover",
    "similar_work",
    "performance_security",
    "liquidated_damages",
    "mse_exemption",
    "documents_required",
]
LABELS = {s.key: s.label for s in SPECS} | {
    "mse_exemption": "MSE / Startup exemption",
    "documents_required": "Documents required",
}
_LABEL_RX = {s.key: re.compile(s.labels, re.I) for s in SPECS}
_OTHER_LABELS = {
    s.key: re.compile("|".join(o.labels for o in SPECS if o.key != s.key), re.I) for s in SPECS
}
# A sentence ends at ". " before a capital, but not after "Rs." / "No." and similar.
_SENT_END = re.compile(r"(?<!\bRs)(?<!\bNo)(?<!\bSl)(?<!\bp)\.\s+(?=[A-Z])|[।;]\s*")


@dataclass
class Field:
    key: str
    value: str | list[str]
    page: int
    quote: str
    document_id: int | None = None
    filename: str = ""
    amounts: list[Decimal] = field(default_factory=list)  # INR values, for eligibility

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": LABELS[self.key],
            "value": self.value,
            "page": self.page,
            "quote": self.quote,
            "document_id": self.document_id,
            "filename": self.filename,
        }


@dataclass
class DocText:
    """A document as one whitespace-collapsed string (a value may wrap onto the next page),
    with the offset where each page starts, and the pages' lines for list detection."""

    text: str
    starts: list[int]  # starts[i] = offset of page numbers[i]
    numbers: list[int]
    lined: list[tuple[int, str]]

    def page_at(self, offset: int) -> int:
        return self.numbers[max(0, bisect_right(self.starts, offset) - 1)]


def doc_text(pages: list[Page]) -> DocText:
    """Running headers and footers are dropped: a footer must not sit between a label and
    its value."""
    skip = running_lines(pages)
    digits = re.compile(r"\d+")
    parts, starts, numbers, lined, pos = [], [], [], [], 0
    for p in pages:
        lines = [
            ln.strip()
            for ln in p.text.splitlines()
            if ln.strip() and digits.sub("#", ln.strip()) not in skip
        ]
        flat = " ".join(" ".join(lines).split())
        starts.append(pos)
        numbers.append(p.number)
        parts.append(flat)
        lined.append((p.number, "\n".join(lines)))
        pos += len(flat) + 1
    return DocText(" ".join(parts), starts, numbers, lined)


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    lo = max(0, start - 150)
    head = list(_SENT_END.finditer(text, lo, start))
    s = head[-1].end() if head else lo
    tail = _SENT_END.search(text, end, min(len(text), end + 150))
    e = tail.start() + 1 if tail else min(len(text), end + 150)
    return s, e


def _quote(text: str, start: int, end: int) -> str:
    s, e = _sentence_bounds(text, min(start, end), max(start, end))
    return text[s:e].strip()[:350]


def _money(value: str) -> list[Decimal]:
    return [Decimal(f.value) for f in grounding.facts(value) if f.kind == "money"]


def _find(spec: Spec, doc: DocText) -> Field | None:
    label_rx, others, text = _LABEL_RX[spec.key], _OTHER_LABELS[spec.key], doc.text
    for m in label_rx.finditer(text):
        # From the label's start: wrapped table cells put the value inside the label
        # ("Last date and time for bid 03-Oct-2026 04:00 PM submission").
        lo, hi = m.start(), min(len(text), m.end() + spec.window)
        for stop in (others.search(text, m.end(), hi), _SENT_END.search(text, m.end(), hi)):
            if stop:
                hi = min(hi, stop.start() + (1 if stop.group(0).startswith(".") else 0))
        v = spec.value.search(text, lo, hi)
        if not v:
            continue
        v_start, v_end = v.start(), v.end()
        if spec.span_to_last:
            s_end = _sentence_bounds(text, v_start, v_end)[1]
            for later in spec.value.finditer(text, v_end, s_end):
                v_end = later.end()
        if spec.qualifier and (q := _QUALIFIER.match(text, v_end)):
            v_end = q.end()
        value = text[v_start:v_end].strip()
        return Field(
            spec.key,
            value,
            doc.page_at(v_start),
            _quote(text, m.start(), v_end),
            amounts=_money(value),
        )
    return None


# --- similar work: every amount of the clause ("3 works of 40%, 2 of 60% or 1 of 80%") ----


def _similar_work(doc: DocText) -> Field | None:
    """The whole requirement, from the start of its sentence ("Three similar completed works
    each costing not less than Rs. X (40% of the estimated cost)"), and every amount in the
    clause: CPWD-style clauses offer options (3 works of 40%, 2 of 60% or 1 of 80%)."""
    f = _find(next(s for s in SPECS if s.key == "similar_work"), doc)
    if f is None:
        return None
    text = doc.text
    at = text.find(f.value)
    if at >= 0:
        s, _ = _sentence_bounds(text, at, at + len(f.value))
        s = max(s, text.rfind(":", s, at) + 1)  # "...bids are invited: One similar work..."
        if at - s < 250:
            f.value = text[s : at + len(f.value)].strip()
    clause = text[max(0, at - 400) : at + 400] if at >= 0 else f.quote
    lo = clause.lower().find("similar")
    clause = clause[max(0, lo - 100) :] if lo >= 0 else clause
    stop = re.search(r"\b(?:turnover|solvency|EMD|earnest)\b", clause[40:], re.I)
    clause = clause[: 40 + stop.start()] if stop else clause
    f.amounts = sorted(set(_money(clause) or f.amounts))
    return f


# --- MSE / startup exemption ----------------------------------------------------------

_MSE = re.compile(
    r"\bMSEs?\b|\bMSMEs?\b|micro,?\s+(?:and|&)\s+small\s+enterprises?|\bNSIC\b|\budyam\b"
    r"|start-?ups?\b|DPIIT",
    re.I,
)
_EXEMPT = re.compile(r"exempt", re.I)
_NOT_EXEMPT = re.compile(
    r"\b(?:not|no|nor)\b[^.]{0,40}exempt|exemption[^.]{0,30}\bnot\b[^.]{0,20}(?:allowed|"
    r"available|applicable|admissible)",
    re.I,
)


_EXEMPT_FROM = (
    ("EMD", r"\bEMD\b|earnest|bid security"),
    ("tender fee", r"tender\s+(?:document\s+)?fee|cost of (?:the )?tender"),
    ("experience and turnover criteria", r"turnover|prior experience|experience"),
)


def _mse(doc: DocText) -> Field | None:
    text = doc.text
    for m in _MSE.finditer(text):
        s, e = _sentence_bounds(text, m.start(), m.end())
        sentence = text[s:e]
        if not _EXEMPT.search(sentence):
            continue
        what = [w for w, rx in _EXEMPT_FROM if re.search(rx, sentence, re.I)]
        verdict = "No exemption" if _NOT_EXEMPT.search(sentence) else "Exempted"
        value = verdict + (f" from {', '.join(what)}" if what else "")
        return Field("mse_exemption", value, doc.page_at(m.start()), sentence.strip()[:350])
    return None


# --- documents required -------------------------------------------------------------

_DOC_HEADING = re.compile(
    r"(?:list\s+of\s+)?documents?\s+(?:to\s+be\s+|required\s+to\s+be\s+)?(?:uploaded|submitted|"
    r"required|enclosed|furnished)|check\s*-?\s*list\s+of\s+documents|list\s+of\s+documents",
    re.I,
)
_ITEM = re.compile(r"^\s*(?:\(?[0-9]{1,2}[.)]|\(?[a-zA-Z][.)]|\(?[ivx]{1,4}[.)]|[•\-–*·])\s*(.+)$")
_HEADING_LINE = re.compile(r"^\s*(?:\d{1,2}(?:\.\d{1,2})*\.?\s+)?[A-Z][A-Z &/,\-()]{5,}$")
KNOWN_DOCS = [
    ("PAN card", r"\bPAN\b"),
    ("GST registration", r"\bGST(?:IN)?\b[^.]{0,30}registration|\bGSTIN\b|GST registration"),
    ("EPF registration", r"\bEPF\b|Employees'?\s*Provident\s+Fund"),
    ("ESI registration", r"\bESIC?\b|Employees'?\s*State\s+Insurance"),
    ("MSE / Udyam certificate", r"\budyam\b|\bNSIC\b[^.]{0,30}certificate|MSE certificate"),
    (
        "Experience / completion certificates",
        r"(?:experience|completion|performance)\s+certificates?",
    ),
    ("Audited balance sheets", r"audited\s+(?:balance\s+sheets?|accounts|financial\s+statements)"),
    ("Income tax returns", r"income\s+tax\s+returns?|\bITRs?\b"),
    ("CA turnover certificate", r"chartered\s+accountant|CA\s+certificate"),
    ("Bank solvency certificate", r"solvency\s+certificate"),
    ("Affidavit", r"\baffidavit\b"),
    ("Contractor registration certificate", r"registration\s+certificate|enlistment"),
    ("Power of attorney", r"power\s+of\s+attorney"),
    ("Joint venture agreement", r"joint\s+venture\s+agreement|JV\s+agreement"),
    ("Labour licence", r"labour\s+licen[cs]e"),
]


def _documents(doc: DocText) -> Field | None:
    # 1. A section that lists them ("Documents to be uploaded: 1. ... 2. ...").
    for number, lined in doc.lined:
        lines = lined.splitlines()
        for i, line in enumerate(lines):
            if not _DOC_HEADING.search(line) or len(line) > 120:
                continue
            items: list[str] = []
            for nxt in lines[i + 1 : i + 40]:
                if _HEADING_LINE.match(nxt) and items:
                    break
                m = _ITEM.match(nxt)
                if m:
                    items.append(m.group(1).strip().rstrip(";.,")[:200])
                elif items and nxt and nxt[0].islower():  # wrapped item
                    items[-1] = f"{items[-1]} {nxt.strip()}"[:200]
                elif items:
                    break
                if len(items) >= 25:
                    break
            if len(items) >= 2:
                return Field("documents_required", items, number, line.strip()[:350])
    # 2. Otherwise the well-known documents the text mentions as required.
    found: list[str] = []
    first: tuple[int, str] | None = None
    text = doc.text
    hits = sorted(
        (m.start(), m.end(), name) for name, rx in KNOWN_DOCS if (m := re.search(rx, text, re.I))
    )
    for start, end, name in hits:
        found.append(name)
        if first is None:
            first = (doc.page_at(start), _quote(text, start, end))
    if not found or first is None:
        return None
    return Field("documents_required", found, first[0], first[1])


# --- the brief ------------------------------------------------------------------------


def extract_fields(pages: list[Page]) -> dict[str, Field]:
    flat = doc_text(pages)
    out: dict[str, Field] = {}
    for spec in SPECS:
        f = _similar_work(flat) if spec.key == "similar_work" else _find(spec, flat)
        if f:
            out[spec.key] = f
    for key, fn in (("mse_exemption", _mse), ("documents_required", _documents)):
        if f := fn(flat):
            out[key] = f
    return out


def _is_corrigendum(doc) -> bool:
    head = " ".join((doc.page_texts or [""])[:1])[:2000]
    return bool(re.search(r"corrigend|addend", f"{doc.filename} {head}", re.I))


def document_fields(doc) -> dict[str, Field]:
    pages = [Page(i, t) for i, t in enumerate(doc.page_texts or [], start=1)]
    fields = extract_fields(pages)
    for f in fields.values():
        f.document_id, f.filename = doc.pk, doc.filename
    return fields


def merged_fields(docs) -> dict[str, Field]:
    """Across a tender's documents: the first document (oldest upload) that states a field
    wins, except that a corrigendum or addendum overrides what it restates (it usually moves
    dates or changes amounts)."""
    docs = sorted(docs, key=lambda d: (d.created_at, d.pk))
    out: dict[str, Field] = {}
    for doc in docs:
        corr = _is_corrigendum(doc)
        for key, f in document_fields(doc).items():
            if key not in out or corr:
                out[key] = f
    return out


def brief(docs) -> dict:
    fields = merged_fields(docs)
    return {
        "fields": [fields[k].as_dict() for k in KEYS if k in fields],
        "missing": [k for k in KEYS if k not in fields],
        "generated_at": timezone.now().isoformat(),
    }
