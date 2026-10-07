"""Workspace, members, invites, organisation switching and API keys (/api/workspace...)."""

import hashlib
from datetime import timedelta
from decimal import Decimal
from itertools import count

import pytest
from django.contrib.auth import get_user_model
from django.core import mail, signing
from django.utils import timezone
from rest_framework.exceptions import NotFound
from rest_framework.test import APIClient

from tenders.models import Tender
from workspaces import invites
from workspaces.auth import hash_key
from workspaces.models import ApiKey, BidTrack, Invite, Membership, Organization
from workspaces.services import get_active_org

pytestmark = pytest.mark.django_db
User = get_user_model()
_seq = count(1)


# --- helpers shared by the SaaS test files ------------------------------------------------


def make_user(email: str, **kw):
    return User.objects.create(username=email, email=email, **kw)


def make_org(owner, plan="free", name=None, **kw) -> Organization:
    """An organisation with `owner` as its owner, made the owner's active one."""
    n = next(_seq)
    org = Organization.objects.create(
        name=name or f"Org {n}", slug=f"org-{n}", plan_code=plan, **kw
    )
    Membership.objects.filter(user=owner, is_active=True).update(is_active=False)
    Membership.objects.create(user=owner, organization=org, role="owner", is_active=True)
    return org


def add_member(org, user, role="member", active=True) -> Membership:
    if active:
        Membership.objects.filter(user=user, is_active=True).update(is_active=False)
    return Membership.objects.create(user=user, organization=org, role=role, is_active=active)


def client_for(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user)
    return c


def make_tender(**kw) -> Tender:
    n = next(_seq)
    now = timezone.now()
    data = dict(
        source="central",
        source_tender_id=f"2026_TST_{n}_1",
        ref_no=f"REF/{n}",
        title=f"Construction of road {n}",
        buyer_raw="Public Works Department",
        state="Chhattisgarh",
        sector="roads",
        category="Works",
        published_at=now - timedelta(days=2),
        closes_at=now + timedelta(days=10),
        url=f"https://eprocure.gov.in/eprocure/app?page=FrontEndViewTender&sp={n}",
        content_hash=hashlib.sha256(str(n).encode()).hexdigest(),
        fetched_at=now,
        first_seen=now,
        last_seen=now,
    )
    data.update(kw)
    return Tender.objects.create(**data)


@pytest.fixture
def owner():
    return make_user("owner@example.com", first_name="Olga", last_name="Owner")


@pytest.fixture
def org(owner):
    return make_org(owner, plan="team", name="Acme Infra")


@pytest.fixture
def oc(owner, org):
    return client_for(owner)


# --- GET / PATCH workspace ----------------------------------------------------------------


def test_workspace_shape(oc, org):
    r = oc.get("/api/workspace")
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in ("id", "name", "slug", "role")} == {
        "id": org.pk,
        "name": "Acme Infra",
        "slug": org.slug,
        "role": "owner",
    }
    assert body["plan"]["code"] == "team"
    assert body["usage"] == {
        "questions_per_month": 0,
        "documents_per_month": 0,
        "alerts": 0,
        "seats": 1,
    }
    assert set(body["profile"]) == {
        "annual_turnover_inr",
        "largest_similar_work_inr",
        "years_in_business",
        "states",
        "sectors",
        "certifications",
        "gstin",
    }
    assert body["calendar_url"].startswith("http://")
    assert "/api/pipeline/calendar.ics?token=" in body["calendar_url"]
    org.refresh_from_db()
    assert body["calendar_url"].endswith(org.calendar_token)


def test_first_visit_creates_personal_workspace():
    u = make_user("solo@example.com")
    r = client_for(u).get("/api/workspace")
    assert r.status_code == 200
    assert r.json()["role"] == "owner" and r.json()["plan"]["code"] == "free"


def test_anonymous_gets_403():
    assert APIClient().get("/api/workspace").status_code == 403
    assert APIClient().get("/api/pipeline").status_code == 403


def test_patch_profile_flat_and_nested(oc, org):
    r = oc.patch(
        "/api/workspace",
        {
            "name": "Acme Infra Pvt Ltd",
            "annual_turnover_inr": "25000000",
            "profile": {"states": ["Chhattisgarh", "Odisha"], "sectors": ["roads"]},
            "gstin": "22aaaaa0000a1z5",
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    org.refresh_from_db()
    assert org.name == "Acme Infra Pvt Ltd"
    assert org.annual_turnover_inr == Decimal("25000000")
    assert org.states == ["Chhattisgarh", "Odisha"] and org.sectors == ["roads"]
    assert org.gstin == "22AAAAA0000A1Z5"
    assert r.json()["profile"]["states"] == ["Chhattisgarh", "Odisha"]


@pytest.mark.parametrize(
    "payload",
    [
        {"sectors": ["not-a-sector"]},
        {"states": "Delhi"},
        {"annual_turnover_inr": "-5"},
        {"gstin": "123"},
        {"name": "  "},
    ],
)
def test_patch_rejects_bad_input(oc, payload):
    assert oc.patch("/api/workspace", payload, format="json").status_code == 400


def test_member_cannot_patch_org(org):
    m = make_user("m@example.com")
    add_member(org, m, "member")
    r = client_for(m).patch("/api/workspace", {"name": "Hijacked"}, format="json")
    assert r.status_code == 403
    org.refresh_from_db()
    assert org.name == "Acme Infra"


def test_admin_can_patch_org(org):
    a = make_user("a@example.com")
    add_member(org, a, "admin")
    assert client_for(a).patch("/api/workspace", {"name": "New"}, format="json").status_code == 200


# --- switching ----------------------------------------------------------------------------


def test_switch_active_organisation(owner, org):
    other = make_org(owner, name="Second Co")  # now active
    c = client_for(owner)
    assert c.get("/api/workspace").json()["id"] == other.pk
    listed = c.get("/api/workspaces").json()
    assert {(w["id"], w["active"]) for w in listed} == {(org.pk, False), (other.pk, True)}
    r = c.post("/api/workspace/switch", {"organization": org.pk}, format="json")
    assert r.status_code == 200 and r.json()["id"] == org.pk
    assert c.get("/api/workspace").json()["id"] == org.pk


def test_cannot_switch_to_foreign_org(org):
    stranger = make_user("s@example.com")
    r = client_for(stranger).post("/api/workspace/switch", {"organization": org.pk}, format="json")
    assert r.status_code == 404
    assert get_active_org(stranger).pk != org.pk


# --- members ------------------------------------------------------------------------------


def test_members_list_and_remove(oc, org):
    m = make_user("m@example.com", first_name="Mia")
    mm = add_member(org, m, active=False)
    rows = oc.get("/api/workspace/members").json()
    assert [(r["email"], r["role"]) for r in rows] == [
        ("owner@example.com", "owner"),
        ("m@example.com", "member"),
    ]
    assert rows[1]["name"] == "Mia" and rows[1]["id"] == mm.pk
    assert oc.delete(f"/api/workspace/members/{mm.pk}").status_code == 204
    assert not Membership.objects.filter(pk=mm.pk).exists()


def test_member_cannot_remove_others_but_can_leave(org, owner):
    m = make_user("m@example.com")
    mm = add_member(org, m)
    owner_m = Membership.objects.get(user=owner, organization=org)
    c = client_for(m)
    assert c.delete(f"/api/workspace/members/{owner_m.pk}").status_code == 403
    assert c.delete(f"/api/workspace/members/{mm.pk}").status_code == 204
    # The member now lands in a fresh personal workspace.
    assert get_active_org(m).pk != org.pk


def test_last_owner_cannot_leave(oc, org, owner):
    me = Membership.objects.get(user=owner, organization=org)
    assert oc.delete(f"/api/workspace/members/{me.pk}").status_code == 400


def test_admin_cannot_remove_owner(org, owner):
    a = make_user("a@example.com")
    add_member(org, a, "admin")
    owner_m = Membership.objects.get(user=owner, organization=org)
    assert client_for(a).delete(f"/api/workspace/members/{owner_m.pk}").status_code == 403


def test_owner_changes_roles_but_keeps_one_owner(oc, org, owner):
    m = make_user("m@example.com")
    mm = add_member(org, m, active=False)
    r = oc.patch(f"/api/workspace/members/{mm.pk}", {"role": "admin"}, format="json")
    assert r.status_code == 200 and r.json()["role"] == "admin"
    me = Membership.objects.get(user=owner, organization=org)
    assert oc.patch(f"/api/workspace/members/{me.pk}", {"role": "member"}).status_code == 400
    assert (
        client_for(m).patch(f"/api/workspace/members/{me.pk}", {"role": "member"}).status_code
        == 403
    )


def test_idor_members_of_another_org(org):
    stranger = make_user("s@example.com")
    make_org(stranger)
    m = make_user("m@example.com")
    mm = add_member(org, m, active=False)
    c = client_for(stranger)
    assert c.delete(f"/api/workspace/members/{mm.pk}").status_code == 404
    assert c.patch(f"/api/workspace/members/{mm.pk}", {"role": "owner"}).status_code == 404
    emails = [r["email"] for r in c.get("/api/workspace/members").json()]
    assert emails == ["s@example.com"]
    assert Membership.objects.filter(pk=mm.pk).exists()


def test_removing_member_clears_pipeline_ownership(oc, org):
    m = make_user("m@example.com")
    mm = add_member(org, m, active=False)
    track = BidTrack.objects.create(organization=org, tender=make_tender(), owner=m)
    oc.delete(f"/api/workspace/members/{mm.pk}")
    track.refresh_from_db()
    assert track.owner is None


# --- invites ------------------------------------------------------------------------------


def _token_from_mail() -> str:
    body = mail.outbox[-1].body
    return body.split("/invite/")[1].split()[0]


def test_invite_email_and_accept(oc, org):
    r = oc.post("/api/workspace/invites", {"email": "New@Example.com", "role": "admin"})
    assert r.status_code == 201, r.content
    assert r.json()["email"] == "new@example.com"
    assert mail.outbox[-1].to == ["new@example.com"]
    assert "Acme Infra" in mail.outbox[-1].subject
    token = _token_from_mail()
    assert mail.outbox[-1].body.count("http://localhost:8080/invite/") == 1

    preview = APIClient().get(f"/api/workspace/invites/{token}")
    assert preview.status_code == 200 and preview.json()["organization"] == "Acme Infra"

    invitee = make_user("new@example.com")
    r = client_for(invitee).post(f"/api/workspace/invites/{token}/accept")
    assert r.status_code == 200, r.content
    assert r.json()["id"] == org.pk and r.json()["role"] == "admin"
    assert get_active_org(invitee).pk == org.pk
    # Single use.
    again = client_for(invitee).post(f"/api/workspace/invites/{token}/accept")
    assert again.status_code == 404


def test_invite_needs_matching_email(oc, org):
    oc.post("/api/workspace/invites", {"email": "new@example.com"})
    token = _token_from_mail()
    r = client_for(make_user("other@example.com")).post(f"/api/workspace/invites/{token}/accept")
    assert r.status_code == 403
    assert not Membership.objects.filter(user__email="other@example.com", organization=org)


def test_invite_expiry(oc, org, settings):
    oc.post("/api/workspace/invites", {"email": "new@example.com"})
    token = _token_from_mail()
    Invite.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    r = client_for(make_user("new@example.com")).post(f"/api/workspace/invites/{token}/accept")
    assert r.status_code == 404


def test_invite_signature_expiry(oc, org, settings):
    """The signed token's own timestamp expires too, even if the row was extended."""
    oc.post("/api/workspace/invites", {"email": "new@example.com"})
    token = _token_from_mail()
    settings.INVITE_MAX_AGE_DAYS = 0
    with pytest.raises(NotFound):
        invites.read_token(token)


@pytest.mark.parametrize(
    "mangle", [lambda t: t[:-2] + "xx", lambda t: "garbage", lambda t: t + "a"]
)
def test_tampered_invite_token(oc, org, mangle):
    oc.post("/api/workspace/invites", {"email": "new@example.com"})
    token = mangle(_token_from_mail())
    r = client_for(make_user("new@example.com")).post(f"/api/workspace/invites/{token}/accept")
    assert r.status_code == 404


def test_forged_token_for_other_invite_rejected(oc, org):
    oc.post("/api/workspace/invites", {"email": "new@example.com"})
    inv = Invite.objects.get()
    forged = signing.dumps({"i": inv.pk, "n": "guess"}, salt=invites.SALT, compress=True)
    r = client_for(make_user("new@example.com")).post(f"/api/workspace/invites/{forged}/accept")
    assert r.status_code == 404


def test_revoked_invite(oc, org):
    oc.post("/api/workspace/invites", {"email": "new@example.com"})
    token = _token_from_mail()
    inv = Invite.objects.get()
    assert oc.get("/api/workspace/invites").json()[0]["id"] == inv.pk
    assert oc.delete(f"/api/workspace/invites/{inv.pk}").status_code == 204
    assert oc.get("/api/workspace/invites").json() == []
    r = client_for(make_user("new@example.com")).post(f"/api/workspace/invites/{token}/accept")
    assert r.status_code == 404


def test_seat_limit_counts_members_and_open_invites(org, oc):
    # Team plan: 5 seats. Owner + 3 members + 1 open invite = 5.
    for i in range(3):
        add_member(org, make_user(f"m{i}@example.com"), active=False)
    assert oc.post("/api/workspace/invites", {"email": "x@example.com"}).status_code == 201
    r = oc.post("/api/workspace/invites", {"email": "y@example.com"})
    assert r.status_code == 402
    assert r.json() == {
        "detail": "Your plan's limit for seats is reached.",
        "code": "quota_exceeded",
        "limit": "seats",
    }


def test_free_plan_cannot_invite(owner):
    make_org(owner, plan="free")
    r = client_for(owner).post("/api/workspace/invites", {"email": "x@example.com"})
    assert r.status_code == 402 and r.json()["limit"] == "seats"


def test_seat_limit_at_accept_after_downgrade(org, oc):
    oc.post("/api/workspace/invites", {"email": "new@example.com"})
    token = _token_from_mail()
    Organization.objects.filter(pk=org.pk).update(plan_code="free")
    r = client_for(make_user("new@example.com")).post(f"/api/workspace/invites/{token}/accept")
    assert r.status_code == 402


def test_member_cannot_invite(org):
    m = make_user("m@example.com")
    add_member(org, m)
    assert (
        client_for(m).post("/api/workspace/invites", {"email": "x@example.com"}).status_code == 403
    )


def test_invite_existing_member_rejected(oc, org):
    add_member(org, make_user("m@example.com"), active=False)
    assert oc.post("/api/workspace/invites", {"email": "M@example.com"}).status_code == 400


def test_cannot_invite_as_owner(oc):
    assert (
        oc.post("/api/workspace/invites", {"email": "x@example.com", "role": "owner"}).status_code
        == 400
    )


# --- API keys -----------------------------------------------------------------------------


@pytest.fixture
def ent(owner):
    return make_org(owner, plan="enterprise", name="Big Corp")


def test_api_key_lifecycle(oc, ent):
    r = oc.post("/api/workspace/api-keys", {"name": "ERP sync"})
    assert r.status_code == 201, r.content
    body = r.json()
    key = body["key"]
    assert key.startswith("tl_") and len(key) > 40
    assert body["prefix"] == key[:11]
    row = ApiKey.objects.get()
    assert row.key_hash == hash_key(key) and key not in (row.prefix, row.key_hash)
    listed = oc.get("/api/workspace/api-keys").json()
    assert [k["name"] for k in listed] == ["ERP sync"] and "key" not in listed[0]

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    r = api.get("/api/pipeline")
    assert r.status_code == 200
    row.refresh_from_db()
    assert row.last_used_at is not None

    assert oc.delete(f"/api/workspace/api-keys/{row.pk}").status_code == 204
    assert api.get("/api/pipeline").status_code == 403


def test_api_key_feature_gate(oc, org):
    r = oc.post("/api/workspace/api-keys", {"name": "x"})
    assert r.status_code == 402 and r.json()["limit"] == "api"


def test_api_key_stops_after_downgrade(oc, ent):
    key = oc.post("/api/workspace/api-keys", {"name": "x"}).json()["key"]
    Organization.objects.filter(pk=ent.pk).update(plan_code="pro")
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    r = api.get("/api/pipeline")
    assert r.status_code == 402 and r.json()["limit"] == "api"


def test_api_key_acts_in_its_own_org(owner, ent):
    key = client_for(owner).post("/api/workspace/api-keys", {"name": "x"}).json()["key"]
    t = make_tender()
    BidTrack.objects.create(organization=ent, tender=t)
    make_org(owner, name="Other")  # the owner switches away; the key stays with Big Corp
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    assert [b["tender"]["id"] for b in api.get("/api/pipeline").json()] == [t.pk]


def test_api_key_cannot_manage_workspace(oc, ent):
    key = oc.post("/api/workspace/api-keys", {"name": "x"}).json()["key"]
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    assert api.post("/api/workspace/api-keys", {"name": "y"}).status_code == 403
    assert api.get("/api/workspace/members").status_code == 403


@pytest.mark.parametrize("header", ["Api-Key nope", "Api-Key tl_wrong", "Api-Key "])
def test_bad_api_key(header):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=header)
    assert api.get("/api/pipeline").status_code == 403
    assert api.get("/api/tenders").status_code == 403


def test_api_key_of_departed_member_stops(ent):
    admin = make_user("admin@example.com")
    am = add_member(ent, admin, "admin")
    key = client_for(admin).post("/api/workspace/api-keys", {"name": "x"}).json()["key"]
    am.delete()
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    assert api.get("/api/pipeline").status_code == 403


def test_idor_api_keys(oc, ent):
    oc.post("/api/workspace/api-keys", {"name": "x"})
    row = ApiKey.objects.get()
    stranger = make_user("s@example.com")
    make_org(stranger, plan="enterprise")
    c = client_for(stranger)
    assert c.get("/api/workspace/api-keys").json() == []
    assert c.delete(f"/api/workspace/api-keys/{row.pk}").status_code == 404
    row.refresh_from_db()
    assert row.revoked_at is None


def test_member_cannot_manage_keys(ent):
    m = make_user("m@example.com")
    add_member(ent, m)
    assert client_for(m).post("/api/workspace/api-keys", {"name": "x"}).status_code == 403


def test_api_key_throttle(oc, ent, settings, monkeypatch):
    from workspaces.auth import ApiKeyRateThrottle

    monkeypatch.setattr(ApiKeyRateThrottle, "THROTTLE_RATES", {"api_key": "2/min"})
    key = oc.post("/api/workspace/api-keys", {"name": "x"}).json()["key"]
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    codes = [api.get("/api/pipeline").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
