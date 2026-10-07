"""Plans, quotas and organisations: billing.plans, billing.entitlements, workspaces.services."""

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from billing import entitlements
from billing.entitlements import QuotaExceeded, consume, limit, require_feature, used
from billing.models import Usage
from billing.plans import LIMIT_KEYS, PLANS
from workspaces.models import Membership, Organization
from workspaces.services import get_active_org, require_role, set_active_org

User = get_user_model()
IST = ZoneInfo("Asia/Kolkata")


def make_org(plan="free", slug="acme") -> Organization:
    return Organization.objects.create(name=slug.title(), slug=slug, plan_code=plan)


# --- plans --------------------------------------------------------------------------------


def test_plans_match_the_price_list():
    assert list(PLANS) == ["free", "pro", "team", "enterprise"]
    for plan in PLANS.values():
        assert set(plan.limits) == set(LIMIT_KEYS)
        assert plan.features
    free, pro, team, ent = (PLANS[k] for k in ("free", "pro", "team", "enterprise"))
    assert (free.price_inr_month, pro.price_inr_month, pro.price_inr_year) == (0, 999, 9_990)
    assert (team.price_inr_month, team.price_inr_year) == (2_999, 29_990)
    assert ent.price_inr_month is None and ent.price_inr_year is None
    assert dict(free.limits) == {
        "alerts": 2,
        "questions_per_month": 20,
        "documents_per_month": 5,
        "seats": 1,
        "export": False,
        "api": False,
    }
    assert pro.limits["questions_per_month"] == 500 and pro.limits["export"] is True
    assert team.limits["seats"] == 5 and team.limits["api"] is False
    assert ent.limits["questions_per_month"] is None and ent.limits["api"] is True
    assert set(ent.as_dict()) == {
        "code",
        "name",
        "price_inr_month",
        "price_inr_year",
        "limits",
        "features",
    }


# --- entitlements -------------------------------------------------------------------------


@pytest.mark.django_db
def test_limits_and_unknown_plan_falls_back_to_free():
    org = make_org("pro")
    assert limit(org, "documents_per_month") == 100
    assert entitlements.get_plan(org).code == "pro"
    org.plan_code = "discontinued"
    assert entitlements.get_plan(org).code == "free"
    with pytest.raises(KeyError):
        limit(org, "nope")


@pytest.mark.django_db
def test_consume_counts_until_the_cap_then_raises():
    org = make_org()
    for i in range(1, 21):
        assert consume(org, "questions_per_month") == i
    with pytest.raises(QuotaExceeded) as exc:
        consume(org, "questions_per_month")
    assert exc.value.status_code == 402
    assert used(org, "questions_per_month") == 20  # the refused unit was not counted
    with pytest.raises(QuotaExceeded):
        consume(make_org(slug="b"), "documents_per_month", n=6)  # more than the cap at once
    assert entitlements.remaining(org, "questions_per_month") == 0
    entitlements.refund(org, "questions_per_month")
    assert used(org, "questions_per_month") == 19


@pytest.mark.django_db
def test_monthly_periods_reset_on_the_first_in_ist(monkeypatch):
    org = make_org()
    # 31 Oct 2026 23:30 IST is still October in India although UTC is 18:00 on the 31st,
    # and 1 Nov 00:10 IST (31 Oct 18:40 UTC) is November.
    monkeypatch.setattr(
        "billing.entitlements.timezone.now", lambda: datetime(2026, 10, 31, 23, 30, tzinfo=IST)
    )
    for _ in range(5):
        consume(org, "documents_per_month")
    with pytest.raises(QuotaExceeded):
        consume(org, "documents_per_month")
    monkeypatch.setattr(
        "billing.entitlements.timezone.now", lambda: datetime(2026, 11, 1, 0, 10, tzinfo=IST)
    )
    assert used(org, "documents_per_month") == 0
    consume(org, "documents_per_month")
    assert sorted(Usage.objects.values_list("period", "count")) == [("2026-10", 5), ("2026-11", 1)]
    assert entitlements.usage_summary(org) == {"questions_per_month": 0, "documents_per_month": 1}


@pytest.mark.django_db
def test_unlimited_plan_never_raises():
    org = make_org("enterprise")
    assert limit(org, "questions_per_month") is None
    assert consume(org, "questions_per_month", n=10_000) == 10_000
    assert entitlements.remaining(org, "questions_per_month") is None
    require_feature(org, "api")
    entitlements.ensure_capacity(org, "seats", current=10_000)


@pytest.mark.django_db
def test_features_and_count_limits():
    free, pro = make_org(), make_org("pro", slug="pro")
    with pytest.raises(QuotaExceeded) as exc:
        require_feature(free, "export")
    assert exc.value.limit_key == "export"
    require_feature(pro, "export")
    with pytest.raises(QuotaExceeded):
        require_feature(pro, "api")
    with pytest.raises(ValueError):
        require_feature(pro, "seats")
    with pytest.raises(ValueError):
        consume(pro, "seats")
    entitlements.ensure_capacity(free, "alerts", current=1)
    with pytest.raises(QuotaExceeded):
        entitlements.ensure_capacity(free, "alerts", current=2)


@pytest.mark.django_db
def test_quota_error_body_names_the_limit():
    org = make_org()

    class Ask(APIView):
        authentication_classes, permission_classes = [], []

        def post(self, request):
            require_feature(org, "export")
            return Response({})

    r = Ask.as_view()(APIRequestFactory().post("/x"))
    assert r.status_code == 402
    assert r.data["code"] == "quota_exceeded"
    assert r.data["limit"] == "export"
    assert "export" in str(r.data["detail"])


@pytest.mark.django_db(transaction=True)
def test_consume_is_race_safe():
    """Parallel requests on separate connections never take more than the cap."""
    org = make_org()  # 20 questions
    results: list[str] = []
    barrier = threading.Barrier(8)

    def worker():
        try:
            barrier.wait()
            for _ in range(5):
                try:
                    consume(org, "questions_per_month")
                    results.append("ok")
                except QuotaExceeded:
                    results.append("refused")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 20 and results.count("refused") == 20
    assert used(org, "questions_per_month") == 20


# --- workspaces ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_active_org_creates_a_personal_org_once():
    user = User.objects.create(username="asha@example.com", email="asha@example.com")
    org = get_active_org(user)
    assert org.plan_code == "free" and org.slug == "asha"
    assert get_active_org(user) == org
    assert Organization.objects.count() == 1
    m = Membership.objects.get()
    assert (m.user, m.organization, m.role, m.is_active) == (user, org, "owner", True)

    other = User.objects.create(username="asha@other.org", email="asha@other.org")
    assert get_active_org(other).slug != org.slug  # slugs stay unique


@pytest.mark.django_db
def test_require_role_and_switching_org():
    owner = User.objects.create(username="o@example.com", email="o@example.com")
    member = User.objects.create(username="m@example.com", email="m@example.com")
    stranger = User.objects.create(username="s@example.com", email="s@example.com")
    team = make_org("team", slug="team")
    Membership.objects.create(user=owner, organization=team, role="owner")
    Membership.objects.create(user=member, organization=team, role="member")

    assert require_role(owner, team, "owner", "admin").role == "owner"
    assert require_role(member, team).role == "member"
    with pytest.raises(PermissionDenied):
        require_role(member, team, "owner", "admin")
    with pytest.raises(PermissionDenied):
        require_role(stranger, team)

    # A member somewhere with nothing marked active works in that organisation.
    assert get_active_org(member) == team
    personal = get_active_org(owner)
    assert personal == team
    with pytest.raises(PermissionDenied):
        set_active_org(stranger, team)
    mine = get_active_org(stranger)
    assert mine != team
