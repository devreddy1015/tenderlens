"""Bid pipeline API, summary, daily reminders and the iCal feed."""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from tests.test_workspaces import add_member, client_for, make_org, make_tender, make_user
from workspaces import ical
from workspaces.models import BidTrack, ReminderLog
from workspaces.tasks import send_pipeline_reminders

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return make_user("owner@example.com")


@pytest.fixture
def org(owner):
    return make_org(owner, plan="team", name="Acme, Infra; Ltd")


@pytest.fixture
def oc(owner, org):
    return client_for(owner)


# --- CRUD ---------------------------------------------------------------------------------


def test_track_list_patch_delete(oc, owner):
    t = make_tender(value_inr=Decimal("5000000"))
    r = oc.post("/api/pipeline", {"tender": t.pk}, format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "watching"
    assert body["tender"]["id"] == t.pk and body["tender"]["source_tender_id"] == t.source_tender_id
    assert body["owner"] == {"id": owner.pk, "email": owner.email}
    assert set(body) == {
        "id",
        "tender",
        "status",
        "notes",
        "bid_amount_inr",
        "l1_amount_inr",
        "winner_name",
        "num_bidders",
        "our_rank",
        "owner",
        "created_at",
        "updated_at",
    }
    # Idempotent per org + tender.
    again = oc.post("/api/pipeline", {"tender": t.pk, "status": "won"}, format="json")
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    assert again.json()["status"] == "watching"
    assert BidTrack.objects.count() == 1

    r = oc.patch(
        f"/api/pipeline/{body['id']}",
        {"status": "preparing", "notes": "Site visit Monday", "bid_amount_inr": "4800000"},
        format="json",
    )
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["notes"], r.json()["bid_amount_inr"]) == (
        "preparing",
        "Site visit Monday",
        "4800000.00",
    )
    assert [b["id"] for b in oc.get("/api/pipeline?status=preparing").json()] == [body["id"]]
    assert oc.get("/api/pipeline?status=won").json() == []
    assert oc.delete(f"/api/pipeline/{body['id']}").status_code == 204
    assert oc.get("/api/pipeline").json() == []


@pytest.mark.parametrize(
    "payload",
    [{"tender": 999999}, {}, {"tender": "x"}, {"tender": 1, "status": "maybe"}],
)
def test_track_bad_input(oc, payload):
    make_tender()
    assert oc.post("/api/pipeline", payload, format="json").status_code == 400


def test_bad_status_filter(oc):
    assert oc.get("/api/pipeline?status=nope").status_code == 400


def test_patch_owner_must_be_member(oc, org):
    track = BidTrack.objects.create(organization=org, tender=make_tender())
    outsider = make_user("x@example.com")
    r = oc.patch(f"/api/pipeline/{track.pk}", {"owner": outsider.pk}, format="json")
    assert r.status_code == 400
    m = make_user("m@example.com")
    add_member(org, m, active=False)
    r = oc.patch(f"/api/pipeline/{track.pk}", {"owner": m.pk}, format="json")
    assert r.json()["owner"]["email"] == "m@example.com"
    r = oc.patch(f"/api/pipeline/{track.pk}", {"owner": None}, format="json")
    assert r.json()["owner"] is None
    bad = oc.patch(f"/api/pipeline/{track.pk}", {"bid_amount_inr": "-1"}, format="json")
    assert bad.status_code == 400


def test_team_shares_pipeline(org, oc):
    m = make_user("m@example.com")
    add_member(org, m)
    t = make_tender()
    oc.post("/api/pipeline", {"tender": t.pk}, format="json")
    assert [b["tender"]["id"] for b in client_for(m).get("/api/pipeline").json()] == [t.pk]


def test_idor_pipeline(org):
    track = BidTrack.objects.create(organization=org, tender=make_tender(), notes="secret")
    stranger = make_user("s@example.com")
    make_org(stranger)
    c = client_for(stranger)
    assert c.get("/api/pipeline").json() == []
    assert c.get(f"/api/pipeline/{track.pk}").status_code == 404
    assert c.patch(f"/api/pipeline/{track.pk}", {"status": "dropped"}).status_code == 404
    assert c.delete(f"/api/pipeline/{track.pk}").status_code == 404
    assert c.get("/api/pipeline/summary").json()["by_status"]["watching"] == 0
    track.refresh_from_db()
    assert track.status == "watching"
    # Tracking the same tender in another org is a separate entry.
    assert c.post("/api/pipeline", {"tender": track.tender_id}).status_code == 201
    assert BidTrack.objects.count() == 2


def test_summary(oc, org):
    now = timezone.now()
    soon = make_tender(closes_at=now + timedelta(days=2), value_inr=Decimal("1000000"))
    later = make_tender(closes_at=now + timedelta(days=30), value_inr=Decimal("2000000"))
    won = make_tender(value_inr=Decimal("9000000"))
    submitted = make_tender(closes_at=now + timedelta(days=1), value_inr=Decimal("7000000"))
    BidTrack.objects.create(organization=org, tender=soon, status="preparing")
    BidTrack.objects.create(organization=org, tender=later, bid_amount_inr=Decimal("1500000.50"))
    BidTrack.objects.create(organization=org, tender=won, status="won")
    BidTrack.objects.create(organization=org, tender=submitted, status="submitted")
    body = oc.get("/api/pipeline/summary").json()
    assert body["by_status"] == {
        "watching": 1,
        "preparing": 1,
        "submitted": 1,
        "won": 1,
        "lost": 0,
        "dropped": 0,
    }
    assert [b["tender"]["id"] for b in body["closing_soon"]] == [soon.pk]
    # 10 lakh (tender value) + 15,00,000.50 (bid amount) + 70 lakh (submitted)
    assert body["value_inr_in_play"] == "9500000.50"


# --- reminders ----------------------------------------------------------------------------


def test_daily_reminders_once_per_day(org, owner):
    now = timezone.now()
    m = make_user("m@example.com")
    add_member(org, m, active=False)
    t1 = make_tender(closes_at=now + timedelta(days=1), title="Bridge repair")
    t2 = make_tender(closes_at=now + timedelta(days=2), title="School building")
    BidTrack.objects.create(organization=org, tender=t1, owner=m)
    BidTrack.objects.create(organization=org, tender=t2)  # no owner: org owners get it
    BidTrack.objects.create(
        organization=org, tender=make_tender(closes_at=now + timedelta(days=1)), status="submitted"
    )
    BidTrack.objects.create(organization=org, tender=make_tender(closes_at=now + timedelta(days=5)))
    BidTrack.objects.create(
        organization=org, tender=make_tender(closes_at=now - timedelta(hours=1))
    )

    assert send_pipeline_reminders() == 2
    by_to = {msg.to[0]: msg for msg in mail.outbox}
    assert set(by_to) == {"m@example.com", "owner@example.com"}
    assert "Bridge repair" in by_to["m@example.com"].body
    assert "School building" not in by_to["m@example.com"].body
    assert "School building" in by_to["owner@example.com"].body
    assert "1 tender in Acme, Infra; Ltd's pipeline closes" in by_to["owner@example.com"].subject
    assert ReminderLog.objects.count() == 2

    assert send_pipeline_reminders() == 0  # idempotent per day
    assert len(mail.outbox) == 2


def test_reminder_failure_releases_claim(org, monkeypatch):
    BidTrack.objects.create(
        organization=org, tender=make_tender(closes_at=timezone.now() + timedelta(days=1))
    )

    def boom(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr("workspaces.tasks.send_mail", boom)
    assert send_pipeline_reminders() == 0
    assert ReminderLog.objects.count() == 0


def test_reminder_task_in_beat_schedule(settings):
    entry = settings.CELERY_BEAT_SCHEDULE["pipeline-reminders"]
    assert entry["task"] == "workspaces.tasks.send_pipeline_reminders"


# --- iCal feed ----------------------------------------------------------------------------


def _unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def _feed(oc):
    url = oc.get("/api/workspace").json()["calendar_url"]
    path = url.split("localhost:8080", 1)[1]
    return path, APIClient().get(path)


def test_calendar_feed_is_valid_ics(oc, org):
    now = timezone.now().replace(microsecond=0)
    long_title = "Construction of 2-lane road, with drains; culverts\nand " + "very long " * 12
    t = make_tender(
        title=long_title,
        closes_at=now + timedelta(days=4),
        opens_at=now + timedelta(days=5),
        location="Raipur, Chhattisgarh",
    )
    track = BidTrack.objects.create(organization=org, tender=t, status="preparing")
    BidTrack.objects.create(organization=org, tender=make_tender(title="Done"), status="submitted")

    path, r = _feed(oc)
    assert r.status_code == 200
    assert r["Content-Type"] == "text/calendar; charset=utf-8"
    raw = r.content.decode()
    # Every physical line ends in CRLF and fits 75 octets.
    assert raw.endswith("\r\n") and "\n" not in raw.replace("\r\n", "")
    assert all(len(line.encode()) <= 75 for line in raw.split("\r\n"))
    lines = _unfold(raw)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR" and lines[-1] == ""
    assert "VERSION:2.0" in lines and any(x.startswith("PRODID:") for x in lines)
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 2  # due + opening
    assert "X-WR-CALNAME:TenderLens: Acme\\, Infra\\; Ltd" in lines
    summary = next(x for x in lines if x.startswith("SUMMARY:Bid due"))
    assert "road\\, with drains\\; culverts\\nand" in summary
    uids = [x for x in lines if x.startswith("UID:")]
    assert uids == [
        f"UID:bidtrack-{track.pk}-due@localhost",
        f"UID:bidtrack-{track.pk}-opening@localhost",
    ]
    assert f"DTEND:{ical.utc(t.closes_at)}" in lines
    assert all(
        re.fullmatch(r"\d{8}T\d{6}Z", x.split(":", 1)[1])
        for x in lines
        if x.startswith(("DTSTART", "DTEND", "DTSTAMP"))
    )
    assert f"URL:http://localhost:8080/tenders/{t.pk}" in lines
    assert "Done" not in raw
    # Stable UIDs across polls.
    assert APIClient().get(path).content == r.content


def test_calendar_token_auth_and_rotation(oc, org, owner):
    path, r = _feed(oc)
    assert r.status_code == 200
    assert APIClient().get("/api/pipeline/calendar.ics").status_code == 404
    assert APIClient().get("/api/pipeline/calendar.ics?token=" + "x" * 43).status_code == 404

    m = make_user("m@example.com")
    add_member(org, m, active=False)
    from workspaces.services import set_active_org

    set_active_org(m, org)
    assert client_for(m).post("/api/workspace/calendar-token").status_code == 403

    r = oc.post("/api/workspace/calendar-token")
    assert r.status_code == 200
    new_path = r.json()["calendar_url"].split("localhost:8080", 1)[1]
    assert new_path != path
    assert APIClient().get(path).status_code == 404
    assert APIClient().get(new_path).status_code == 200


def test_fold_never_splits_utf8():
    line = "SUMMARY:" + "भवन निर्माण कार्य " * 10
    folded = ical.fold(line)
    for part in folded.split("\r\n"):
        assert len(part.encode()) <= 75
    assert folded.replace("\r\n ", "") == line


def test_escape():
    assert ical.escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
