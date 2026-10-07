"""PMGSY (Pradhan Mantri Gram Sadak Yojana) rural road works, sanctioned 2000-01 onwards,
from the India Data Portal's (ISB) copy of the OMMAS "Financial and Physical Report".

Kind "history": `total_cost` is the *sanctioned* cost in lakh rupees, i.e. the estimate,
not the contract price, so rows carry `estimated_value` only and never a ratio. They feed
market history and the competitor radar: who builds rural roads where, how often, how big.

The CSV is not one row per contract. It has one row per habitation a road serves, and a
road appears again for every contract awarded on it (a re-award after termination, or a
package split between contractors). The unit here is one award on one road: rows are
grouped by (state, package, road, award date), so habitations collapse into their road and
a re-awarded road keeps both awards. Spelling variants of the contractor within one award
("M/s. Tirumala Constructions" / "M/S Thirumala Constructions") take the most common one.
"""

import csv
import hashlib
import html
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from intel.sources.base import AwardRow, ImportContext, Source, parse_amount, register
from tenders.pincode import ALL_STATES

DOWNLOAD_URL = (
    "https://ckandev.indiadataportal.com/dataset/ca23895a-ed8b-438c-aa6e-c5a89b6b8dce/"
    "resource/14c4a773-61bb-4cc3-9ba5-fc21e16fe8d7/download/pmgsy-financial-and-physical-report.csv"
)
DATASET_URL = "https://ckandev.indiadataportal.com/dataset/pradhan-mantri-gram-sadak-yojana-pmgsy"
COLUMNS = {
    "id",
    "state_name",
    "state_code",
    "district_name",
    "road_name",
    "packages",
    "upgrade_or_new",
    "contractor_name",
    "company_name",
    "sanctioned_year",
    "work_award_date",
    "total_cost",
}
_NULLS = {"", "none", "nan", "na", "n/a", "null", "0", "0.0", "-"}
_KEPT = ("state_name", "district_name", "road_name", "upgrade_or_new")
_STATES = {s.lower(): s for s in ALL_STATES}
_DATE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")
# The first works were sanctioned in financial year 2000-01 (the scheme was launched in
# December 2000): an earlier date or year is a typo or a placeholder such as 1-1-2000.
FIRST_DAY = date(2000, 4, 1)
# Below 1 lakh (Rs 1,00,000) a "road" cost is a unit or entry error (0.01 lakh occurs).
MIN_COST = Decimal(100_000)
# Values in the contractor columns that are not a contractor: budget heads ("BMS",
# "BMS EXPENDITURE", "BMS-07": Uttar Pradesh), design cells, entry noise. A registered
# company that happens to start with BMS is kept, and so is departmental execution
# ("PWD Sikkim"): a public works wing really did build the road.
_NOT_A_WINNER = re.compile(
    r"(?i)^(bms(?!.*\b(private|pvt|ltd|limited)\b).*|.*expenditure.*|project\s*and\s*design"
    r"|no|nil|n\.?a\.?)$"
)


def _clean(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value.lower() in _NULLS else value


def _award_date(text: str) -> date | None:
    """'3-4-2002' / '27-06-2004' (day-month-year, any width) -> date; None for 'None' and
    impossible or out-of-range dates."""
    m = _DATE.fullmatch(_clean(text))
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    return parsed if FIRST_DAY <= parsed <= date.today() else None


def _sanction_year(text: str) -> int | None:
    """'2008-2009' -> 2008 (Indian financial year start)."""
    m = re.match(r"(\d{4})", _clean(text))
    year = int(m.group(1)) if m else None
    return year if year and FIRST_DAY.year <= year <= date.today().year else None


def _winner(text: str | None) -> str:
    """'M/s L.N. Agarwal..' -> 'M/s L.N. Agarwal'; '' for placeholders and noise."""
    name = re.sub(r"\s+", " ", html.unescape(_clean(text)))
    name = re.sub(r"[\s.,;:-]+$", "", name)
    if len(re.sub(r"[^A-Za-z]", "", name)) < 3 or _NOT_A_WINNER.match(name):
        return ""
    return name


def _cost(text: str | None) -> Decimal | None:
    cost = parse_amount(_clean(text) or None, unit="lakh")
    return cost if cost is not None and cost >= MIN_COST else None


def _state(name: str) -> str:
    name = _clean(name)
    return _STATES.get(name.lower(), name)


@dataclass
class _Award:
    """The rows of one award on one road, reduced as they stream past."""

    key: str
    first: dict
    award_date: date | None
    winners: Counter = field(default_factory=Counter)
    costs: Counter = field(default_factory=Counter)  # (sanction year, cost) -> rows


def _key(row: dict, award: date | None) -> str:
    road = _clean(row["road_name"])
    # A road without a name cannot be told apart from its package's other roads: keep each
    # habitation row on its own rather than merge unrelated roads.
    road_part = (
        hashlib.sha1(re.sub(r"\s+", " ", road.lower()).encode()).hexdigest()[:12]
        if road
        else f"row{row['id']}"
    )
    package = _clean(row["packages"]) or "-"
    return f"{_clean(row['state_code']) or '-'}:{package}:{road_part}:{award or '-'}"


def _sanction(costs: Counter, award_year: int | None) -> tuple[int | None, Decimal | None]:
    """(sanction year, sanctioned cost) behind an award. A re-sanctioned road has several
    pairs: use the latest sanction not after the award, else the latest one; within a year
    the most common cost. Pairs with a cost win over pairs without."""
    pairs = [(y, c, n) for (y, c), n in costs.items()]
    priced = [p for p in pairs if p[1] is not None] or pairs
    before = [p for p in priced if award_year and p[0] and p[0] <= award_year]
    year, cost, _ = max(before or priced, key=lambda p: (p[0] or 0, p[1] is not None, p[2]))
    return year, cost


@register
class Pmgsy(Source):
    key = "pmgsy"
    name = "PMGSY rural roads (India Data Portal, OMMAS)"
    url = DATASET_URL
    license = (
        "ODC-BY 1.0 (Open Data Commons Attribution). Source: Ministry of Rural Development, "
        "OMMAS; via India Data Portal (ISB)."
    )
    kind = "history"
    min_interval_seconds = 1.0

    def rows(self, ctx: ImportContext) -> Iterator[AwardRow]:
        path = ctx.file or ctx.download(DOWNLOAD_URL)
        if ctx.file:
            ctx.record_file(str(ctx.file), Path(ctx.file))
        for award in self._awards(path):
            row = self._to_row(award)
            year = row.award_date.year if row.award_date else row.year
            if ctx.since and (year or 0) < ctx.since:
                continue
            yield row

    def _awards(self, path: Path) -> Iterator[_Award]:
        """Groups the habitation rows; the file is not sorted by road, so this holds one
        small record per award (~200k) rather than streaming."""
        groups: dict[str, _Award] = {}
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            missing = COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"PMGSY CSV is missing columns: {', '.join(sorted(missing))}")
            for row in reader:
                award = _award_date(row["work_award_date"])
                key = _key(row, award)
                group = groups.get(key)
                if group is None:
                    first = {k: row[k] for k in _KEPT}  # not the whole row: ~190k groups
                    group = groups[key] = _Award(key=key, first=first, award_date=award)
                # The contractor column is only a fallback for a missing company: next to a
                # placeholder company ("PROJECT AND DESIGN") it names an engineer, not a firm.
                company = _clean(row["company_name"])
                winner = _winner(company) if company else _winner(row["contractor_name"])
                if winner:
                    group.winners[winner] += 1
                group.costs[(_sanction_year(row["sanctioned_year"]), _cost(row["total_cost"]))] += 1
        yield from groups.values()

    @staticmethod
    def _to_row(award: _Award) -> AwardRow:
        row = award.first
        award_year = award.award_date.year if award.award_date else None
        sanction_year, cost = _sanction(award.costs, award_year)
        road = _clean(row["road_name"])
        kind = _clean(row["upgrade_or_new"]).lower()
        title = f"{road} ({kind})" if road and kind else road or "PMGSY rural road"
        # most_common keeps first-seen order on ties, so the choice is deterministic.
        winner = award.winners.most_common(1)[0][0] if award.winners else ""
        return AwardRow(
            source_id=award.key,
            country="IN",
            state=_state(row["state_name"]),
            district=_clean(row["district_name"]),
            title=title,
            category="works",
            sector="roads",
            method="open",
            currency="INR",
            estimated_value=cost,
            award_value=None,
            winner=winner,
            tender_date=None,
            award_date=award.award_date,
            year=award_year or sanction_year,
            url=DATASET_URL,
        )
