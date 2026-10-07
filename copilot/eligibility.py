"""Eligibility: the tender's qualification criteria (from the Bid Brief) against the active
organisation's company profile.

Conservative on purpose. A wrong "pass" can cost a customer a bid fee, an EMD and weeks of
work, so a check passes only when both sides are known and the comparison is unambiguous;
anything else is "unknown" with a note saying what is missing. The verdict is "eligible"
only when every criterion passes, "not_eligible" when any one fails, and "unknown" otherwise.
Requirements stated only as a percentage of the estimated cost are not converted into an
amount (the brief never calculates), so they stay "unknown".
"""

import re
from decimal import Decimal

from copilot.brief import Field

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
MSE_CERTS = re.compile(r"\bMSEs?\b|MSME|udyam|NSIC|micro|small enterprise", re.I)
STARTUP_CERTS = re.compile(r"start-?up|DPIIT", re.I)
_YEARS = re.compile(
    r"(?:minimum|at\s+least|not\s+less\s+than)\s+(\d{1,2})\s+years?\s+(?:of\s+)?"
    r"(?:experience|existence|standing|in\s+(?:the\s+)?business)"
    r"|(?:experience|existence)\s+of\s+(?:at\s+least\s+|minimum\s+)?(\d{1,2})\s+years",
    re.I,
)


def inr(v: Decimal | None) -> str | None:
    """Indian digit grouping: 4918700000 -> ₹4,91,87,00,000."""
    if v is None:
        return None
    s = f"{int(v)}"
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join([*parts, tail]) if parts else f"₹{tail}"


def _source(f: Field | None) -> dict | None:
    if f is None:
        return None
    return {"document_id": f.document_id, "filename": f.filename, "page": f.page}


def _check(key, requirement, required, yours, status, f, note) -> dict:
    return {
        "key": key,
        "requirement": requirement,
        "required": required,
        "yours": yours,
        "status": status,
        "source": _source(f),
        "note": note,
    }


def _turnover(f: Field | None, org) -> dict:
    mine = org.annual_turnover_inr
    req = "Average annual turnover"
    if f is None:
        return _check(
            "min_turnover",
            req,
            None,
            inr(mine),
            UNKNOWN,
            None,
            "No turnover requirement was found in the documents; check them yourself.",
        )
    need = max(f.amounts) if f.amounts else None
    if need is None:
        return _check(
            "min_turnover",
            req,
            f.value,
            inr(mine),
            UNKNOWN,
            f,
            "The requirement is not stated as an amount.",
        )
    if mine is None:
        return _check(
            "min_turnover",
            req,
            f.value,
            None,
            UNKNOWN,
            f,
            "Add your average annual turnover to the company profile.",
        )
    ok = Decimal(mine) >= need
    return _check(
        "min_turnover",
        req,
        f.value,
        inr(mine),
        PASS if ok else FAIL,
        f,
        "" if ok else f"Your turnover is below the required {inr(need)}.",
    )


def _similar(f: Field | None, org) -> dict:
    mine = org.largest_similar_work_inr
    req = "Similar work completed"
    if f is None:
        return _check(
            "similar_work",
            req,
            None,
            inr(mine),
            UNKNOWN,
            None,
            "No similar-work requirement was found in the documents; check them yourself.",
        )
    if not f.amounts:
        return _check(
            "similar_work",
            req,
            f.value,
            inr(mine),
            UNKNOWN,
            f,
            "The requirement is not stated as an amount.",
        )
    if mine is None:
        return _check(
            "similar_work",
            req,
            f.value,
            None,
            UNKNOWN,
            f,
            "Add the value of your largest similar completed work to the company profile.",
        )
    mine = Decimal(mine)
    hi, lo = max(f.amounts), min(f.amounts)
    if mine >= hi:  # one work of the largest amount satisfies every option
        return _check("similar_work", req, f.value, inr(mine), PASS, f, "")
    if mine < lo:
        return _check(
            "similar_work",
            req,
            f.value,
            inr(mine),
            FAIL,
            f,
            f"Your largest similar work is below the smallest amount asked for ({inr(lo)}).",
        )
    return _check(
        "similar_work",
        req,
        f.value,
        inr(mine),
        UNKNOWN,
        f,
        "Depends on how many similar works of this size you have completed; check the clause.",
    )


def _years(pages_text: list[tuple[Field | None, str]], org) -> dict | None:
    """Only when the documents ask for a minimum number of years in business/experience."""
    for f, text in pages_text:
        m = _YEARS.search(text)
        if m:
            need = int(m.group(1) or m.group(2))
            mine = org.years_in_business
            requirement = m.group(0)
            if mine is None:
                status, note = UNKNOWN, "Add your years in business to the company profile."
            else:
                status = PASS if mine >= need else FAIL
                note = "" if status == PASS else f"The documents ask for {need} years."
            yours = None if mine is None else f"{mine} years"
            return _check("years", "Years of experience", requirement, yours, status, f, note)
    return None


def _exemption(f: Field | None, org) -> dict | None:
    if f is None:
        return None
    certs = " ".join(org.certifications or [])
    has = bool(MSE_CERTS.search(certs) or STARTUP_CERTS.search(certs))
    granted = f.value.startswith("Exempted")
    if granted and has:
        status, note = PASS, "You can claim this exemption; upload your certificate with the bid."
    elif granted:
        status, note = UNKNOWN, "Applies only to registered MSEs / startups (none in your profile)."
    else:
        status, note = UNKNOWN, "The documents say no exemption applies."
    return _check(
        "mse_exemption", "MSE / Startup exemption", f.value, certs or None, status, f, note
    )


def evaluate(fields: dict[str, Field], docs, org) -> dict:
    checks = [_turnover(fields.get("min_turnover"), org), _similar(fields.get("similar_work"), org)]
    years_sources = []
    for doc in docs:
        for i, text in enumerate(doc.page_texts or [], start=1):
            years_sources.append(
                (
                    Field("years", "", i, "", document_id=doc.pk, filename=doc.filename),
                    " ".join(text.split()),
                )
            )
    if y := _years(years_sources, org):
        checks.append(y)
    # Informational: an exemption never makes a bidder ineligible, so it is left out of
    # the verdict.
    exemption = _exemption(fields.get("mse_exemption"), org)
    statuses = [c["status"] for c in checks]
    if FAIL in statuses:
        verdict = "not_eligible"
    elif all(s == PASS for s in statuses):
        verdict = "eligible"
    else:
        verdict = "unknown"
    if exemption:
        checks.append(exemption)
    return {"verdict": verdict, "checks": checks}
