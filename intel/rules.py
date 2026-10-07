"""Indian procurement rules that bound or reshape a bid, versioned by date and state.

The price model learns what bidders did; these rules say what a bid is allowed to cost
or risk on a given day. They do two things for the advisor: produce warnings with a
citation, and price the Additional Performance Security (APS) a deep discount triggers,
which the expected-profit calculation subtracts.

Every rule here was read in its primary text (or, where marked, a primary agency's tender
that applies it) on 2026-10-07; the citation travels with the warning. A tender's own NIT
always overrides these defaults: state PWDs and individual buyers vary, and some NITs even
contradict the department's latest memorandum (an April 2026 Odisha notice still printed
the abolished 15% cap). So the advisor's wording is "check the NIT", never "the law says".
"""

import re
from dataclasses import dataclass
from datetime import date

GFR = "https://iitk.ac.in/centralstores/data/GFR_2017_Amended_upto_31-07-2024.pdf"
DOE_ALB = "https://doe.gov.in/files/circulars_document/Additional_Performance_Security_ALBs.pdf"
ODISHA_OM_173 = (
    "https://gajapati.odisha.gov.in/sites/default/files/2026-04/"
    "Tender%20Call%20Notice%2001%202026-27.pdf"
)
MORTH_APS = (
    "https://indianinfrastructure.com/2025/05/02/"
    "morth-imposes-additional-security-performance-on-low-bids/"
)
NHIDCL_APS = "https://www.nhidcl.com/sites/default/files/corrigendum/corrigendumi_5.pdf"
MSE_FAQ = "https://www.dcmsme.gov.in/NewFAQs01022022.pdf"
MII_ORDER = (
    "https://tenders.bhel.com/sites/default/files/DoPIIT_MII_Circular-2024-07-27-04%3A02%3A07.pdf"
)

# Dates the regimes change.
MORTH_APS_FROM = date(2025, 4, 30)  # MoRTH circular of 30.04.2025 (tiers as NHIDCL applies them)
ODISHA_CAP_UNTIL = date(2026, 1, 3)  # Works Dept OM 173 abolished the 14.99% cap on this day
ODISHA_FLOOR_RATIO = 0.8501  # bids more than 15% below the estimate were rejected

LAKH = 100_000
GEM_BIDDING_ABOVE_INR = 10 * LAKH  # GFR Rule 149(iii) as amended 10.07.2024
MII_EXEMPT_BELOW_INR = 5 * LAKH  # DPIIT order of 16.09.2020
DEEP_DISCOUNT = 0.20  # beyond this, expect abnormally-low-bid scrutiny anywhere
STATE_APS_HINT = 0.10  # many state PWDs ask for extra security below this discount

# Financing cost of a bank guarantee, used to price APS in expected profit: commission per
# year times how long the guarantee is held (contract period plus defect liability). Both
# are assumptions, stated in the advice text; the APS percentage itself is the rule.
BG_COMMISSION_PER_YEAR = 0.015
BG_TENURE_YEARS = 3.0

_HIGHWAYS = re.compile(
    r"ministry of road transport|\bmorth\b|\bnhai\b|national highways? authority|nhidcl|"
    r"national highways? (?:and|&) infrastructure|\bnational highway\b|\bNH[- ]?\d",
    re.I,
)
_GEM = re.compile(r"\bgem\b|government e-?marketplace", re.I)


@dataclass(frozen=True)
class RuleContext:
    estimated_value_inr: float
    category: str = ""  # works | goods | services | consultancy
    state: str = ""
    buyer: str = ""  # buyer name / organisation chain
    title: str = ""
    method: str = ""  # HistoricalAward.Method value, if known
    source: str = ""  # tender source key ("gem" for GeM bids)
    on_date: date | None = None
    is_mse: bool | None = None  # the bidder's own status, from the company profile
    is_class1_local: bool | None = None


@dataclass(frozen=True)
class Finding:
    key: str
    severity: str  # "info" | "warn"
    message: str
    source: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "severity": self.severity,
            "message": self.message,
            "source": self.source,
        }


def _day(ctx: RuleContext) -> date:
    return ctx.on_date or date.today()


def is_highways(ctx: RuleContext) -> bool:
    return bool(_HIGHWAYS.search(f"{ctx.buyer} {ctx.title}"))


def tiered_aps_percent(ratio: float) -> float:
    """APS as % of the bid price under the tiered schedule MoRTH (30.04.2025) and Odisha
    (OM 173, 03.01.2026) share: nothing down to 10% below the estimate, 0.1% per point
    from 11% to 19% below, 1% + 0.2% per point from 20% below. The discount is rounded to
    the nearest whole percent first, as both texts say."""
    below = round((1.0 - ratio) * 100)
    if below <= 10:
        return 0.0
    if below < 20:
        return round(0.1 * (below - 10), 2)
    return round(1.0 + 0.2 * (below - 20), 2)


def aps_regime(ctx: RuleContext) -> str | None:
    """Which APS schedule binds this tender: "morth", "odisha", or None."""
    if ctx.category and ctx.category != "works":
        return None
    day = _day(ctx)
    if is_highways(ctx) and day >= MORTH_APS_FROM:
        return "morth"
    if ctx.state == "Odisha" and day >= ODISHA_CAP_UNTIL:
        return "odisha"
    return None


def aps_percent(ctx: RuleContext, ratio: float) -> float:
    return tiered_aps_percent(ratio) if aps_regime(ctx) else 0.0


def aps_cost_fraction(ctx: RuleContext, ratio: float) -> float:
    """Expected financing cost of the APS bank guarantee, as a fraction of the bid."""
    return aps_percent(ctx, ratio) / 100 * BG_COMMISSION_PER_YEAR * BG_TENURE_YEARS


def floor_ratio(ctx: RuleContext) -> float | None:
    """A hard lower limit on bid / estimate, or None. Only Odisha works before the cap was
    abolished had one; elsewhere deep bids are scrutinised, not barred."""
    if ctx.state == "Odisha" and ctx.category in ("", "works") and _day(ctx) < ODISHA_CAP_UNTIL:
        return ODISHA_FLOOR_RATIO
    return None


def evaluate(ctx: RuleContext, ratio: float | None = None) -> list[Finding]:
    """Warnings and notes for a tender, and for a bid at `ratio` (bid / estimate) when given."""
    out: list[Finding] = []
    category = ctx.category
    regime = aps_regime(ctx)

    if category == "consultancy" or ctx.method == "qcbs":
        out.append(
            Finding(
                "qcbs",
                "warn",
                "Consultancy is usually selected on quality and cost (QCBS), not lowest price: "
                "the price score is only part of the total, so treat this price advice as a "
                "rough guide and weigh your expected technical score.",
                GFR,
            )
        )

    if regime and ratio is not None:
        pct = tiered_aps_percent(ratio)
        who = "MoRTH national-highway" if regime == "morth" else "Odisha Works Department"
        src = NHIDCL_APS if regime == "morth" else ODISHA_OM_173
        if pct > 0:
            out.append(
                Finding(
                    "aps",
                    "warn",
                    f"At {round((1 - ratio) * 100)}% below the estimate, {who} rules ask for "
                    f"Additional Performance Security of {pct}% of the bid price on top of "
                    "the normal performance security. Check the NIT's own clause.",
                    src,
                )
            )
        else:
            out.append(
                Finding(
                    "aps_free_band",
                    "info",
                    f"{who} rules add no extra security for bids up to 10% below the "
                    "estimate; deeper discounts need Additional Performance Security.",
                    src,
                )
            )

    floor = floor_ratio(ctx)
    if floor is not None:
        out.append(
            Finding(
                "odisha_floor",
                "warn",
                "Before 3 January 2026, Odisha works bids more than 15% below the estimate "
                "were rejected, with a lottery among bids at 14.99% below.",
                ODISHA_OM_173,
            )
        )
    elif ctx.state == "Odisha" and category in ("", "works"):
        out.append(
            Finding(
                "odisha_cap_abolished",
                "info",
                "Odisha abolished its 15% negative-bid cap on 3 January 2026 (OM 173); some "
                "notices still print the old clause, so read the NIT carefully.",
                ODISHA_OM_173,
            )
        )

    if ratio is not None and ratio < 1 - DEEP_DISCOUNT:
        out.append(
            Finding(
                "abnormally_low",
                "warn",
                f"A bid {round((1 - ratio) * 100)}% below the estimate may be examined as an "
                "abnormally low bid: keep a rate analysis ready to justify it.",
                DOE_ALB,
            )
        )
    elif (
        ratio is not None
        and category == "works"
        and not regime
        and ratio < 1 - STATE_APS_HINT
        and ctx.state
    ):
        out.append(
            Finding(
                "state_aps",
                "info",
                "Many state public works departments ask for additional security when a bid "
                "is well below the estimate; check this NIT's performance-security clause.",
                DOE_ALB,
            )
        )

    if category in ("goods", "services"):
        if ctx.is_mse:
            msg = (
                "As an MSE you may be offered part of the order if your price is within 15% "
                "of the lowest bid and you match it, even when you are not L1."
            )
        else:
            msg = (
                "Micro and small enterprises quoting within 15% of the lowest bid may match "
                "it and take at least 25% of the order (100% if it cannot be split), so "
                "winning as L1 may not mean the whole contract."
            )
        out.append(Finding("mse_preference", "info", msg, MSE_FAQ))
        if ctx.estimated_value_inr >= MII_EXEMPT_BELOW_INR and ctx.is_class1_local is not True:
            out.append(
                Finding(
                    "make_in_india",
                    "info",
                    "Make in India: if the lowest bidder is not a Class-I local supplier, a "
                    "Class-I bidder within 20% may be invited to match and take half (or all) "
                    "of the order.",
                    MII_ORDER,
                )
            )

    gem = ctx.source == "gem" or ctx.method == "reverse_auction" or bool(_GEM.search(ctx.buyer))
    if gem and ctx.estimated_value_inr > GEM_BIDDING_ABOVE_INR:
        out.append(
            Finding(
                "reverse_auction",
                "info",
                "GeM purchases above Rs 10 lakh go through online bidding or a reverse "
                "auction. In a reverse auction, treat the advised price as your walk-away "
                "floor, not your opening bid.",
                GFR,
            )
        )
    return out
