from datetime import date

import pytest

from intel import rules
from intel.rules import RuleContext


def _keys(findings) -> set[str]:
    return {f.key for f in findings}


@pytest.mark.parametrize(
    "ratio,pct",
    [
        (1.00, 0.0),
        (0.90, 0.0),  # exactly 10% below: free band
        (0.896, 0.0),  # 10.4% rounds to 10
        (0.89, 0.1),  # 11% below
        (0.85, 0.5),
        (0.81, 0.9),  # 19% below
        (0.80, 1.0),  # 20% below
        (0.75, 2.0),  # 25% below: 1% + 5 x 0.2%
        (1.10, 0.0),  # above the estimate
    ],
)
def test_tiered_aps_percent(ratio, pct):
    assert rules.tiered_aps_percent(ratio) == pytest.approx(pct)


def _nh(**kw) -> RuleContext:
    base = dict(
        estimated_value_inr=500e7,
        category="works",
        buyer="National Highways Authority of India|PIU Raipur",
        title="Four laning of NH-130 from km 10 to km 52",
        on_date=date(2026, 10, 7),
    )
    return RuleContext(**{**base, **kw})


def test_highway_aps_applies_from_the_morth_circular_only():
    assert rules.aps_regime(_nh()) == "morth"
    assert rules.aps_percent(_nh(), 0.85) == pytest.approx(0.5)
    assert rules.aps_regime(_nh(on_date=date(2025, 4, 29))) is None
    assert rules.aps_regime(_nh(category="goods")) is None
    # Cost of carrying the guarantee: 0.5% of the bid x 1.5% a year x 3 years.
    assert rules.aps_cost_fraction(_nh(), 0.85) == pytest.approx(0.005 * 0.015 * 3)
    assert rules.aps_cost_fraction(_nh(), 0.95) == 0


def test_highway_findings_name_the_aps_and_the_scrutiny():
    deep = _keys(rules.evaluate(_nh(), 0.75))
    assert {"aps", "abnormally_low"} <= deep
    assert "aps_free_band" in _keys(rules.evaluate(_nh(), 0.95))
    msg = next(f for f in rules.evaluate(_nh(), 0.85) if f.key == "aps").message
    assert "15% below" in msg and "0.5%" in msg


def test_odisha_floor_before_2026_and_aps_after():
    old = RuleContext(1e7, category="works", state="Odisha", on_date=date(2025, 12, 1))
    new = RuleContext(1e7, category="works", state="Odisha", on_date=date(2026, 2, 1))
    assert rules.floor_ratio(old) == rules.ODISHA_FLOOR_RATIO
    assert rules.floor_ratio(new) is None
    assert "odisha_floor" in _keys(rules.evaluate(old, 0.9))
    assert {"odisha_cap_abolished", "aps"} <= _keys(rules.evaluate(new, 0.85))
    assert rules.aps_regime(old) is None and rules.aps_regime(new) == "odisha"


def test_other_states_get_a_hint_not_a_rule():
    ctx = RuleContext(1e7, category="works", state="Chhattisgarh", on_date=date(2026, 10, 7))
    assert _keys(rules.evaluate(ctx, 0.87)) == {"state_aps"}
    assert _keys(rules.evaluate(ctx, 0.95)) == set()
    assert rules.aps_cost_fraction(ctx, 0.7) == 0


def test_goods_get_mse_and_make_in_india_notes():
    ctx = RuleContext(20 * rules.LAKH, category="goods")
    assert {"mse_preference", "make_in_india"} <= _keys(rules.evaluate(ctx, 0.95))
    mse = RuleContext(20 * rules.LAKH, category="goods", is_mse=True, is_class1_local=True)
    found = rules.evaluate(mse, 0.95)
    assert "make_in_india" not in _keys(found)
    assert "within 15%" in next(f for f in found if f.key == "mse_preference").message
    small = RuleContext(2 * rules.LAKH, category="goods")
    assert "make_in_india" not in _keys(rules.evaluate(small))


def test_consultancy_and_reverse_auction():
    assert "qcbs" in _keys(rules.evaluate(RuleContext(1e6, category="consultancy")))
    gem = RuleContext(50 * rules.LAKH, category="goods", source="gem")
    assert "reverse_auction" in _keys(rules.evaluate(gem))
    assert "reverse_auction" not in _keys(rules.evaluate(RuleContext(5 * rules.LAKH, source="gem")))


def test_every_finding_cites_a_source():
    findings = rules.evaluate(_nh(), 0.7) + rules.evaluate(
        RuleContext(50 * rules.LAKH, category="goods", source="gem"), 0.7
    )
    assert findings and all(f.source.startswith("https://") for f in findings)
    assert all(set(f.as_dict()) == {"key", "severity", "message", "source"} for f in findings)
