"""Stage-2 follow-ups: chunk context for global Copilot retrieval, the pre-bid meeting date
(portal -> Tender -> API -> iCal, and from a Copilot brief), cancelling superseded Razorpay
subscriptions, and alert keywords matched by the tender search."""

import json
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from alerts import matching
from billing.models import Subscription
from copilot import ingest
from copilot.chunking import document_context, document_title
from copilot.extract import Page, extract
from copilot.models import Chunk, Document
from copilot.retrieval import GLOBAL_WEIGHTS, SCOPED_WEIGHTS, Filters, search
from ingest.loader import load_detail_page
from ingest.parsers import gepnic
from ingest.validation import TenderIn, validate_detail
from tenders.models import Tender
from tests.conftest import CENTRAL, FIXTURES
from tests.test_billing import _event, _post_webhook
from tests.test_workspaces import make_org, make_tender, make_user
from workspaces import ical
from workspaces.models import BidTrack

pytestmark = pytest.mark.django_db
IST = ZoneInfo("Asia/Kolkata")
COPILOT = FIXTURES / "copilot"
DDA = COPILOT / "NIT_2026_DDA_928070_1.pdf"
ITBP = COPILOT / "NIT_2026_ITBP_925996_1.pdf"


@pytest.fixture(autouse=True)
def _copilot_settings(settings, tmp_path):
    settings.EMBEDDING_MODEL = "fake"
    settings.RERANKER_MODEL = ""
    settings.MEDIA_ROOT = tmp_path / "media"


def _ingest(org, path: Path, tender=None) -> Document:
    doc = Document.objects.create(
        organization=org,
        tender=tender,
        filename=path.name,
        file=str(path),
        sha256=path.name,
        bytes=path.stat().st_size,
    )
    return ingest.process(doc, path=path)


# --- 1. chunk context --------------------------------------------------------------------


def test_document_title_reads_the_wrapped_name_of_work():
    pages = extract(ITBP, ocr=False).pages
    assert document_title(pages) == (
        "Construction of SOs and Jawan Living Accomadation at Lower Rimkhim 1 BN ITBP"
    )
    assert document_context(pages).endswith("· 2026_ITBP_925996_1")


def test_document_title_variants_and_absence():
    assert document_title([Page(1, "Subject: Repair of roof at Raipur station\nEMD: Rs 1")]) == (
        "Repair of roof at Raipur station"
    )
    assert document_title([Page(1, "NAME OF THE WORK:\nDesilting of drains, Ward 7\n")]) == (
        "Desilting of drains, Ward 7"
    )
    assert document_title([Page(1, "EMD: Rs. 10,000\nTender fee: Rs. 500")]) == ""


def test_context_prefers_the_linked_tender_and_skips_repeats():
    t = make_tender(title="M/o Completed scheme under North Zone.", source_tender_id="2026_X_1_1")
    ctx = document_context(extract(DDA, ocr=False).pages, tender=t)
    assert ctx.startswith("M/o Completed scheme under North Zone. · 2026_X_1_1 · ")
    assert ctx.count("Completed scheme") == 1  # the PDF's own title repeats the tender's
    assert "2026_DDA_928070_1" in ctx


def test_chunks_carry_context_but_quotes_do_not():
    org = make_org(make_user("ctx@example.com"))
    doc = _ingest(org, ITBP)
    chunks = list(doc.chunks.all())
    assert chunks and all(c.context.startswith("Construction of SOs") for c in chunks)
    hits = search("earnest money Jawan Living Accomadation", Filters(org.pk), mode="fts")
    assert hits and all(
        "Construction of SOs" not in h.text or h.text.find("Name of work") >= 0 for h in hits
    )
    assert all(h.context.startswith("Construction of SOs") for h in hits)


def test_global_search_finds_the_named_tenders_clause():
    """The EMD clause of the ITBP notice does not mention the work; its context does."""
    org = make_org(make_user("global@example.com"))
    itbp, dda = _ingest(org, ITBP), _ingest(org, DDA)
    for mode in ("fts", "dense", "hybrid"):
        hits = search(
            "earnest money deposit for Jawan Living Accomadation at Lower Rimkhim",
            Filters(org.pk),
            mode=mode,
            k=3,
        )
        assert hits[0].document_id == itbp.pk, mode
    # The ITBP notice has a whole "EARNEST MONEY DEPOSIT" section (heading weight) and the
    # DDA notice only a clause: naming the DDA work still brings its clause to the top.
    question = "EMD for M/o Completed scheme under North Zone"
    hits = search(question, Filters(org.pk), mode="fts")
    assert hits[0].document_id == dda.pk
    assert "EMD" in hits[0].text or "Earnest" in hits[0].text
    assert search(question, Filters(org.pk), mode="hybrid")[0].document_id == dda.pk


def test_context_has_no_weight_inside_one_document():
    assert SCOPED_WEIGHTS[1] == 0 and GLOBAL_WEIGHTS[1] > 0


def test_reindex_command_backfills_context_and_embeddings():
    org = make_org(make_user("reindex@example.com"))
    doc = _ingest(org, DDA)
    Chunk.objects.filter(document=doc).update(context="")
    before = list(doc.chunks.values_list("embedding", flat=True))
    out = StringIO()
    call_command("copilot_reindex", "--missing-context", stdout=out)
    assert f"Reindexed 1 documents ({len(before)} chunks)" in out.getvalue()
    assert set(doc.chunks.values_list("context", flat=True)) == {
        "M/o Completed scheme under North Zone. · 2026_DDA_928070_1"
    }
    # Already filled: nothing to do.
    out = StringIO()
    call_command("copilot_reindex", "--missing-context", stdout=out)
    assert "Reindexed 0 documents" in out.getvalue()


def test_reindex_after_linking_a_tender_uses_its_title():
    org = make_org(make_user("link@example.com"))
    doc = _ingest(org, DDA)
    doc.tender = make_tender(title="Maintenance of DDA North Zone parks")
    doc.save(update_fields=["tender"])
    assert ingest.reindex(doc) == doc.chunks.count()
    hits = search("parks maintenance", Filters(org.pk), mode="fts", k=1)
    assert hits and hits[0].document_id == doc.pk


# --- 2. pre-bid meeting ------------------------------------------------------------------


def test_parser_reads_prebid_meeting():
    raw = gepnic.parse_detail((CENTRAL / "detail_07.html").read_text(encoding="utf-8"))
    assert raw["prebid"] == "11-Aug-2026 02:30 PM"
    raw = gepnic.parse_detail((CENTRAL / "detail_01.html").read_text(encoding="utf-8"))
    assert raw["prebid"] == "NA"


def test_loader_stores_prebid_meeting(make_page):
    r = load_detail_page(make_page((CENTRAL / "detail_07.html").read_text(encoding="utf-8")))
    assert r.outcome == "new"
    t = Tender.objects.get(pk=r.tender_id)
    assert t.prebid_meeting == datetime(2026, 8, 11, 14, 30, tzinfo=IST)
    r = load_detail_page(make_page((CENTRAL / "detail_01.html").read_text(encoding="utf-8")))
    assert Tender.objects.get(pk=r.tender_id).prebid_meeting is None


def test_unreadable_prebid_is_unknown_not_quarantined(make_page):
    html = (CENTRAL / "detail_07.html").read_text(encoding="utf-8")
    html = html.replace("11-Aug-2026 02:30 PM", "As per NIT")
    r = load_detail_page(make_page(html))
    assert r.outcome == "new"
    assert Tender.objects.get(pk=r.tender_id).prebid_meeting is None


def test_hash_unchanged_for_tenders_without_prebid():
    """Tenders loaded before the field existed keep their content hash (no mass rewrite)."""
    raw = gepnic.parse_detail((CENTRAL / "detail_01.html").read_text(encoding="utf-8"))
    t, _ = validate_detail(raw, source="central", url="u", state="")
    legacy = TenderIn.model_construct(**t.model_dump(exclude={"prebid_meeting"}))
    data = legacy.model_dump(mode="json", exclude={"url", "prebid_meeting"})
    import hashlib

    blob = json.dumps(data, sort_keys=True, ensure_ascii=False)
    assert t.content_hash() == hashlib.sha256(blob.encode()).hexdigest()
    with_prebid = t.model_copy(update={"prebid_meeting": timezone.now()})
    assert with_prebid.content_hash() != t.content_hash()


def test_portal_na_keeps_a_date_read_by_the_copilot(make_page):
    html = (CENTRAL / "detail_07.html").read_text(encoding="utf-8")
    r = load_detail_page(make_page(html))
    when = datetime(2026, 8, 12, 11, 0, tzinfo=IST)
    Tender.objects.filter(pk=r.tender_id).update(prebid_meeting=when)
    changed = html.replace("11-Aug-2026 02:30 PM", "NA").replace("Transport Bhawan", "Transport B")
    assert load_detail_page(make_page(changed)).outcome == "updated"
    assert Tender.objects.get(pk=r.tender_id).prebid_meeting == when


def test_tender_detail_api_exposes_prebid_meeting():
    t = make_tender(prebid_meeting=datetime(2026, 10, 9, 11, 0, tzinfo=IST))
    body = APIClient().get(f"/api/tenders/{t.pk}").json()
    assert body["prebid_meeting"].startswith("2026-10-09T")
    assert "prebid_meeting" in APIClient().get(f"/api/tenders/{make_tender().pk}").json()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("03-Oct-2026 at 11:00 AM", datetime(2026, 10, 3, 11, 0, tzinfo=IST)),
        ("15.10.2026, 15:00 hrs", datetime(2026, 10, 15, 15, 0, tzinfo=IST)),
        ("15.10.2026 at 3.30 PM", datetime(2026, 10, 15, 15, 30, tzinfo=IST)),
        ("October 1, 2026", None),  # no time: not confident
        ("03-Oct-2026 or 05-Oct-2026 at 11:00 AM", None),  # two dates
        ("03-Oct-2026 at 13:00 PM", None),
    ],
)
def test_brief_datetime(value, expected):
    assert ingest.brief_datetime(value) == expected


def _dda_tender(**kw):
    data = dict(
        source_tender_id="2026_DDA_928070_1",
        published_at=datetime(2026, 9, 20, 10, 0, tzinfo=IST),
        closes_at=datetime(2026, 10, 3, 15, 0, tzinfo=IST),
    )
    data.update(kw)
    return make_tender(**data)


def test_copilot_fills_an_empty_prebid_meeting():
    org = make_org(make_user("prebid@example.com"))
    t = _dda_tender()
    _ingest(org, DDA, tender=t)
    t.refresh_from_db()
    assert t.prebid_meeting == datetime(2026, 10, 3, 11, 0, tzinfo=IST)


@pytest.mark.parametrize(
    "kw",
    [
        {"prebid_meeting": datetime(2026, 10, 1, 10, 0, tzinfo=IST)},  # the portal's wins
        {"closes_at": datetime(2026, 10, 2, 15, 0, tzinfo=IST)},  # after closing: implausible
        {"source_tender_id": "2026_OTHER_1_1"},  # the PDF names another tender
    ],
)
def test_copilot_does_not_fill_when_not_confident(kw):
    org = make_org(make_user("noprebid@example.com"))
    t = _dda_tender(**kw)
    before = t.prebid_meeting
    _ingest(org, DDA, tender=t)
    t.refresh_from_db()
    assert t.prebid_meeting == before


def _calendar_lines(org) -> list[str]:
    return ical.calendar(org).replace("\r\n ", "").split("\r\n")


def test_ical_has_a_prebid_meeting_event():
    org = make_org(make_user("cal@example.com"))
    now = timezone.now().replace(microsecond=0)
    t = make_tender(
        title="Road works, phase 2",
        prebid_meeting=now + timedelta(days=2),
        closes_at=now + timedelta(days=6),
        location="Raipur",
    )
    track = BidTrack.objects.create(organization=org, tender=t, status="watching")
    lines = _calendar_lines(org)
    assert lines.count("BEGIN:VEVENT") == 2
    i = lines.index(f"UID:bidtrack-{track.pk}-prebid@localhost")
    event = lines[i : lines.index("END:VEVENT", i)]
    assert "SUMMARY:Pre-bid meeting: Road works\\, phase 2" in event
    assert f"DTSTART:{ical.utc(t.prebid_meeting)}" in event
    assert f"DTEND:{ical.utc(t.prebid_meeting + timedelta(hours=1))}" in event
    assert not any(x.startswith("LOCATION:") for x in event)  # the venue is not the site
    assert "TRIGGER:-P1D" in event


def test_ical_skips_missing_or_implausible_prebid():
    org = make_org(make_user("cal2@example.com"))
    now = timezone.now()
    BidTrack.objects.create(organization=org, tender=make_tender(), status="watching")
    late = make_tender(prebid_meeting=now + timedelta(days=20), closes_at=now + timedelta(days=5))
    BidTrack.objects.create(organization=org, tender=late, status="preparing")
    assert not any("-prebid@" in x for x in _calendar_lines(org))


# --- 3. Razorpay upgrades ----------------------------------------------------------------

CANCEL = "https://api.razorpay.com/v1/subscriptions/{}/cancel"


def _sub(org, sub_id, status="created", plan="pro"):
    return Subscription.objects.create(
        organization=org,
        plan_code=plan,
        interval="month",
        provider="razorpay",
        provider_subscription_id=sub_id,
        status=status,
    )


def _event_for(event, sub_id, plan_id="plan_team_m"):
    body = json.loads(_event(event, sub_id=sub_id))
    body["payload"]["subscription"]["entity"]["plan_id"] = plan_id
    return json.dumps(body).encode()


@pytest.fixture
def upgraded(razorpay, django_capture_on_commit_callbacks):
    """An organisation on Pro (sub_old) that bought Team (sub_new): returns a function that
    delivers sub_new's activation and runs the on-commit callbacks."""
    org = make_org(make_user("upgrade@example.com"))
    old = _sub(org, "sub_old", status="active")
    new = _sub(org, "sub_new", plan="team")

    def activate(event_id="evt_up"):
        with django_capture_on_commit_callbacks(execute=True):
            r = _post_webhook(_event_for("subscription.activated", "sub_new"), event_id)
        assert r.status_code == 200, r.content
        return r

    return org, old, new, activate


@pytest.fixture
def razorpay(settings):
    settings.BILLING_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID = "rzp_test_key"
    settings.RAZORPAY_KEY_SECRET = "rzp_secret"
    settings.RAZORPAY_WEBHOOK_SECRET = "whsec_test"
    settings.RAZORPAY_PLAN_IDS = {"PRO_MONTH": "plan_pro_m", "TEAM_MONTH": "plan_team_m"}


@respx.mock
def test_upgrade_cancels_the_superseded_razorpay_subscription(upgraded):
    org, old, new, activate = upgraded
    route = respx.post(CANCEL.format("sub_old")).mock(
        return_value=httpx.Response(200, json={"id": "sub_old", "status": "cancelled"})
    )
    activate()
    assert route.call_count == 1
    req = route.calls[0].request
    assert json.loads(req.content) == {"cancel_at_cycle_end": 0}
    assert req.headers["authorization"].startswith("Basic ")
    old.refresh_from_db()
    new.refresh_from_db()
    org.refresh_from_db()
    assert old.status == "cancelled" and new.status == "active" and org.plan_code == "team"
    # A late renewal of the old one is ignored and does not take the plan back, but its
    # cancel is re-sent (idempotent at Razorpay).
    respx.post(CANCEL.format("sub_old")).mock(
        return_value=httpx.Response(
            400, json={"error": {"description": "Subscription is not cancellable in cancelled"}}
        )
    )
    from billing import services

    with pytest.MonkeyPatch.context() as mp:
        calls = []
        mp.setattr(services, "_enqueue_provider_cancel", calls.append)
        r = _post_webhook(_event_for("subscription.charged", "sub_old", "plan_pro_m"), "evt_late")
    assert "cancel re-sent" in WebhookResult.of("evt_late")
    org.refresh_from_db()
    assert org.plan_code == "team" and r.status_code == 200


class WebhookResult:
    @staticmethod
    def of(event_id: str) -> str:
        from billing.models import WebhookEvent

        return WebhookEvent.objects.get(event_id=event_id).result


@respx.mock
def test_cancel_already_cancelled_counts_as_done():
    from billing.services import cancel_razorpay_now

    respx.post(CANCEL.format("sub_x")).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "code": "BAD_REQUEST_ERROR",
                    "description": "Subscription is not cancellable in cancelled status.",
                }
            },
        )
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("django.conf.settings.RAZORPAY_KEY_ID", "k", raising=False)
        mp.setattr("django.conf.settings.RAZORPAY_KEY_SECRET", "s", raising=False)
        assert cancel_razorpay_now("sub_x") == "already ended"


@pytest.fixture
def worker_retries(settings):
    """Eager tasks that retry like a worker: with eager propagation (the test default) a
    Retry is raised to the caller instead of re-running the task inline."""
    settings.CELERY_TASK_EAGER_PROPAGATES = False


@respx.mock
def test_provider_failure_never_fails_the_webhook_and_is_retried(upgraded, worker_retries):
    org, old, new, activate = upgraded
    route = respx.post(CANCEL.format("sub_old")).mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(503), httpx.Response(200, json={})]
    )
    activate()  # 200 although Razorpay failed twice
    assert route.call_count == 3  # eager Celery runs the retries inline
    old.refresh_from_db()
    org.refresh_from_db()
    assert old.status == "cancelled" and org.plan_code == "team"


@respx.mock
def test_provider_giving_up_is_logged(upgraded, worker_retries, caplog, monkeypatch):
    from billing import tasks

    monkeypatch.setattr(tasks.cancel_at_provider, "max_retries", 1)
    org, old, new, activate = upgraded
    route = respx.post(CANCEL.format("sub_old")).mock(return_value=httpx.Response(500))
    activate()
    assert route.call_count == 2
    assert "giving up cancelling Razorpay subscription sub_old" in caplog.text
    org.refresh_from_db()
    assert org.plan_code == "team"


@respx.mock
def test_redelivered_activation_cancels_once(upgraded):
    org, old, new, activate = upgraded
    route = respx.post(CANCEL.format("sub_old")).mock(return_value=httpx.Response(200, json={}))
    activate("evt_same")
    activate("evt_same")  # duplicate delivery
    activate("evt_other")  # charged-like re-activation of the new one: nothing to supersede
    assert route.call_count == 1


@respx.mock
def test_first_subscription_has_nothing_to_cancel(razorpay, django_capture_on_commit_callbacks):
    org = make_org(make_user("first@example.com"))
    _sub(org, "sub_only")
    with django_capture_on_commit_callbacks(execute=True):
        _post_webhook(_event_for("subscription.activated", "sub_only", "plan_pro_m"), "evt_1")
    assert not respx.calls
    org.refresh_from_db()
    assert org.plan_code == "pro"


# --- 4. alerts use the tender search ------------------------------------------------------


@pytest.fixture
def alert_tenders():
    return {
        "toilets": make_tender(title="Construction of toilets at Ward 4", state="Delhi"),
        "bridge": make_tender(title="Repair of minor bridge on NH-30", state="Delhi"),
        "roads": make_tender(title="Road repair works in Durg", state="Delhi"),
        "road": make_tender(title="Widening of road near station", state="Delhi"),
        "aiims": make_tender(title="Supply of furniture", buyer_raw="AIIMS Raipur"),
    }


def _match(keywords: str) -> set[int]:
    qs = matching.matching_tenders(states=[], pin_prefixes=[], sectors=[], keywords=keywords)
    return set(qs.values_list("pk", flat=True))


def test_alert_keywords_stem_and_prefix(alert_tenders):
    t = alert_tenders
    assert _match("toilet") == {t["toilets"].pk}  # stemming
    assert _match("constr") == {t["toilets"].pk}  # prefix
    assert _match("bridges") == {t["bridge"].pk}


def test_alert_keyword_is_all_words_and_list_is_any(alert_tenders):
    t = alert_tenders
    assert _match("road repair") == {t["roads"].pk}  # both words, never "any word"
    assert _match("road repair, bridge") == {t["roads"].pk, t["bridge"].pk}
    assert _match("road -widening") == {t["roads"].pk}
    assert _match('"minor bridge"') == {t["bridge"].pk}


def test_alert_keyword_typo_and_buyer(alert_tenders):
    t = alert_tenders
    from tenders import search as tsearch

    tsearch.refresh_words()  # the hourly task in production
    assert _match("toilts") == {t["toilets"].pk}  # one letter off "toilets"
    assert _match("aiims") == {t["aiims"].pk}  # the buyer, like the search box


def test_alert_keyword_without_searchable_words_falls_back_to_substring(alert_tenders):
    assert _match("NH-30") == {alert_tenders["bridge"].pk}
    assert _match("the") >= set()  # stop words only: no crash


def test_alert_matches_what_search_finds(alert_tenders):
    for q in ("toilet", "road repair", "bridges", "constr"):
        found = {r["id"] for r in APIClient().get("/api/tenders", {"q": q}).json()["results"]}
        assert _match(q) == found, q
