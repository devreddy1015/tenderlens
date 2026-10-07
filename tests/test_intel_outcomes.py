"""Outcome capture: pipeline results (L1, winner, bidders, rank) become training rows
(intel/outcomes.py), and Organization.contribute_outcomes controls whether they are shared."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from intel import outcomes
from intel.models import HistoricalAward
from tests.test_workspaces import add_member, client_for, make_org, make_tender, make_user
from workspaces.models import BidTrack

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return make_user("owner@example.com")


@pytest.fixture
def org(owner):
    return make_org(owner, plan="team", name="Acme Infra")


@pytest.fixture
def oc(owner, org):
    return client_for(owner)


@pytest.fixture
def track(org):
    tender = make_tender(value_inr=Decimal("10000000"), tender_type="Open Tender")
    return BidTrack.objects.create(organization=org, tender=tender, status="submitted")


def _patch(client, track, **data):
    return client.patch(f"/api/pipeline/{track.pk}", data, format="json")


def _rows():
    return HistoricalAward.objects.filter(source="tenderlens")


# --- the pipeline API -------------------------------------------------------------------


def test_won_with_l1_records_a_training_row(oc, org, track):
    r = _patch(oc, track, status="won", l1_amount_inr="9000000", num_bidders=5, our_rank=1)
    assert r.status_code == 200, r.content
    body = r.json()
    assert (body["l1_amount_inr"], body["winner_name"], body["num_bidders"], body["our_rank"]) == (
        "9000000.00",
        "",
        5,
        1,
    )
    a = _rows().get()
    t = track.tender
    assert a.source_id == f"{org.pk}:{t.pk}"
    assert (a.estimated_value, a.award_value, a.ratio) == (
        Decimal("10000000.00"),
        Decimal("9000000.00"),
        pytest.approx(0.9),
    )
    assert a.num_bidders == 5 and a.winner == "Acme Infra"  # won, no name given: us
    assert a.organization_id == org.pk and a.tender_id == t.pk and a.shared is True
    assert (a.country, a.state, a.sector, a.category, a.method) == (
        "IN",
        "Chhattisgarh",
        "roads",
        "works",
        "open",
    )
    assert a.title == t.title and a.buyer == "Public Works Department" and a.url == t.url
    assert a.award_date == timezone.localdate() and a.year == timezone.localdate().year


def test_lost_uses_the_named_winner(oc, track):
    _patch(oc, track, status="lost", l1_amount_inr="8500000", winner_name="  M/s Rival Infra ")
    a = _rows().get()
    assert a.winner == "M/s Rival Infra" and a.winner_key == "m s rival infra"
    assert a.ratio == pytest.approx(0.85)
    # Lost without a name: the winner is unknown, never us.
    _patch(oc, track, winner_name="")
    assert _rows().get().winner == ""


def test_outcome_is_idempotent_and_keeps_its_first_date(oc, track):
    _patch(oc, track, status="won", l1_amount_inr="9000000")
    _rows().update(award_date=date(2026, 1, 15))
    for _ in range(2):
        assert _patch(oc, track, notes="kick-off meeting booked").status_code == 200
    a = _rows().get()
    assert a.award_date == date(2026, 1, 15) and a.award_value == Decimal("9000000.00")
    _patch(oc, track, l1_amount_inr="9100000")
    assert _rows().get().award_value == Decimal("9100000.00") and _rows().count() == 1


@pytest.mark.parametrize(
    "change",
    [
        {"status": "submitted"},  # left won/lost
        {"status": "dropped"},
        {"l1_amount_inr": None},  # L1 cleared
        {"l1_amount_inr": "0"},
    ],
)
def test_row_is_removed_when_the_outcome_no_longer_holds(oc, track, change):
    _patch(oc, track, status="lost", l1_amount_inr="9500000")
    assert _rows().count() == 1
    assert _patch(oc, track, **change).status_code == 200
    assert _rows().count() == 0


def test_no_row_without_l1_or_tender_value(oc, org):
    no_value = BidTrack.objects.create(organization=org, tender=make_tender(value_inr=None))
    _patch(oc, no_value, status="won", l1_amount_inr="500000")
    plain = BidTrack.objects.create(organization=org, tender=make_tender(value_inr=Decimal("1e6")))
    _patch(oc, plain, status="won")
    submitted = BidTrack.objects.create(
        organization=org, tender=make_tender(value_inr=Decimal("1e6"))
    )
    _patch(oc, submitted, status="submitted", l1_amount_inr="900000")  # result not in yet
    assert _rows().count() == 0
    assert BidTrack.objects.get(pk=submitted.pk).l1_amount_inr == Decimal("900000")


def test_implausible_ratio_is_kept_without_a_ratio(oc, track):
    _patch(oc, track, status="lost", l1_amount_inr="100000")  # 1% of the estimate
    a = _rows().get()
    assert a.ratio is None and a.award_value == Decimal("100000.00")


def test_deleting_the_track_deletes_its_outcome(oc, track):
    _patch(oc, track, status="won", l1_amount_inr="9000000")
    assert oc.delete(f"/api/pipeline/{track.pk}").status_code == 204
    assert _rows().count() == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"l1_amount_inr": "-1"},
        {"l1_amount_inr": "lots"},
        {"l1_amount_inr": "1" * 20},
        {"num_bidders": 0},
        {"num_bidders": 501},
        {"num_bidders": "many"},
        {"our_rank": 0},
        {"our_rank": 3, "num_bidders": 2},
        {"winner_name": "x" * 301},
        {"winner_name": None},
    ],
)
def test_outcome_validation(oc, track, payload):
    r = _patch(oc, track, status="lost", **payload)
    assert r.status_code == 400, r.content
    assert BidTrack.objects.get(pk=track.pk).status == "submitted"
    assert _rows().count() == 0


def test_rank_is_checked_against_the_stored_bidder_count(oc, track):
    assert _patch(oc, track, num_bidders=3).status_code == 200
    assert _patch(oc, track, our_rank=4).status_code == 400
    assert _patch(oc, track, our_rank=3).status_code == 200
    r = _patch(oc, track, num_bidders=2)
    assert r.status_code == 400 and "our_rank" in r.json()
    assert _patch(oc, track, num_bidders=None).status_code == 200  # unknown count: any rank
    assert _patch(oc, track, our_rank=None, num_bidders=500).status_code == 200


def test_database_enforces_the_ranges(org):
    tender = make_tender()
    for bad in ({"num_bidders": 0}, {"num_bidders": 3, "our_rank": 4}, {"l1_amount_inr": -1}):
        with pytest.raises(IntegrityError), transaction.atomic():
            BidTrack.objects.create(organization=org, tender=tender, **bad)


def test_team_member_records_outcomes_but_strangers_cannot(org, track):
    member = make_user("m@example.com")
    add_member(org, member)
    assert _patch(client_for(member), track, status="won", l1_amount_inr="9e6").status_code == 200
    assert _rows().count() == 1

    stranger = make_user("s@example.com")
    make_org(stranger)
    r = _patch(client_for(stranger), track, status="dropped")
    assert r.status_code == 404
    assert _rows().count() == 1


def test_anonymous_cannot_patch(track):
    from rest_framework.test import APIClient

    assert _patch(APIClient(), track, status="won").status_code == 403


# --- contribute_outcomes ----------------------------------------------------------------


def test_workspace_exposes_contribute_outcomes(oc, org):
    body = oc.get("/api/workspace").json()
    assert body["contribute_outcomes"] is True
    assert "contribute_outcomes" not in body["profile"]


def test_switching_sharing_off_updates_existing_and_new_rows(oc, org, owner, track):
    _patch(oc, track, status="won", l1_amount_inr="9000000")
    # Another organisation's outcome must not be touched.
    other_owner = make_user("o@example.com")
    other = make_org(other_owner)
    other_track = BidTrack.objects.create(
        organization=other, tender=make_tender(value_inr=Decimal("2e6")), status="lost"
    )
    other_track.l1_amount_inr = Decimal("1800000")
    other_track.save()
    outcomes.record_outcome(other_track)

    r = oc.patch("/api/workspace", {"contribute_outcomes": False}, format="json")
    assert r.status_code == 200 and r.json()["contribute_outcomes"] is False
    assert _rows().get(organization=org).shared is False
    assert _rows().get(organization=other).shared is True

    later = BidTrack.objects.create(organization=org, tender=make_tender(value_inr=Decimal("3e6")))
    _patch(oc, later, status="lost", l1_amount_inr="2700000")
    assert _rows().get(tender=later.tender).shared is False

    oc.patch("/api/workspace", {"contribute_outcomes": True}, format="json")
    assert set(_rows().filter(organization=org).values_list("shared", flat=True)) == {True}


def test_only_owner_or_admin_changes_sharing(org):
    member = make_user("m@example.com")
    add_member(org, member)
    r = client_for(member).patch("/api/workspace", {"contribute_outcomes": False}, format="json")
    assert r.status_code == 403
    org.refresh_from_db()
    assert org.contribute_outcomes is True

    admin = make_user("a@example.com")
    add_member(org, admin, role="admin")
    r = client_for(admin).patch("/api/workspace", {"contribute_outcomes": False}, format="json")
    assert r.status_code == 200
    org.refresh_from_db()
    assert org.contribute_outcomes is False


@pytest.mark.parametrize("value", ["maybe", None, [True]])
def test_contribute_outcomes_bad_input(oc, org, value):
    assert (
        oc.patch("/api/workspace", {"contribute_outcomes": value}, format="json").status_code == 400
    )
    org.refresh_from_db()
    assert org.contribute_outcomes is True


# --- the service on its own -------------------------------------------------------------


def test_record_outcome_uses_the_resolved_buyer_and_category(org):
    from tenders.models import BuyerEntity

    buyer = BuyerEntity.objects.create(canonical_name="PWD Raipur Division", norm_key="pwd raipur")
    tender = make_tender(
        value_inr=Decimal("4000000"),
        buyer_entity=buyer,
        category="Consultancy",
        tender_type="Limited",
        published_at=timezone.now() - timedelta(days=40),
        closes_at=timezone.now() - timedelta(days=20),
    )
    track = BidTrack.objects.create(
        organization=org, tender=tender, status="lost", l1_amount_inr=Decimal("3000000")
    )
    a = outcomes.record_outcome(track)
    assert (a.buyer, a.category, a.method) == ("PWD Raipur Division", "consultancy", "limited")
    assert a.tender_date == timezone.localtime(tender.published_at).date()
    assert outcomes.record_outcome(track).pk == a.pk  # idempotent
    track.status = "watching"
    assert outcomes.record_outcome(track) is None and _rows().count() == 0
