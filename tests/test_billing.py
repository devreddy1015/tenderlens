"""Billing API: plans, subscription, fake and Razorpay checkout, webhook, cancel, and the
plan's alert limit."""

import hashlib
import hmac
import json
import time

import httpx
import pytest
import respx
from rest_framework.test import APIClient

from alerts.models import AlertSubscription
from billing.models import Subscription, WebhookEvent
from tests.test_workspaces import add_member, client_for, make_org, make_user
from workspaces.models import Organization

pytestmark = pytest.mark.django_db
SECRET = "whsec_test"


@pytest.fixture
def owner():
    return make_user("owner@example.com")


@pytest.fixture
def org(owner):
    return make_org(owner)


@pytest.fixture
def oc(owner, org):
    return client_for(owner)


@pytest.fixture
def razorpay(settings):
    settings.BILLING_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID = "rzp_test_key"
    settings.RAZORPAY_KEY_SECRET = "rzp_secret"
    settings.RAZORPAY_WEBHOOK_SECRET = SECRET
    settings.RAZORPAY_PLAN_IDS = {
        "PRO_MONTH": "plan_pro_m",
        "PRO_YEAR": "plan_pro_y",
        "TEAM_MONTH": "plan_team_m",
        "TEAM_YEAR": "",
    }


def test_plans_public():
    r = APIClient().get("/api/billing/plans")
    assert r.status_code == 200
    plans = r.json()
    assert [p["code"] for p in plans] == ["free", "pro", "team", "enterprise"]
    assert set(plans[1]) == {
        "code",
        "name",
        "price_inr_month",
        "price_inr_year",
        "limits",
        "features",
    }


def test_subscription_without_one(oc):
    body = oc.get("/api/billing/subscription").json()
    assert body["plan"]["code"] == "free" and body["status"] == "none"
    assert body["interval"] is None and body["provider"] is None


def test_subscription_login_required():
    assert APIClient().get("/api/billing/subscription").status_code == 403
    assert APIClient().post("/api/billing/checkout", {"plan": "pro"}).status_code == 403


# --- fake provider ------------------------------------------------------------------------


def test_fake_checkout_activates_and_cancel_reverts(oc, org, settings):
    settings.BILLING_PROVIDER = "fake"
    r = oc.post("/api/billing/checkout", {"plan": "pro", "interval": "year"}, format="json")
    assert r.status_code == 200 and r.json() == {"provider": "fake", "activated": True}
    org.refresh_from_db()
    assert org.plan_code == "pro"
    sub = oc.get("/api/billing/subscription").json()
    assert (sub["plan"]["code"], sub["status"], sub["interval"], sub["provider"]) == (
        "pro",
        "active",
        "year",
        "fake",
    )
    # Upgrading replaces the subscription.
    oc.post("/api/billing/checkout", {"plan": "team", "interval": "month"}, format="json")
    org.refresh_from_db()
    assert org.plan_code == "team"
    assert Subscription.objects.filter(organization=org, status="active").count() == 1

    r = oc.post("/api/billing/cancel")
    assert r.status_code == 200 and r.json()["plan"]["code"] == "free"
    org.refresh_from_db()
    assert org.plan_code == "free"
    assert oc.post("/api/billing/cancel").status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"plan": "gold", "interval": "month"},
        {"plan": "pro", "interval": "week"},
        {"plan": "free", "interval": "month"},
        {"plan": "enterprise", "interval": "month"},
    ],
)
def test_checkout_bad_input(oc, settings, payload):
    settings.BILLING_PROVIDER = "fake"
    assert oc.post("/api/billing/checkout", payload, format="json").status_code == 400


def test_member_cannot_checkout(org, settings):
    settings.BILLING_PROVIDER = "fake"
    org.plan_code = "team"
    org.save()
    m = make_user("m@example.com")
    add_member(org, m)
    r = client_for(m).post("/api/billing/checkout", {"plan": "pro", "interval": "month"})
    assert r.status_code == 403
    assert client_for(m).post("/api/billing/cancel").status_code == 403


def test_production_default_is_not_fake():
    """BILLING_PROVIDER unset and DEBUG off must mean razorpay, never free upgrades."""
    from django.conf import settings

    if not settings.DEBUG and "BILLING_PROVIDER" not in __import__("os").environ:
        assert settings.BILLING_PROVIDER == "razorpay"


def test_razorpay_not_configured(oc, settings):
    settings.BILLING_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID = settings.RAZORPAY_KEY_SECRET = ""
    r = oc.post("/api/billing/checkout", {"plan": "pro", "interval": "month"}, format="json")
    assert r.status_code == 503


# --- razorpay -----------------------------------------------------------------------------


@respx.mock
def test_razorpay_checkout(oc, org, razorpay):
    route = respx.post("https://api.razorpay.com/v1/subscriptions").mock(
        return_value=httpx.Response(
            200, json={"id": "sub_123", "status": "created", "short_url": "https://rzp.io/i/x"}
        )
    )
    r = oc.post("/api/billing/checkout", {"plan": "pro", "interval": "month"}, format="json")
    assert r.status_code == 200
    assert r.json() == {
        "provider": "razorpay",
        "key_id": "rzp_test_key",
        "subscription_id": "sub_123",
        "short_url": "https://rzp.io/i/x",
    }
    sent = route.calls.last.request
    assert sent.headers["authorization"].startswith("Basic ")
    payload = json.loads(sent.content)
    assert payload["plan_id"] == "plan_pro_m"
    assert payload["notes"]["organization_id"] == str(org.pk)
    org.refresh_from_db()
    assert org.plan_code == "free"  # only the webhook activates
    assert Subscription.objects.get().status == "created"


@respx.mock
def test_razorpay_errors(oc, razorpay):
    respx.post("https://api.razorpay.com/v1/subscriptions").mock(
        return_value=httpx.Response(400, json={"error": {"description": "bad"}})
    )
    r = oc.post("/api/billing/checkout", {"plan": "pro", "interval": "month"}, format="json")
    assert r.status_code == 502
    # No plan id configured for this interval.
    r = oc.post("/api/billing/checkout", {"plan": "team", "interval": "year"}, format="json")
    assert r.status_code == 503


def _event(event: str, sub_id="sub_123", current_end=None, **notes) -> bytes:
    entity = {"id": sub_id, "plan_id": "plan_pro_m", "status": event.split(".")[1]}
    if current_end:
        entity["current_end"] = current_end
    if notes:
        entity["notes"] = notes
    return json.dumps(
        {"entity": "event", "event": event, "payload": {"subscription": {"entity": entity}}}
    ).encode()


def _post_webhook(body: bytes, event_id: str, secret=SECRET, signature=None):
    sig = signature
    if sig is None:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return APIClient(enforce_csrf_checks=True).generic(
        "POST",
        "/api/billing/webhook",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sig,
        HTTP_X_RAZORPAY_EVENT_ID=event_id,
    )


def _created_sub(org):
    return Subscription.objects.create(
        organization=org,
        plan_code="pro",
        interval="month",
        provider="razorpay",
        provider_subscription_id="sub_123",
    )


def test_webhook_activates_and_deactivates(org, razorpay):
    _created_sub(org)
    end = int(time.time()) + 30 * 86400
    r = _post_webhook(_event("subscription.activated", current_end=end), "evt_1")
    assert r.status_code == 200, r.content
    org.refresh_from_db()
    assert org.plan_code == "pro"
    sub = Subscription.objects.get()
    assert sub.status == "active" and int(sub.current_period_end.timestamp()) == end

    assert _post_webhook(_event("subscription.charged"), "evt_2").status_code == 200
    org.refresh_from_db()
    assert org.plan_code == "pro"

    assert _post_webhook(_event("subscription.halted"), "evt_3").status_code == 200
    org.refresh_from_db()
    assert org.plan_code == "free"
    # A successful retry after a halt re-activates.
    _post_webhook(_event("subscription.charged"), "evt_4")
    org.refresh_from_db()
    assert org.plan_code == "pro"

    _post_webhook(_event("subscription.cancelled"), "evt_5")
    org.refresh_from_db()
    assert org.plan_code == "free"
    # Cancelled is final: a late charged event does not resurrect it.
    _post_webhook(_event("subscription.charged"), "evt_6")
    org.refresh_from_db()
    assert org.plan_code == "free"


def test_webhook_completed_reverts_to_free(org, razorpay):
    _created_sub(org)
    _post_webhook(_event("subscription.activated"), "evt_1")
    _post_webhook(_event("subscription.completed"), "evt_2")
    org.refresh_from_db()
    assert org.plan_code == "free"


def test_webhook_signature_invalid(org, razorpay):
    _created_sub(org)
    body = _event("subscription.activated")
    assert _post_webhook(body, "evt_1", secret="wrong").status_code == 400
    assert _post_webhook(body, "evt_1", signature="").status_code == 400
    # Signature of a different body.
    other = hmac.new(SECRET.encode(), b"{}", hashlib.sha256).hexdigest()
    assert _post_webhook(body, "evt_1", signature=other).status_code == 400
    org.refresh_from_db()
    assert org.plan_code == "free" and WebhookEvent.objects.count() == 0


def test_webhook_without_configured_secret_rejects(org, razorpay, settings):
    settings.RAZORPAY_WEBHOOK_SECRET = ""
    _created_sub(org)
    body = _event("subscription.activated")
    assert _post_webhook(body, "evt_1", secret="").status_code == 400


def test_webhook_replay_is_idempotent(org, razorpay):
    _created_sub(org)
    body = _event("subscription.activated")
    assert _post_webhook(body, "evt_1").json()["status"].startswith("active")
    org.refresh_from_db()
    assert org.plan_code == "pro"
    # Cancelled meanwhile; a replay of the old activation must not re-activate.
    Subscription.objects.update(status="halted")
    Organization.objects.filter(pk=org.pk).update(plan_code="free")
    r = _post_webhook(body, "evt_1")
    assert r.status_code == 200 and r.json() == {"status": "duplicate"}
    org.refresh_from_db()
    assert org.plan_code == "free"
    assert WebhookEvent.objects.count() == 1


def test_webhook_adopts_dashboard_subscription(org, razorpay):
    body = _event("subscription.activated", sub_id="sub_new", organization_id=str(org.pk))
    assert _post_webhook(body, "evt_1").status_code == 200
    org.refresh_from_db()
    assert org.plan_code == "pro"


def test_webhook_unknown_subscription_ignored(org, razorpay):
    r = _post_webhook(_event("subscription.activated", sub_id="sub_zzz"), "evt_1")
    assert r.status_code == 200 and r.json()["status"].startswith("ignored")
    org.refresh_from_db()
    assert org.plan_code == "free"


def test_webhook_rejects_get_and_bad_json(razorpay):
    assert APIClient().get("/api/billing/webhook").status_code == 405
    body = b"not json"
    assert _post_webhook(body, "evt_x").status_code == 400


@respx.mock
def test_razorpay_cancel_at_period_end(oc, org, razorpay):
    sub = _created_sub(org)
    _post_webhook(_event("subscription.activated"), "evt_1")
    route = respx.post("https://api.razorpay.com/v1/subscriptions/sub_123/cancel").mock(
        return_value=httpx.Response(200, json={"id": "sub_123", "status": "active"})
    )
    r = oc.post("/api/billing/cancel")
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True
    assert json.loads(route.calls.last.request.content) == {"cancel_at_cycle_end": 1}
    org.refresh_from_db()
    assert org.plan_code == "pro"  # paid until the period ends
    _post_webhook(_event("subscription.cancelled"), "evt_2")
    org.refresh_from_db()
    sub.refresh_from_db()
    assert org.plan_code == "free" and sub.status == "cancelled"


# --- alerts limit -------------------------------------------------------------------------

ALERT = {"name": "Roads", "states": ["Delhi"], "sectors": []}


def test_alert_quota(oc, org, monkeypatch):
    monkeypatch.setattr("alerts.tasks.send_first_digest.delay", lambda pk: None)
    assert oc.post("/api/alerts", ALERT, format="json").status_code == 201
    assert oc.post("/api/alerts", ALERT, format="json").status_code == 201
    r = oc.post("/api/alerts", ALERT, format="json")
    assert r.status_code == 402
    assert r.json() == {
        "detail": "Your plan's limit for email alerts is reached.",
        "code": "quota_exceeded",
        "limit": "alerts",
    }
    assert AlertSubscription.objects.count() == 2
    org.plan_code = "pro"
    org.save()
    assert oc.post("/api/alerts", ALERT, format="json").status_code == 201


def test_alert_quota_is_shared_by_the_team(org, owner, monkeypatch):
    monkeypatch.setattr("alerts.tasks.send_first_digest.delay", lambda pk: None)
    m = make_user("m@example.com")
    add_member(org, m)  # free plan, 2 alerts for the whole organisation
    AlertSubscription.objects.create(user=owner, name="a")
    AlertSubscription.objects.create(user=owner, name="b")
    assert client_for(m).post("/api/alerts", ALERT, format="json").status_code == 402
