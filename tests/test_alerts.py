from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from alerts import emails, tasks
from alerts.models import AlertDelivery, AlertSubscription
from ingest.loader import load_detail_page
from tenders.models import Tender
from tests.conftest import CENTRAL

pytestmark = pytest.mark.django_db
User = get_user_model()
NOW = timezone.datetime(2026, 10, 2, 9, 0, tzinfo=timezone.get_current_timezone())


@pytest.fixture
def loaded(make_page):
    for p in sorted(CENTRAL.glob("detail_*.html")):
        load_detail_page(make_page(p.read_text(encoding="utf-8")))
    # Pretend the crawler first saw them a day before NOW.
    Tender.objects.update(first_seen=NOW - timedelta(days=1))
    return Tender.objects.count()


@pytest.fixture
def user():
    return User.objects.create(username="u@example.com", email="u@example.com")


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    for mod in ("alerts.matching", "alerts.tasks", "alerts.emails"):
        monkeypatch.setattr(f"{mod}.timezone.now", lambda: NOW)


def make_alert(user, **kw):
    defaults = dict(name="Delhi works", states=["Delhi"], pin_prefixes=[], sectors=[])
    defaults.update(kw)
    return AlertSubscription.objects.create(user=user, **defaults)


def test_first_digest_lists_open_matching_tenders(loaded, user):
    sub = make_alert(user)
    sent = tasks.send_for_subscription(sub)
    delhi_open = Tender.objects.filter(state="Delhi", closes_at__gte=NOW).count()
    assert sent == delhi_open > 0
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["u@example.com"]
    assert f"{delhi_open} open tender" in msg.subject and "Delhi" in msg.subject
    html = msg.alternatives[0][0]
    assert "/tenders/" in html and "Unsubscribe" in html
    assert "List-Unsubscribe" in msg.extra_headers


def test_second_run_sends_only_new_tenders_and_never_repeats(loaded, user, monkeypatch, make_page):
    sub = make_alert(user)
    tasks.send_for_subscription(sub)
    mail.outbox.clear()
    sub.refresh_from_db()
    assert tasks.send_for_subscription(sub) == 0  # nothing new
    assert mail.outbox == []
    # A new Delhi tender appears.
    later = NOW + timedelta(hours=1)
    t = Tender.objects.filter(state="Delhi").first()
    Tender.objects.filter(pk=t.pk).update(first_seen=later - timedelta(minutes=5))
    AlertDelivery.objects.filter(tender=t).delete()
    sub.refresh_from_db()
    sent = tasks.send_for_subscription(sub, now=later)
    assert sent == 1
    assert "1 new tender" in mail.outbox[0].subject


def test_pin_prefix_area_for_bhilai(loaded, user):
    """PIN 490xxx is Durg/Bhilai. Area = states OR PIN prefixes."""
    t = Tender.objects.filter(closes_at__gte=NOW).first()
    Tender.objects.filter(pk=t.pk).update(pincode="490001", state="Chhattisgarh")
    sub = make_alert(user, name="Bhilai", states=[], pin_prefixes=["490"])
    assert tasks.send_for_subscription(sub) == 1
    assert "PIN 490xxx" in mail.outbox[0].subject


def test_sector_keyword_and_value_filters(loaded, user):
    sub = make_alert(user, states=[], sectors=["roads"], min_value_inr=10_000_000)
    expected = Tender.objects.filter(
        sector="roads", value_inr__gte=10_000_000, closes_at__gte=NOW
    ).count()
    assert tasks.send_for_subscription(sub) == expected > 0
    mail.outbox.clear()
    sub2 = make_alert(user, name="toilets", states=[], keywords="toilet, washroom")
    assert tasks.send_for_subscription(sub2) == 1


def test_closed_tenders_are_never_sent(loaded, user):
    Tender.objects.update(closes_at=NOW - timedelta(hours=1), published_at=NOW - timedelta(days=9))
    assert tasks.send_for_subscription(make_alert(user)) == 0
    assert mail.outbox == []


def test_failed_email_records_nothing_so_next_run_retries(loaded, user, monkeypatch):
    sub = make_alert(user)

    def boom(self, fail_silently=False):
        raise OSError("SMTP down")

    monkeypatch.setattr("django.core.mail.EmailMultiAlternatives.send", boom)
    with pytest.raises(OSError):
        tasks.send_for_subscription(sub)
    assert AlertDelivery.objects.count() == 0
    sub.refresh_from_db()
    assert sub.checked_until is None
    monkeypatch.undo()
    for mod in ("alerts.matching", "alerts.tasks", "alerts.emails"):
        monkeypatch.setattr(f"{mod}.timezone.now", lambda: NOW)
    assert tasks.send_for_subscription(sub) > 0


def test_send_alerts_task_skips_inactive(loaded, user):
    make_alert(user)
    make_alert(user, name="off", active=False)
    result = tasks.send_alerts.apply().get()
    assert result["subscriptions"] == 1
    assert len(mail.outbox) == 1


def test_crawl_run_with_new_tenders_triggers_alerts(
    portal, user, monkeypatch, django_capture_on_commit_callbacks
):
    calls = []
    monkeypatch.setattr("alerts.tasks.send_alerts.delay", lambda: calls.append(1))
    from ingest import pipeline

    with django_capture_on_commit_callbacks(execute=True):
        pipeline.run_sync("central", mode="full")
    assert calls == [1]
    with django_capture_on_commit_callbacks(execute=True):
        pipeline.run_sync("central", mode="incremental")  # nothing new: no alert run
    assert calls == [1]


# --- API ------------------------------------------------------------------------------


def test_alert_api_requires_sign_in():
    assert APIClient().get("/api/alerts").status_code == 403


def test_create_alert_sends_first_digest(client, loaded):
    r = client.post(
        "/api/alerts",
        {"name": "Delhi roads", "states": ["Delhi"], "sectors": ["buildings"]},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.json()["states"] == ["Delhi"]
    assert len(mail.outbox) == 1  # eager Celery in tests


def test_alert_validation(client):
    bad = client.post(
        "/api/alerts",
        {"name": "x", "states": ["Atlantis"], "pin_prefixes": ["49a"], "sectors": ["rockets"]},
        format="json",
    )
    assert bad.status_code == 400
    body = bad.json()
    assert "unknown state: Atlantis" in body["states"][0]
    assert "PIN prefix" in body["pin_prefixes"][0]
    assert "unknown sector: rockets" in body["sectors"][0]


def test_alert_limit_per_user(client, user):
    for i in range(10):
        make_alert(user, name=f"a{i}")
    r = client.post("/api/alerts", {"name": "one too many"}, format="json")
    assert r.status_code == 400


def test_users_cannot_see_or_change_each_others_alerts(client, user):
    other = User.objects.create(username="o@example.com", email="o@example.com")
    theirs = make_alert(other)
    assert client.get(f"/api/alerts/{theirs.pk}").status_code == 404
    assert client.delete(f"/api/alerts/{theirs.pk}").status_code == 404
    assert client.get("/api/alerts").json() == []


def test_patch_and_delete(client, user):
    a = make_alert(user)
    r = client.patch(f"/api/alerts/{a.pk}", {"active": False}, format="json")
    assert r.json()["active"] is False
    assert client.delete(f"/api/alerts/{a.pk}").status_code == 204


def test_preview_counts_matches(loaded):
    r = APIClient().post("/api/alerts/preview", {"states": ["Delhi"]}, format="json")
    assert r.json()["count"] == Tender.objects.filter(state="Delhi", closes_at__gte=NOW).count()
    assert len(r.json()["sample"]) <= 3


def test_test_email(client, user, loaded):
    a = make_alert(user)
    r = client.post(f"/api/alerts/{a.pk}/test")
    assert r.json()["sent_to"] == "u@example.com"
    assert mail.outbox[0].subject.startswith("[Test]")
    assert AlertDelivery.objects.count() == 0  # a test never counts as delivered


def test_unsubscribe_link(user):
    a = make_alert(user)
    token = emails.unsubscribe_token(a)
    r = APIClient().get("/api/alerts/unsubscribe", {"token": token})
    assert r.status_code == 200 and b"Unsubscribed" in r.content
    a.refresh_from_db()
    assert a.active is False
    bad = APIClient().get("/api/alerts/unsubscribe", {"token": token[:-2] + "xx"})
    assert bad.status_code == 400


def test_format_inr():
    assert emails.format_inr(800000) == "₹8.00 lakh"
    assert emails.format_inr(4918700000) == "₹491.87 crore"
    assert emails.format_inr(None) == "Not disclosed"
    assert emails.format_inr(0) == "Not disclosed"
