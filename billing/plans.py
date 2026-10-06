"""The price list. Code, not database rows: a plan change is a reviewed commit, and every
process agrees on the limits without a query.

Limit values: an int is a cap, None is unlimited, 0 / False is "not included". Monthly
limits (MONTHLY_KEYS) reset on the 1st (IST) and are counted in billing.models.Usage; the
others cap a current count (alert subscriptions, members) or switch a feature on.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

LIMIT_KEYS = ("alerts", "questions_per_month", "documents_per_month", "seats", "export", "api")
MONTHLY_KEYS = ("questions_per_month", "documents_per_month")
FEATURE_KEYS = ("export", "api")  # boolean limits, checked with entitlements.require_feature

Limit = int | bool | None


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_inr_month: int | None  # None: priced per customer ("contact sales")
    price_inr_year: int | None
    limits: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    features: tuple[str, ...] = ()  # human bullet points for the pricing page

    def as_dict(self) -> dict:
        """The API shape: {code, name, price_inr_month, price_inr_year, limits, features}."""
        return {
            "code": self.code,
            "name": self.name,
            "price_inr_month": self.price_inr_month,
            "price_inr_year": self.price_inr_year,
            "limits": dict(self.limits),
            "features": list(self.features),
        }


def _plan(code, name, month, year, limits: dict, features: list[str]) -> Plan:
    assert set(limits) == set(LIMIT_KEYS), f"{code}: limits must define exactly {LIMIT_KEYS}"
    return Plan(code, name, month, year, MappingProxyType(dict(limits)), tuple(features))


PLANS: dict[str, Plan] = {
    p.code: p
    for p in (
        _plan(
            "free",
            "Free",
            0,
            0,
            {
                "alerts": 2,
                "questions_per_month": 20,
                "documents_per_month": 5,
                "seats": 1,
                "export": False,
                "api": False,
            },
            [
                "Search every crawled tender: typo-tolerant, with filters and facets",
                "2 email alerts",
                "Copilot: 20 questions and 5 tender documents a month",
                "Bid Brief: EMD, fees, dates and eligibility criteria with page citations",
            ],
        ),
        _plan(
            "pro",
            "Pro",
            999,
            9_990,
            {
                "alerts": 25,
                "questions_per_month": 500,
                "documents_per_month": 100,
                "seats": 1,
                "export": True,
                "api": False,
            },
            [
                "Everything in Free",
                "25 email alerts",
                "Copilot: 500 questions and 100 tender documents a month",
                "Eligibility check against your company profile",
                "Bid pipeline with closing-date reminders",
                "CSV export",
            ],
        ),
        _plan(
            "team",
            "Team",
            2_999,
            29_990,
            {
                "alerts": 100,
                "questions_per_month": 2_500,
                "documents_per_month": 500,
                "seats": 5,
                "export": True,
                "api": False,
            },
            [
                "Everything in Pro",
                "5 seats with owner / admin / member roles",
                "Shared bid pipeline for the whole team",
                "100 email alerts",
                "Copilot: 2,500 questions and 500 tender documents a month",
            ],
        ),
        _plan(
            "enterprise",
            "Enterprise",
            None,
            None,
            {
                "alerts": None,
                "questions_per_month": None,
                "documents_per_month": None,
                "seats": None,
                "export": True,
                "api": True,
            },
            [
                "Everything in Team, without limits",
                "REST API access with API keys, OCDS export",
                "Dedicated Copilot model, optionally fine-tuned on your own documents",
                "Private deployment option and priority support",
            ],
        ),
    )
}

DEFAULT_PLAN = "free"
