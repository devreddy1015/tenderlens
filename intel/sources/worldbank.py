"""World Bank-financed contracts in India: estimate, award and every bid for one contract.

Three public feeds describe the same contracts and share the borrower's contract reference
number (e.g. "IN-ICAR-18247-GO-RFQ"), so they are merged on it:

- Contract award notices (procurement notices API, 2013-today): the awarded bidder and
  every evaluated bidder with their prices in the bid currency (INR for India), as HTML.
- Finances One contract awards (DS00005 FY2020-today, DS01004 FY2001-FY2016): the signed
  amount in US dollars and the supplier, one row per supplier/lot.
- STEP procurement plans (documents API, PDF): the Estimated Amount and Actual Amount in
  US dollars per activity, the method, market approach, status and milestone dates. The
  only public source of the *estimate*, which is what makes award / estimate learnable.

Every row is in US dollars: the plan's and Finances One's amounts already are, and bids
(in rupees) are converted with the contract's own implied rate (award USD / signed INR),
so the bid ladder stays consistent with the award whatever rate the Bank used.
"""

import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Comment

from intel.prices import Deflator
from intel.sources.base import AwardRow, ImportContext, Source, register
from tenders.pincode import ALL_STATES
from tenders.resolution import normalise

log = logging.getLogger(__name__)

NOTICES_URL = (
    "https://search.worldbank.org/api/v2/procnotices?format=json&rows={rows}&os={offset}"
    "&notice_type_exact=Contract%20Award&project_ctry_name=India"
)
FONE_URL = (
    "https://datacatalogapi.worldbank.org/dexapps/fone/api/apiservice?datasetId={dataset}"
    "&resourceId={resource}&top={rows}&skip={offset}&type=json&filter=borrower_country%3D'India'"
)
# DS00005 starts at FY2020; DS01004 is the frozen FY2001-FY2016 history (FY2017-19 is in
# neither, so those years rest on notices and plans alone).
FONE_DATASETS = (("DS00005", "RS00005"), ("DS01004", "RS00934"))
PLANS_URL = (
    "https://search.worldbank.org/api/v2/wds?format=json&docty_exact=Procurement%20Plan"
    "&count_exact=India&rows={rows}&os={offset}&fl=docdt,display_title,pdfurl,txturl,projectid"
)
NOTICE_PAGE = "https://projects.worldbank.org/en/projects-operations/procurement-detail/{}"
PROJECT_PAGE = "https://projects.worldbank.org/en/projects-operations/project-detail/{}"
PAGE_ROWS = 500
FONE_ROWS = 5000
# documents1.worldbank.org serves the PDFs; the APIs tolerate twice the rate.
DOCUMENT_INTERVAL_FACTOR = 2
# STEP plans are cumulative, but some projects publish one plan per implementing unit
# (Kerala SWM: one per municipality). Walk each project's plans newest first and stop
# once this many consecutive parsed plans add no new reference.
PLAN_STOP_AFTER_REDUNDANT = 2
# Older plans that yield no STEP table (pre-2016 layouts, textual parts) end the walk too.
PLAN_STOP_AFTER_EMPTY = 3
# A signed price and a USD award only describe the same contract when the implied
# exchange rate is near that year's average; a 2x gap means a lot or an amendment.
RATE_TOLERANCE = (0.8, 1.25)
INR_PER_USD_BAND = (35.0, 120.0)  # 2000-2026 range, used when no WDI rate is stored
AWARDED_STATUSES = {"signed", "completed", "under implementation"}

# --- normalisation ------------------------------------------------------------------------


def norm_ref(text: str | None) -> str:
    """Uppercase, collapse whitespace, strip surrounding punctuation: the published form."""
    s = re.sub(r"\s+", " ", str(text or "")).strip().upper()
    return re.sub(r"^[\s.,;:/\\-]+|[\s.,;:/\\-]+$", "", s)


# A STEP activity reference carries a Bank-wide activity number and the procurement
# category ("IN-ICAR-18247-GO-RFQ"), so it identifies one contract on its own. Older,
# free-form references ("PACKAGE 1") repeat across projects and are keyed per project.
_STEP_REF = re.compile(r"-\d{4,7}-(CW|GO|NC|CS)-")


def merge_key(project_id: str, ref: str) -> str:
    """The join key: whitespace dropped as well, because STEP PDFs wrap references at any
    character and drop the space at the wrap ("2ND\\nCALL" vs "2ND CALL")."""
    compact = re.sub(r"\s+", "", norm_ref(ref))
    if not compact:
        return ""
    return compact if _STEP_REF.search(compact) else f"{project_id or '?'}:{compact}"


_GROUP_CATEGORY = {"CW": "works", "GO": "goods", "NC": "services", "CS": "consultancy"}


def category_of(ref: str = "", *hints: str) -> str:
    """Reference suffix first ("-CW-"), then the feed's own group or category label."""
    m = re.search(r"-(CW|GO|NC|CS)-", norm_ref(ref))
    if m:
        return _GROUP_CATEGORY[m.group(1)]
    for hint in hints:
        h = (hint or "").strip().lower()
        if not h:
            continue
        if h.upper() in _GROUP_CATEGORY:
            return _GROUP_CATEGORY[h.upper()]
        if "non" in h and "consult" in h:
            return "services"
        if "consult" in h:
            return "consultancy"
        if "work" in h:
            return "works"
        if "good" in h:
            return "goods"
        if "service" in h:
            return "services"
    return ""


_CONSULTANT_SELECTION = re.compile(
    r"\b(qcbs|qbs|cqs|lcs|fbs|sss?|indv|ic|quality|least[- ]cost|fixed[- ]budget|"
    r"consultants?'? qualification|individual)\b"
)


def method_of(*texts: str) -> str:
    """HistoricalAward.Method from codes and names in any of the three feeds. Direct
    selection wins over everything, then consultant selection (scored, so L1 logic does not
    apply), then RFQ/shopping (three quotations, even when advertised), then open bidding."""
    t = " ".join(x for x in texts if x).lower()
    if not t.strip():
        return ""
    if re.search(r"\b(direct|single[- ]source|dir|dc|cds|sss)\b", t):
        return "single"
    if _CONSULTANT_SELECTION.search(t):
        return "qcbs"
    if re.search(r"\b(rfq|request for quotations?|shopping|limited)\b", t):
        return "limited"
    if re.search(r"\b(rfb|rfp|icb|ncb|open|competitive bidding|request for bids)\b", t):
        return "open"
    return "other"


_STATE_ALIASES = {
    "Orissa": "Odisha",
    "Uttaranchal": "Uttarakhand",
    "Pondicherry": "Puducherry",
    "Tamilnadu": "Tamil Nadu",
    "Telengana": "Telangana",
    "Chattisgarh": "Chhattisgarh",
    "Jammu & Kashmir": "Jammu and Kashmir",
    "J&K": "Jammu and Kashmir",
    # The notices API truncates project names ("... Rain-fed Agriculture in Himachal").
    "Himachal": "Himachal Pradesh",
}
_STATE_NAMES = sorted(
    [(s, s) for s in ALL_STATES] + list(_STATE_ALIASES.items()), key=lambda p: -len(p[0])
)
_STATE_RE = [(re.compile(rf"\b{re.escape(n)}\b", re.I), s) for n, s in _STATE_NAMES]


def find_state(*texts: str) -> str:
    """First Indian state named in the texts, tried in order (project name first)."""
    for text in texts:
        if not text:
            continue
        for pattern, state in _STATE_RE:
            if pattern.search(text):
                return state
    return ""


def _date(text) -> date | None:
    s = str(text or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(s[:11].strip(), fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)  # 2026-09-30T00:00:00Z
    return date(*map(int, m.groups())) if m else None


def _dec(text) -> Decimal | None:
    if text is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(text))
    try:
        value = Decimal(s) if s not in {"", ".", "-"} else None
    except InvalidOperation:
        return None
    return value if value and value > 0 else None


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


# --- contract award notices ---------------------------------------------------------------


@dataclass
class Bidder:
    name: str
    role: str  # awarded | evaluated | rejected
    currency: str = ""
    opening: Decimal | None = None
    evaluated: Decimal | None = None
    signed: Decimal | None = None

    def price(self) -> Decimal | None:
        """The evaluated price, unless it is a typo of the opening price (a dropped digit
        turns INR 824,746 into 82,746); a winner published with only its signed price
        bid that price."""
        ev, op = self.evaluated, self.opening
        if ev and op and not (Decimal("0.5") <= ev / op <= 2):
            return op
        return ev or op or self.signed


@dataclass
class Notice:
    id: str
    project_id: str
    project_name: str
    ref: str
    description: str
    group: str
    method: str
    notice_date: date | None
    signature_date: date | None = None
    notification_date: date | None = None
    version: int = 0
    contract_ref: str = ""  # the notice text's own reference: one contract of the activity
    bidders: list[Bidder] = field(default_factory=list)

    @property
    def awarded(self) -> list[Bidder]:
        return [b for b in self.bidders if b.role == "awarded"]

    @property
    def evaluated(self) -> list[Bidder]:
        return [b for b in self.bidders if b.role in {"awarded", "evaluated"}]


_SECTION = re.compile(r"^(awarded|evaluated|rejected)\b[^:]{0,40}:$", re.I)
_PRICE_LABELS = [
    (re.compile(r"^(bid price at opening|read out price)\b", re.I), "opening"),
    (re.compile(r"^(evaluated bid price|final evaluation price)\b", re.I), "evaluated"),
    (re.compile(r"^(signed contract price|contract price)\b", re.I), "signed"),
]
_OTHER_LABELS = re.compile(
    r"^(scores|price:?|currency:?|amount:?|reason for rejection|technical:?|financial:?|"
    r"combined:?|rank:?|country:)",
    re.I,
)
_MONEY = re.compile(r"\b([A-Z]{3})\s*(\d[\d,]*(?:\.\d+)?)")


def _money(text: str) -> tuple[str, Decimal] | None:
    found = [(c, _dec(a)) for c, a in _MONEY.findall(text or "")]
    found = [(c, a) for c, a in found if a]
    if not found:
        return None
    # "USD 2,884,286.00 INR 26,110,374.00": the notice's evaluation currency is INR.
    return next(((c, a) for c, a in found if c == "INR"), found[0])


def _bidder_name(text: str) -> str:
    name = re.sub(r"^name\s*:\s*", "", text, flags=re.I)
    name = re.sub(r"\s*\(\d+\)\s*$", "", name)  # "(763924)": STEP supplier id
    name = re.sub(r"\s*\[[^\]]*\]\s*$", "", name)  # "[BHEL]": old notices' short name
    return _clean(name)


def _tokens(soup: BeautifulSoup) -> list[tuple[str, bool]]:
    out = []
    for s in soup.find_all(string=True):
        if isinstance(s, Comment):
            continue
        text = _clean(s)
        if text:
            out.append((text, any(p.name in {"b", "strong"} for p in s.parents)))
    return out


def parse_notice_text(html: str) -> dict:
    """Header facts and bidders from a notice's HTML. Two layouts exist: the STEP-era one
    (2016+, each value in its own <div>, names in <b>) and the older <p>/"Name:" one; both
    reduce to the same stream of text tokens, read here by one small state machine."""
    soup = BeautifulSoup(html or "", "lxml")
    text = soup.get_text("\n")
    out: dict = {"project_id": "", "ref": "", "version": 0, "bidders": []}
    m = re.search(r"Project\s*:\s*(P\d{5,7})", text)
    out["project_id"] = m.group(1) if m else ""
    m = re.search(r"Bid/Contract Reference No\s*:[ \t]*\n?[ \t]*([^\n]+)", text)
    out["ref"] = _clean(m.group(1)) if m else ""
    m = re.search(r"Notice Version No\s*:\s*(\d+)", text)
    out["version"] = int(m.group(1)) if m else 0
    date_re = r"\s*:?\s*(?:\(YYYY/MM/DD\))?\s*(\d{4}/\d{2}/\d{2}|\d{1,2}-[A-Za-z]{3}-\d{4})"
    m = re.search(r"Contract Signature Date" + date_re, text)
    out["signature_date"] = _date(m.group(1)) if m else None
    m = re.search(r"Date Notification of Award Issued" + date_re, text)
    out["notification_date"] = _date(m.group(1)) if m else None

    role, cur, pending = None, None, None
    for token, bold in _tokens(soup):
        m = _SECTION.match(token)
        if m:
            role, cur, pending = m.group(1).lower(), None, None
            continue
        if role is None:
            continue
        label = next((f for rx, f in _PRICE_LABELS if rx.match(token)), None)
        if label:
            pending = label
            rest = re.sub(r"^[^:]*:", "", token) if ":" in token else ""
            money = _money(rest)
            if money and cur:
                _set_price(cur, label, money)
                pending = None
            continue
        if re.match(r"^name\s*:", token, re.I) or (bold and not _OTHER_LABELS.match(token)):
            cur = Bidder(name=_bidder_name(token), role=role)
            out["bidders"].append(cur)
            pending = None
            continue
        if _OTHER_LABELS.match(token):
            pending = None
            continue
        if pending and cur:
            money = _money(token)
            if money:
                _set_price(cur, pending, money)
            pending = None
    return out


def _set_price(bidder: Bidder, label: str, money: tuple[str, Decimal]) -> None:
    """Keeps one currency per bidder: the evaluation currency. A foreign bidder may open in
    USD and be evaluated in INR; the evaluated price is the comparable one."""
    currency, amount = money
    if label == "evaluated" and bidder.currency and currency != bidder.currency:
        bidder.currency, bidder.opening = currency, None
    bidder.currency = bidder.currency or currency
    if currency == bidder.currency:
        setattr(bidder, label, amount)


def parse_notice(record: dict) -> Notice | None:
    """One API record -> Notice. None when the HTML describes another project: ~1.4% of the
    India records carry another country's notice text (OP00265843 shows a Ghana award)."""
    parsed = parse_notice_text(record.get("notice_text") or "")
    project_id = _clean(record.get("project_id"))
    if parsed["project_id"] and parsed["project_id"] != project_id:
        return None
    return Notice(
        id=_clean(record.get("id")),
        project_id=project_id,
        project_name=_clean(record.get("project_name")),
        ref=norm_ref(record.get("bid_reference_no") or parsed["ref"]),
        description=_clean(record.get("bid_description")),
        group=_clean(record.get("procurement_group")),
        method=" ".join(
            _clean(record.get(k)) for k in ("procurement_method_code", "procurement_method_name")
        ),
        notice_date=_date(record.get("noticedate")) or _date(record.get("submission_date")),
        signature_date=parsed["signature_date"],
        notification_date=parsed["notification_date"],
        version=parsed["version"],
        contract_ref=norm_ref(parsed["ref"]),
        bidders=parsed["bidders"],
    )


# --- Finances One -------------------------------------------------------------------------


@dataclass
class FoneRow:
    ref: str
    project_id: str
    project_name: str
    description: str
    signing_date: date | None
    category: str
    method: str
    supplier: str
    amount_usd: Decimal | None
    contract_no: str


def parse_fone(record: dict) -> FoneRow | None:
    ref = norm_ref(record.get("borrower_contract_reference_number"))
    if not ref:
        return None
    amount = record.get("supplier_contract_amount_usd", record.get("supplier_contract_amount"))
    return FoneRow(
        ref=ref,
        project_id=_clean(record.get("project_id")),
        project_name=_clean(record.get("project_name")),
        description=_clean(record.get("contract_description")),
        signing_date=_date(record.get("contract_signing_date")),
        category=_clean(record.get("procurement_category")),
        method=_clean(record.get("procurement_method")),
        supplier=_clean(record.get("supplier")),
        amount_usd=_dec(amount),
        contract_no=_clean(record.get("wb_contract_number") or record.get("contract_number")),
    )


# --- STEP procurement plans ---------------------------------------------------------------


@dataclass
class PlanActivity:
    ref: str
    section: str  # works | goods | services | consultancy
    description_lines: list[str]
    method: str = ""
    market_approach: str = ""
    estimated: Decimal | None = None
    actual: Decimal | None = None
    status: str = ""
    invitation: date | None = None
    opening: date | None = None
    signed: date | None = None
    project_id: str = ""
    doc_date: date | None = None
    url: str = ""
    agency: str = ""


_PLAN_SECTIONS = {
    "WORKS": "works",
    "GOODS": "goods",
    "NON CONSULTING SERVICES": "services",
    "CONSULTING FIRMS": "consultancy",
    "INDIVIDUAL CONSULTANTS": "consultancy",
}
# Header slug fragment -> field. Milestones are (Planned, Actual) column pairs: the
# header sits over Planned, Actual is the next column.
_PLAN_COLUMNS = [
    ("activityreference", "ref_desc"),
    ("estimatedam", "estimated"),
    ("actualam", "actual"),
    ("processstatus", "status"),
    ("marketapproach", "market_approach"),
    ("method", "method"),
]
_PLAN_MILESTONES = [
    ("specificprocurementnotice", "invitation"),
    ("expressionofinterest", "invitation"),
    ("invitationtoidentified", "invitation"),
    ("proposalsubmission", "opening"),
    ("openingoftechnical", "opening"),
    ("signedcontract", "signed"),
]


def _cell(value) -> str:
    """Cells wrap at any character and drop the space at the wrap, so lines join with
    nothing; descriptions get a word-aware join later (join_wrapped)."""
    return "".join((value or "").split("\n")).strip()


def _slug(value) -> str:
    return re.sub(r"[^a-z]", "", _cell(value).lower())


def _plan_columns(header: list) -> dict[str, int]:
    cols: dict[str, int] = {}
    for i, cell in enumerate(header):
        slug = _slug(cell)
        if not slug:
            continue
        for fragment, name in _PLAN_COLUMNS:
            if slug.startswith(fragment) and name not in cols:
                cols[name] = i
                break
        else:
            for fragment, name in _PLAN_MILESTONES:
                if slug.startswith(fragment) and name not in cols:
                    cols[name] = i + 1  # the Actual column
                    break
    return cols


_REF_SPLIT = (re.compile(r"\s+/\s+"), re.compile(r"/\s+"))


def split_ref(cell: str) -> tuple[str, list[str]]:
    """'IN-X-145628-CW-RFB\\n/ Reconstruction of\\nJetties' -> (ref, description lines)."""
    text = (cell or "").strip()
    for rx in _REF_SPLIT:
        m = rx.search(text)
        if m:
            ref = norm_ref("".join(text[: m.start()].split("\n")))
            return ref, [x for x in text[m.end() :].split("\n") if x.strip()]
    return norm_ref("".join(text.split("\n"))), []


def join_wrapped(lines: list[str], vocab: frozenset[str] | set[str] = frozenset()) -> str:
    """Joins character-wrapped lines. Without a vocabulary every wrap is mid-word (the
    common case); with one, a wrap between two known words that do not form a known word
    together gets its space back ("Renovation|of" vs "Gangway c|um")."""
    if not lines:
        return ""
    out = lines[0].strip()
    for nxt in lines[1:]:
        nxt = nxt.strip()
        tail, head = re.search(r"[A-Za-z]+$", out), re.match(r"[A-Za-z]+", nxt)
        sep = ""
        if vocab and tail and head:
            t, h = tail.group().lower(), head.group().lower()
            if t + h not in vocab and t in vocab and h in vocab:
                sep = " "
        out += sep + nxt
    return _clean(out)


def parse_plan_pdf(source: Path | bytes) -> tuple[str, list[PlanActivity]]:
    """(implementing agency, activities) from a STEP plan PDF. The tables are found with
    pymupdf's ruling-line detection; a table without a header continues the previous one
    (STEP repeats the section title and header only where a section starts). Plans in
    pre-STEP layouts yield no activities."""
    import pymupdf  # heavy; only plan parsing needs it

    doc = (
        pymupdf.open(stream=source, filetype="pdf")
        if isinstance(source, bytes)
        else (pymupdf.open(source))
    )
    agency, out = "", []
    section, cols = "", {}
    try:
        for pno, page in enumerate(doc):
            text = page.get_text()
            if pno < 3 and not agency:
                m = re.search(r"Implementation agency\s*:\s*([^\n]+)", text, re.I)
                agency = _clean(m.group(1)) if m else ""
            if not cols and "Activity Reference" not in text:
                continue  # the textual part: no tables worth detecting
            for table in page.find_tables().tables:
                for row in table.extract():
                    first = _cell(row[0]) if row else ""
                    if first.upper() in _PLAN_SECTIONS:
                        section, cols = _PLAN_SECTIONS[first.upper()], {}
                        continue
                    if _slug(first).startswith("activityreference"):
                        cols = _plan_columns(row)
                        continue
                    if not cols or not first or "ref_desc" not in cols:
                        continue
                    activity = _plan_row(row, cols, section)
                    if activity:
                        out.append(activity)
    finally:
        doc.close()
    return agency, out


def _plan_row(row: list, cols: dict[str, int], section: str) -> PlanActivity | None:
    def get(name: str) -> str:
        i = cols.get(name)
        return _cell(row[i]) if i is not None and i < len(row) else ""

    ref, lines = split_ref(row[cols["ref_desc"]] or "")
    estimated, actual = _dec(get("estimated")), _dec(get("actual"))
    if not ref or (estimated is None and actual is None):
        return None
    return PlanActivity(
        ref=ref,
        section=section,
        description_lines=lines,
        method=get("method"),
        market_approach=get("market_approach"),
        estimated=estimated,
        actual=actual,
        status=get("status").lower(),
        invitation=_date(get("invitation")),
        opening=_date(get("opening")),
        signed=_date(get("signed")),
    )


# --- merge --------------------------------------------------------------------------------


def latest_notices(notices: Iterable[Notice]) -> dict[str, list[Notice]]:
    """Per activity key, one notice per contract. Amendments of one award (same contract
    reference in the notice text, same winners) replace each other: highest version, then
    the newest notice. Several contracts under one activity reference (Himachal's batches
    of small RFQ works, lots awarded separately) stay separate."""
    by_key: dict[str, dict[tuple, Notice]] = defaultdict(dict)
    for n in notices:
        key = merge_key(n.project_id, n.ref)
        if not key:
            continue
        winners = tuple(sorted(normalise(b.name) for b in n.awarded)) or (n.id,)
        contract = (re.sub(r"\s+", "", n.contract_ref), winners)
        best = by_key[key].get(contract)
        rank = (n.version, n.notice_date or date.min, n.id)
        if best is None or rank > (best.version, best.notice_date or date.min, best.id):
            by_key[key][contract] = n
    return {k: list(v.values()) for k, v in by_key.items()}


@dataclass
class Contract:
    """One signed contract inside an activity: its award notice and/or Finances One rows."""

    notice: Notice | None
    fone: list[FoneRow] = field(default_factory=list)


def split_contracts(
    notices: list[Notice],
    fone: list[FoneRow],
    fx: Callable[[int], float | None] = lambda year: None,
) -> list[Contract]:
    """Each standing notice is one contract. A Finances One row joins the notice whose
    winner it names, else the notice whose signed price it matches at the year's rate.
    Rows left over are the lots of a single notice when their total matches its price (or
    no rate is known to check), else contracts of their own (jobs with no notice).
    Without notices, all rows are one contract's lots."""
    rows = list({f.contract_no or f"{f.supplier}|{f.amount_usd}": f for f in fone}.values())
    if not notices:
        return [Contract(None, rows)] if rows else []
    out = [Contract(n) for n in notices]
    names = [{normalise(b.name) for b in n.awarded} for n in notices]
    left = []
    for f in rows:
        supplier = normalise(f.supplier)
        i = next((i for i, ns in enumerate(names) if supplier in ns), None)
        if i is None:
            left.append(f)
        else:
            out[i].fone.append(f)
    for c in out:
        expected = None if c.fone or not left else _contract_usd(c, fx)
        if expected:
            best = min(left, key=lambda f: abs(_log_ratio(f.amount_usd, expected)))
            if _consistent(best.amount_usd, expected):
                c.fone.append(best)
                left.remove(best)
    if left and len(out) == 1 and not out[0].fone:
        expected = _contract_usd(out[0], fx)
        total = sum((f.amount_usd for f in left if f.amount_usd), Decimal(0))
        if expected is None or _consistent(total, expected):
            out[0].fone, left = left, []
    out.extend(Contract(None, [f]) for f in left)
    return out


def _log_ratio(a: Decimal | None, b: Decimal) -> float:
    return math.log(float(a) / float(b)) if a else math.inf


def _consistent(amount: Decimal | None, expected: Decimal) -> bool:
    lo, hi = RATE_TOLERANCE
    return bool(amount) and lo <= float(amount) / float(expected) <= hi


def _usd_rate(
    award_usd: Decimal, local: Decimal, currency: str, fx: float | None
) -> Decimal | None:
    """USD per unit of the notice currency implied by this contract, or None when the two
    amounts cannot be the same contract."""
    rate = award_usd / local
    if currency == "USD":
        expected = 1.0
    elif currency == "INR" and fx:
        expected = 1 / fx
    elif currency == "INR":
        lo, hi = INR_PER_USD_BAND
        return rate if 1 / hi <= rate <= 1 / lo else None
    else:
        return None
    lo, hi = RATE_TOLERANCE
    return rate if lo <= float(rate) / expected <= hi else None


def merge(
    notices: dict[str, list[Notice]],
    fone: dict[str, list[FoneRow]],
    plans: dict[str, PlanActivity],
    *,
    fx: Callable[[int], float | None] = lambda year: None,
    vocab: frozenset[str] | set[str] = frozenset(),
    since: int | None = None,
    stats: Counter | None = None,
) -> Iterator[AwardRow]:
    """AwardRows for every activity key seen in any feed. A row is the unit at which an
    award meets an estimate: the plan activity when the plan estimates it (several
    contracts under it are summed, without a bid ladder), otherwise each contract. A
    planned activity alone is not an award: it needs an award amount, a notice or a
    Finances One row."""
    stats = stats if stats is not None else Counter()
    for key in sorted(set(notices) | set(fone) | set(plans)):
        plan = plans.get(key)
        parts = split_contracts(notices.get(key, []), fone.get(key, []), fx)
        if len(parts) <= 1:
            rows = [_row(key, parts, plan, fx, vocab, stats)]
        elif plan and plan.estimated:
            stats["activities_summed"] += 1
            rows = [_row(key, parts, plan, fx, vocab, stats)]
        else:
            stats["activities_split"] += 1
            rows = [_row(key, [p], None, fx, vocab, stats, lot=True) for p in parts]
            _unique_lot_ids(rows, parts)
        for row in rows:
            if row is None:
                stats["plan_only_unawarded"] += 1
                continue
            day = row.award_date or row.tender_date
            if since and (day is None or day.year < since):
                stats["before_since"] += 1
                continue
            stats["rows"] += 1
            stats["with_estimate"] += row.estimated_value is not None
            stats["with_award"] += row.award_value is not None
            stats["with_ratio_inputs"] += bool(row.estimated_value and row.award_value)
            stats["with_bids"] += bool(row.bids)
            stats["with_notice"] += "procurement-detail" in row.url
            yield row


def _unique_lot_ids(rows: list[AwardRow | None], parts: list[Contract]) -> None:
    """Two contracts of one activity can share a suffix (the same winner twice, or none):
    those get their notice id or Finances One contract number appended."""
    seen = Counter(r.source_id for r in rows if r)
    for row, part in zip(rows, parts, strict=True):
        if row and seen[row.source_id] > 1:
            own = part.notice.id if part.notice else (part.fone[0].contract_no if part.fone else "")
            row.source_id = f"{row.source_id}-{own}"


def _contract_usd(c: Contract, fx: Callable[[int], float | None]) -> Decimal | None:
    """A contract's award in USD: Finances One's amount, else the notice's signed rupees at
    the year's average rate (contracts Finances One misses: FY2017-19, small ones)."""
    total = sum((f.amount_usd for f in c.fone if f.amount_usd), Decimal(0))
    if total:
        return total
    n = c.notice
    if not n or not n.awarded:
        return None
    currencies = {b.currency for b in n.awarded}
    local = sum((b.signed or b.price() or 0 for b in n.awarded), Decimal(0))
    day = n.signature_date or n.notification_date or n.notice_date
    if not local or len(currencies) != 1:
        return None
    currency = currencies.pop()
    if currency == "USD":
        return local
    rate = fx(day.year) if currency == "INR" and day else None
    return (local / Decimal(str(rate))).quantize(Decimal("0.01")) if rate else None


def _row(
    key: str,
    parts: list[Contract],
    plan: PlanActivity | None,
    fx: Callable[[int], float | None],
    vocab,
    stats: Counter,
    *,
    lot: bool = False,
) -> AwardRow | None:
    notices = [c.notice for c in parts if c.notice]
    fone = [f for c in parts for f in c.fone]
    if not notices and not fone and not (plan and plan.actual):
        return None
    fone_main = max(fone, key=lambda f: f.amount_usd or 0, default=None)
    notice = max(notices, key=lambda n: (n.notice_date or date.min, n.id), default=None)
    winners = [b for n in notices for b in n.awarded]

    award_usd = None
    if plan and plan.actual and plan.status in AWARDED_STATUSES:
        award_usd, stats["award_from_plan"] = plan.actual, stats["award_from_plan"] + 1
    elif parts:
        amounts = [_contract_usd(c, fx) for c in parts]
        if all(amounts):
            award_usd = sum(amounts, Decimal(0))
            stats["award_from_fone" if fone else "award_from_notice_fx"] += 1
    if award_usd is None and not notices and not fone:
        return None

    award_date = (
        min((n.signature_date for n in notices if n.signature_date), default=None)
        or min((f.signing_date for f in fone if f.signing_date), default=None)
        or (plan.signed if plan else None)
        or min((n.notification_date for n in notices if n.notification_date), default=None)
    )
    tender_date = (plan.opening or plan.invitation) if plan else None
    day = award_date or tender_date or (notice.notice_date if notice else None)
    year = day.year if day else None

    ref = (notice.ref if notice else "") or (fone_main.ref if fone_main else "") or plan.ref
    project_id = (
        (notice.project_id if notice else "")
        or (fone_main.project_id if fone_main else "")
        or (plan.project_id if plan else "")
    )
    project_name = (notice.project_name if notice else "") or (
        fone_main.project_name if fone_main else ""
    )
    source_id = ref if _STEP_REF.search(key) else f"{project_id}/{ref}"
    winner = (
        max(winners, key=lambda b: b.signed or b.price() or 0).name
        if winners
        else (fone_main.supplier if fone_main else "")
    )
    if lot:  # one contract of several under this reference
        own = re.sub(r"\s+", "", notice.contract_ref) if notice else ""
        suffix = own if own and own != re.sub(r"\s+", "", ref) else normalise(winner).upper()
        source_id = f"{source_id}#{suffix}"

    # Bids: one contract, one winner, one currency, a plausible implied rate.
    methods = [notice.method if notice else "", plan.method if plan else ""]
    is_scored = any(method_of(m) == "qcbs" for m in methods) or (
        category_of(ref, notice.group if notice else "") == "consultancy"
    )
    single = len(parts) == 1 and len(notices) == 1
    bidders = {normalise(b.name): b for b in notice.evaluated} if single else {}
    bids = None
    currencies = {b.currency for b in winners}
    local = sum((b.signed or b.price() or 0 for b in winners), Decimal(0))
    if single and award_usd and local and len(winners) == 1 and len(currencies) == 1:
        currency = currencies.pop()
        rate = _usd_rate(award_usd, local, currency, fx(year) if year else None)
        if rate is None:
            stats["bids_dropped_rate_mismatch"] += 1
        elif not is_scored:
            prices = [b.price() if b.currency == currency else None for b in bidders.values()]
            if all(prices):  # a bidder in another currency or without a price: no ladder
                bids = [float(round(p * rate, 2)) for p in prices]

    title = (
        (notice.description if notice else "")
        or (fone_main.description if fone_main else "")
        or (join_wrapped(plan.description_lines, vocab) if plan else "")
    )
    agency = plan.agency if plan else ""
    method = ""
    for texts in (
        [plan.method, plan.market_approach] if plan else [],
        [notice.method] if notice else [],
        [fone_main.method] if fone_main else [],
    ):
        method = method_of(*texts)
        if method and method != "other":
            break
    category = category_of(
        ref,
        notice.group if notice else "",
        plan.section if plan else "",
        fone_main.category if fone_main else "",
    )
    if notice:
        url = NOTICE_PAGE.format(notice.id)
    elif plan and plan.url:
        url = plan.url
    else:
        url = PROJECT_PAGE.format(project_id) if project_id else ""
    return AwardRow(
        source_id=source_id,
        country="IN",
        state=find_state(project_name, fone_main.project_name if fone_main else "", title, agency),
        buyer=agency or project_name,
        title=title,
        category=category,
        method=method,
        currency="USD",
        estimated_value=plan.estimated if plan else None,
        award_value=award_usd,
        num_bidders=(len(bidders) or None) if single else None,
        bids=bids,
        winner=winner,
        tender_date=tender_date,
        award_date=award_date,
        url=url,
    )


def build_vocab(texts: Iterable[str]) -> frozenset[str]:
    """Lower-case words seen at least twice in the clean descriptions (notices, Finances
    One): enough to tell a wrap between words from a wrap inside one."""
    counts = Counter(w for t in texts for w in re.findall(r"[a-z]+", (t or "").lower()))
    return frozenset(w for w, n in counts.items() if n >= 2)


# --- the adapter --------------------------------------------------------------------------


@register
class WorldBankIndia(Source):
    """`--file` takes either a directory laid out like the cache
    (data/intel/raw/worldbank_in/: notices/, fone/, plans/), read without touching the
    network, or one file: a notices API page (JSON with "procnotices"), a Finances One page
    (JSON with "data") or a STEP plan PDF (project id taken from a "P123456" in its name).
    `--limit` also bounds the downloads (pages and plan documents), for smoke runs."""

    key = "worldbank_in"
    name = "World Bank: India contract awards, bids and STEP plan estimates"
    url = "https://projects.worldbank.org/en/projects-operations/procurement?srce=both&countrycode_exact=IN"
    license = (
        "World Bank Terms of Use; Finances One datasets CC BY 4.0; documents CC BY 3.0 IGO. "
        "Attribution: The World Bank."
    )
    kind = "outcomes"
    min_interval_seconds = 0.5

    def rows(self, ctx: ImportContext) -> Iterator[AwardRow]:
        feeds = _Feeds(ctx)
        notices = latest_notices(feeds.notices())
        fone: dict[str, list[FoneRow]] = defaultdict(list)
        for f in feeds.fone():
            fone[merge_key(f.project_id, f.ref)].append(f)
        plans = feeds.plans()
        inr_per_usd = Deflator.load().fx.get("IN") or {}  # empty: rates not loaded yet
        vocab = build_vocab(
            [n.description for ns in notices.values() for n in ns]
            + [f.description for fs in fone.values() for f in fs]
        )
        stats = Counter(feeds.stats)
        yield from merge(
            notices, fone, plans, fx=inr_per_usd.get, vocab=vocab, since=ctx.since, stats=stats
        )
        log.info("worldbank_in: %s", dict(stats))
        self.last_stats = dict(stats)


class _Feeds:
    """Downloads (or reads from the cache / --file) the three feeds."""

    def __init__(self, ctx: ImportContext):
        self.ctx = ctx
        self.root = ctx.cache_dir
        self.offline = False
        self.single: Path | None = None
        self.stats: Counter = Counter()
        self._last_document = 0.0
        if ctx.file:
            if ctx.file.is_dir():
                self.root, self.offline = ctx.file, True
            else:
                self.single, self.offline = ctx.file, True

    # -- plumbing

    def _fetch(self, url: str, name: str, *, document: bool = False) -> Path | None:
        path = self.root / name
        if path.exists() and (self.offline or not self.ctx.refresh):
            self.ctx.record_file(url, path)
            return path
        if self.offline:
            return None
        if document:  # documents1.worldbank.org: half the API rate
            interval = self.ctx.min_interval * DOCUMENT_INTERVAL_FACTOR
            delay = interval - (time.monotonic() - self._last_document)
            if delay > 0:
                time.sleep(delay)
            self._last_document = time.monotonic()
        try:
            resp = self.ctx.get(url)
        except httpx.HTTPStatusError as exc:
            if document and exc.response.status_code in {403, 404, 410}:
                log.warning("worldbank_in: %s: HTTP %s", url, exc.response.status_code)
                self.stats["plan_missing"] += 1
                return None
            raise
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(resp.content)
        tmp.replace(path)
        self.ctx.record_file(url, path)
        return path

    def _single_json(self) -> dict | None:
        if self.single and self.single.suffix.lower() == ".json":
            return json.loads(self.single.read_text())
        return None

    def _pages(self, url_fmt: str, prefix: str, rows: int, items: Callable[[dict], list]):
        """Every page of a paged JSON API, cached as <prefix>-<offset>.json."""
        offset, total = 0, None
        while total is None or offset < total:
            path = self._fetch(
                url_fmt.format(rows=rows, offset=offset), f"{prefix}-{offset:06d}.json"
            )
            if path is None:
                return
            payload = json.loads(path.read_text())
            batch = items(payload)
            total = int(payload.get("total") or payload.get("count") or 0)
            yield from batch
            if not batch:
                return
            offset += rows
            if self.ctx.limit and offset >= self.ctx.limit:
                return

    # -- feeds

    def notices(self) -> Iterator[Notice]:
        single = self._single_json()
        if self.single and (single is None or "procnotices" not in single):
            return
        records = (
            single["procnotices"]
            if single
            else self._pages(
                NOTICES_URL, "notices/page", PAGE_ROWS, lambda p: p.get("procnotices") or []
            )
        )
        seen = set()
        for record in records:
            if record.get("id") in seen:
                continue  # a notice published mid-paging shifts the pages by one
            seen.add(record.get("id"))
            self.stats["notices"] += 1
            notice = parse_notice(record)
            if notice is None:
                self.stats["notices_contaminated"] += 1
                continue
            yield notice

    def fone(self) -> Iterator[FoneRow]:
        single = self._single_json()
        if self.single and (single is None or "data" not in single):
            return
        if single:
            records: Iterable[dict] = single["data"]
        else:
            records = (
                r
                for dataset, resource in FONE_DATASETS
                for r in self._pages(
                    FONE_URL.replace("{dataset}", dataset).replace("{resource}", resource),
                    f"fone/{dataset}",
                    FONE_ROWS,
                    lambda p: p.get("data") or [],
                )
            )
        for record in records:
            if (record.get("borrower_country") or "India") != "India":
                continue
            self.stats["fone_rows"] += 1
            row = parse_fone(record)
            if row:
                yield row

    def plans(self) -> dict[str, PlanActivity]:
        """Newest plan first per project; the first plan that lists a reference wins."""
        if self.single and self.single.suffix.lower() == ".pdf":
            m = re.search(r"P\d{6}", self.single.name)
            docs = [
                {
                    "projectid": m.group() if m else "",
                    "docdt": "",
                    "pdfurl": "",
                    "_path": self.single,
                }
            ]
        elif self.single:
            return {}
        else:
            docs = list(self._pages(PLANS_URL, "plans/index", PAGE_ROWS, _plan_docs))
        by_project: dict[str, list[dict]] = defaultdict(list)
        for d in docs:
            by_project[_clean(d.get("projectid")) or "?"].append(d)
        out: dict[str, PlanActivity] = {}
        budget = self.ctx.limit
        for project_id in sorted(by_project):
            versions = sorted(
                by_project[project_id],
                key=lambda d: (d.get("docdt") or "", d.get("id") or ""),
                reverse=True,
            )
            redundant = empty = 0
            for d in versions:
                doc_date = _date(d.get("docdt"))
                if self.ctx.since and doc_date and doc_date.year < self.ctx.since:
                    break  # an older plan cannot list contracts signed after it
                if budget is not None and budget <= 0:
                    break
                path = d.get("_path") or self._plan_pdf(project_id, d)
                if path is None:
                    continue
                if budget is not None:
                    budget -= 1
                try:
                    agency, activities = parse_plan_pdf(path)
                except Exception as exc:  # a corrupt or non-PDF download: skip the document
                    log.warning("worldbank_in: plan %s unreadable: %s", path.name, exc)
                    self.stats["plan_unreadable"] += 1
                    continue
                self.stats["plan_docs"] += 1
                if not activities:
                    self.stats["plan_docs_without_step_tables"] += 1
                    empty += 1
                    if empty >= PLAN_STOP_AFTER_EMPTY:
                        break
                    continue
                empty = 0
                new = 0
                for a in activities:
                    key = merge_key(project_id, a.ref)
                    if key and key not in out:
                        a.project_id, a.doc_date, a.agency = project_id, doc_date, agency
                        a.url = _https(d.get("pdfurl") or "")
                        out[key] = a
                        new += 1
                self.stats["plan_activities"] += new
                redundant = 0 if new else redundant + 1
                if redundant >= PLAN_STOP_AFTER_REDUNDANT:
                    break
        self.stats["plan_projects"] = len(by_project)
        return out

    def _plan_pdf(self, project_id: str, doc: dict) -> Path | None:
        url = _https(doc.get("pdfurl") or "")
        if not url:
            return None
        name = re.sub(r"[^\w.-]+", "_", url.rsplit("/", 1)[-1])[:150]
        return self._fetch(url, f"plans/{project_id}/{doc.get('id') or ''}-{name}", document=True)


def _plan_docs(payload: dict) -> list[dict]:
    docs = payload.get("documents") or {}
    return [
        {**v, "id": v.get("id") or k}
        for k, v in docs.items()
        if k != "facets" and isinstance(v, dict)
    ]


def _https(url: str) -> str:
    """The API lists http://documents.worldbank.org/...; the PDFs live on documents1."""
    return re.sub(r"^https?://documents\.worldbank\.org/", "https://documents1.worldbank.org/", url)
