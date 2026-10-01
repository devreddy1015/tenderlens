"""Turns raw parsed strings into a validated TenderIn, or a readable list of errors.

Rules (from the build plan): required fields are present; dates parse; closes_at is
not before published_at; money values are non-negative. Anything that fails goes to
the quarantine table with these errors; nothing is silently dropped.
"""

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

IST = ZoneInfo("Asia/Kolkata")
DATE_FORMATS = ("%d-%b-%Y %I:%M %p", "%d-%b-%Y %H:%M", "%d-%b-%Y")
MISSING = {"", "na", "n/a", "nil", "-", "--", "none", "null"}


def blank(value: str | None) -> bool:
    return value is None or value.strip().lower() in MISSING


def parse_ist(value: str | None) -> datetime | None:
    """'07-Oct-2026 11:00 AM' (portal times are IST) -> aware datetime."""
    if blank(value):
        return None
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}")


_MONEY_JUNK = re.compile(r"[,\s₹]|^rs\.?|/-$", re.I)


def parse_inr(value: str | None) -> Decimal | None:
    """'4,91,87,00,000' (Indian digit grouping) -> Decimal. 'NA' -> None."""
    if blank(value):
        return None
    text = _MONEY_JUNK.sub("", value.strip())
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a money amount: {value!r}") from exc


class TenderIn(BaseModel):
    source: str = Field(min_length=1)
    source_tender_id: str = Field(min_length=3)
    title: str = Field(min_length=3)
    buyer_raw: str = Field(min_length=2)
    org_chain: str = ""
    ref_no: str = ""
    category: str = ""
    product_category: str = ""
    tender_type: str = ""
    value_inr: Decimal | None = Field(default=None, ge=0)
    emd_inr: Decimal | None = Field(default=None, ge=0)
    fee_inr: Decimal | None = Field(default=None, ge=0)
    published_at: datetime
    closes_at: datetime
    opens_at: datetime | None = None
    location: str = ""
    pincode: str = ""
    state: str = ""
    url: str = ""

    @field_validator("pincode")
    @classmethod
    def pincode_digits(cls, v: str) -> str:
        v = v.strip()
        if v and not re.fullmatch(r"[1-9]\d{5}", v):
            return ""  # bad PINs are common and not worth quarantining a tender for
        return v

    @model_validator(mode="after")
    def closes_after_published(self):
        if self.closes_at < self.published_at:
            raise ValueError(
                f"closes_at {self.closes_at:%d-%b-%Y %H:%M} is before "
                f"published_at {self.published_at:%d-%b-%Y %H:%M}"
            )
        return self

    def content_hash(self) -> str:
        """Hash of the business fields only. The raw HTML cannot be hashed for change
        detection: the portal embeds a visitor counter and session tokens that change
        on every request."""
        data = self.model_dump(mode="json", exclude={"url"})
        blob = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()


def _convert(raw: dict[str, str]) -> tuple[dict, list[dict]]:
    """Convert strings to typed values, collecting conversion errors per field."""
    errors: list[dict] = []
    out: dict = {}

    def conv(field, fn, value):
        try:
            out[field] = fn(value)
        except ValueError as exc:
            errors.append({"field": field, "error": str(exc), "input": value})

    conv("published_at", parse_ist, raw.get("published"))
    conv("closes_at", parse_ist, raw.get("closes"))
    conv("opens_at", parse_ist, raw.get("opens"))
    conv("value_inr", parse_inr, raw.get("value"))
    conv("emd_inr", parse_inr, raw.get("emd"))
    conv("fee_inr", parse_inr, raw.get("fee"))
    return out, errors


def buyer_from_chain(org_chain: str) -> str:
    """'Org||Department||Office' -> 'Org || Department'.

    The top level is the ministry/organisation, the second level is the department
    that actually buys. Deeper levels are individual offices and divisions.
    """
    parts = [p.strip() for p in org_chain.split("||") if p.strip()]
    return " || ".join(parts[:2])


def validate_detail(
    raw: dict[str, str], *, source: str, url: str, state: str
) -> tuple[TenderIn | None, list[dict]]:
    """Returns (tender, []) on success or (None, errors) on failure."""
    converted, errors = _convert(raw)
    org_chain = raw.get("org_chain", "")
    candidate = {
        "source": source,
        "source_tender_id": raw.get("tender_id", ""),
        "title": raw.get("title", ""),
        "buyer_raw": buyer_from_chain(org_chain),
        "org_chain": org_chain.replace("||", " || "),
        "ref_no": raw.get("ref_no", ""),
        "category": raw.get("category", ""),
        "product_category": "" if blank(raw.get("product_category")) else raw["product_category"],
        "tender_type": raw.get("tender_type", ""),
        "location": "" if blank(raw.get("location")) else raw["location"],
        "pincode": raw.get("pincode", "") or "",
        "state": state,
        "url": url,
        **converted,
    }
    for field in ("published_at", "closes_at"):
        if candidate.get(field) is None and not any(e["field"] == field for e in errors):
            errors.append({"field": field, "error": "required", "input": None})
    if errors:
        return None, errors
    try:
        return TenderIn(**candidate), []
    except ValidationError as exc:
        return None, [_format_error(e, raw) for e in exc.errors()]


def _format_error(e: dict, raw: dict[str, str]) -> dict:
    field = ".".join(str(p) for p in e["loc"])
    if not field:
        # A cross-field rule failed: show the raw inputs it compared, not the whole record.
        return {
            "field": "__all__",
            "error": e["msg"],
            "input": {k: raw.get(k) for k in ("published", "closes")},
        }
    value = e.get("input")
    return {
        "field": field,
        "error": e["msg"],
        "input": value if isinstance(value, str | int | float | None) else str(value),
    }
