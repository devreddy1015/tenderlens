"""Copilot over HTTP and the database: uploads, processing, organisation scoping, the SSE
answer stream with a mocked LLM, quotas, Bid Brief and eligibility endpoints."""

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pymupdf
import pytest
import respx
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from billing.entitlements import period, used
from billing.models import Usage
from copilot import ingest
from copilot.models import Chunk, Document
from copilot.prompt import ABSTAIN
from copilot.retrieval import Filters, search
from tenders.models import Tender
from workspaces.services import get_active_org

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures" / "copilot"
DDA = FIXTURES / "NIT_2026_DDA_928070_1.pdf"
ITBP = FIXTURES / "NIT_2026_ITBP_925996_1.pdf"
User = get_user_model()


@pytest.fixture(autouse=True)
def _copilot_settings(settings, tmp_path):
    settings.EMBEDDING_MODEL = "fake"
    settings.RERANKER_MODEL = ""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.LLM_BASE_URL = "http://llm.test/v1"
    settings.LLM_MODEL = "test-model"


def make_client(email: str) -> tuple[APIClient, object]:
    user = User.objects.create_user(username=email, email=email, password="x")
    client = APIClient()
    client.force_login(user)
    return client, get_active_org(user)


@pytest.fixture
def alice():
    return make_client("alice@example.com")


@pytest.fixture
def bob():
    return make_client("bob@example.com")


def pdf_bytes(*pages: str) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    return doc.tobytes()


def upload(client, data: bytes | Path = DDA, name: str | None = None, **extra):
    if isinstance(data, Path):
        name, data = name or data.name, data.read_bytes()
    f = SimpleUploadedFile(name or "NIT.pdf", data, content_type="application/pdf")
    return client.post("/api/copilot/documents", {"file": f, **extra}, format="multipart")


def make_tender(source_tender_id="2026_DDA_928070_1") -> Tender:
    now = timezone.now()
    return Tender.objects.create(
        source="central",
        source_tender_id=source_tender_id,
        title="M/o Completed scheme under North Zone",
        buyer_raw="DDA",
        published_at=now - timedelta(days=5),
        closes_at=now + timedelta(days=5),
        content_hash="h",
        fetched_at=now,
        first_seen=now,
        last_seen=now,
    )


def sse_events(resp) -> list[dict]:
    body = b"".join(resp.streaming_content).decode()
    assert body.endswith("\n\n")
    events = []
    for block in body.split("\n\n"):
        if block:
            assert block.startswith("data: ")
            events.append(json.loads(block[len("data: ") :]))
    return events


def llm_stream(text: str, pieces: int = 3) -> httpx.Response:
    size = max(1, len(text) // pieces)
    parts = [text[i : i + size] for i in range(0, len(text), size)]
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": p}, "index": 0}]}) for p in parts
    ]
    body = "\n\n".join([*lines, "data: [DONE]"]) + "\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


# --- upload and processing ---------------------------------------------------------------


def test_upload_processes_document(alice):
    client, org = alice
    tender = make_tender()
    r = upload(client, tender=tender.pk)
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "ready" and body["error"] == ""
    assert body["pages"] == 4 and body["chunks"] > 3 and body["ocr_pages"] == 0
    assert body["filename"] == DDA.name
    assert body["tender"] == {
        "id": tender.pk,
        "title": tender.title,
        "source_tender_id": "2026_DDA_928070_1",
    }
    doc = Document.objects.get(pk=body["id"])
    assert doc.file.name.startswith(f"copilot/{org.pk}/") and Path(doc.file.path).exists()
    assert len(doc.page_texts) == 4
    assert used(org, "documents_per_month") == 1
    # the generated full-text column is populated
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM copilot_chunk WHERE document_id = %s AND search_vector @@ "
            "plainto_tsquery('english', 'earnest money')",
            [doc.pk],
        )
        assert cur.fetchone()[0] >= 1


def test_same_file_twice_is_one_document_and_one_quota_unit(alice):
    client, org = alice
    first = upload(client).json()
    tender = make_tender()
    again = upload(client, name="renamed.pdf", tender=tender.pk)
    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert again.json()["tender"]["id"] == tender.pk  # attached on the second upload
    assert Document.objects.count() == 1 and used(org, "documents_per_month") == 1


def test_processing_is_idempotent(alice):
    client, _ = alice
    doc = Document.objects.get(pk=upload(client).json()["id"])
    ids = list(Chunk.objects.filter(document=doc).values_list("id", flat=True))
    ingest.process(doc)  # ready: nothing to do
    assert list(Chunk.objects.filter(document=doc).values_list("id", flat=True)) == ids
    ingest.process(doc, force=True)  # re-run replaces, never duplicates
    assert Chunk.objects.filter(document=doc).count() == len(ids)
    assert not Chunk.objects.filter(pk__in=ids).exists()


def test_unreadable_pdf_fails_and_refunds_quota(alice):
    client, org = alice
    blank = pymupdf.open()
    blank.new_page()
    data = blank.tobytes()
    r = upload(client, data, name="blank.pdf")
    assert r.status_code == 201
    assert r.json()["status"] == "failed" and "No text could be read" in r.json()["error"]
    assert used(org, "documents_per_month") == 0
    # uploading it again retries instead of returning the failed row
    again = upload(client, data, name="blank.pdf")
    assert again.status_code == 201 and again.json()["id"] != r.json()["id"]
    assert Document.objects.count() == 1


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (b"PK\x03\x04 a zip file pretending", "file"),
        (b"%PDF-1.7\n this is not really a pdf", "file"),
    ],
)
def test_upload_rejects_non_pdfs(alice, payload, field):
    client, org = alice
    r = upload(client, payload)
    assert r.status_code == 400 and field in r.json()
    assert used(org, "documents_per_month") == 0 and not Document.objects.exists()


def test_upload_validation(alice, settings):
    client, org = alice
    assert client.post("/api/copilot/documents", {}, format="multipart").status_code == 400
    r = upload(client, tender=999999)
    assert r.status_code == 400 and r.json() == {"tender": "Unknown tender."}
    settings.COPILOT_MAX_UPLOAD_MB = 0
    r = upload(client)
    assert r.status_code == 400 and "larger than 0 MB" in r.json()["file"]
    assert used(org, "documents_per_month") == 0


def test_upload_quota_is_402(alice):
    client, org = alice
    Usage.objects.create(organization=org, key="documents_per_month", period=period(), count=5)
    r = upload(client)
    assert r.status_code == 402
    assert r.json() == {
        "detail": "Your plan's limit for document uploads this month is reached.",
        "code": "quota_exceeded",
        "limit": "documents_per_month",
    }
    assert not Document.objects.exists()


def test_login_required():
    anon = APIClient()
    for method, url in [
        ("get", "/api/copilot/documents"),
        ("post", "/api/copilot/ask"),
        ("get", "/api/copilot/status"),
        ("get", "/api/copilot/brief?tender=1"),
        ("get", "/api/copilot/eligibility?tender=1"),
    ]:
        assert getattr(anon, method)(url).status_code in (401, 403), url


# --- organisation scoping -------------------------------------------------------------------


def test_documents_are_private_to_their_organisation(alice, bob):
    a, _ = alice
    b, b_org = bob
    doc_id = upload(a).json()["id"]
    assert [d["id"] for d in a.get("/api/copilot/documents").json()] == [doc_id]
    assert b.get("/api/copilot/documents").json() == []
    assert b.get(f"/api/copilot/documents/{doc_id}").status_code == 404
    assert b.get(f"/api/copilot/documents/{doc_id}/brief").status_code == 404
    assert b.get(f"/api/copilot/eligibility?document={doc_id}").status_code == 404
    assert b.delete(f"/api/copilot/documents/{doc_id}").status_code == 404
    # retrieval itself never crosses organisations, whatever the filters say
    for mode in ("fts", "dense", "hybrid"):
        assert search("earnest money deposit", Filters(b_org.pk), mode=mode) == []
        assert search("EMD", Filters(b_org.pk, document_ids=[doc_id]), mode=mode) == []
    r = b.post(
        "/api/copilot/ask?stream=false",
        {"question": "What is the EMD?", "document_ids": [doc_id]},
        format="json",
    )
    assert r.json()["status"] == "no_context" and r.json()["citations"] == []


def test_retrieval_filters_and_modes(alice, bob):
    a, a_org = alice
    b, _ = bob
    tender = make_tender()
    dda = upload(a, tender=tender.pk).json()["id"]
    itbp = upload(a, ITBP).json()["id"]
    upload(b, ITBP)  # the same file in another organisation
    for mode in ("fts", "dense", "hybrid"):
        hits = search("Earnest Money Deposit EMD", Filters(a_org.pk), mode=mode, k=10)
        assert hits and {h.document_id for h in hits} <= {dda, itbp}, mode
    only = search("Earnest Money", Filters(a_org.pk, tender_id=tender.pk), k=10)
    assert only and {h.document_id for h in only} == {dda}
    only = search("Earnest Money", Filters(a_org.pk, document_ids=[itbp]), k=10)
    assert only and {h.document_id for h in only} == {itbp}
    top = search("What is the earnest money deposit?", Filters(a_org.pk, document_ids=[dda]))
    assert "22,316" in " ".join(h.text for h in top)
    with pytest.raises(ValueError):
        search("x", Filters(0))


def test_delete_removes_file_and_chunks(alice):
    client, _ = alice
    doc = Document.objects.get(pk=upload(client).json()["id"])
    path = Path(doc.file.path)
    assert client.delete(f"/api/copilot/documents/{doc.pk}").status_code == 204
    assert not path.exists() and not Chunk.objects.exists() and not Document.objects.exists()


# --- ask: the SSE stream -----------------------------------------------------------------


@pytest.fixture
def ready_doc(alice):
    client, org = alice
    tender = make_tender()
    doc_id = upload(client, tender=tender.pk).json()["id"]
    return client, org, tender, doc_id


def ask(client, question="What is the EMD for this work?", **body):
    return client.post("/api/copilot/ask", {"question": question, **body}, format="json")


def test_ask_streams_retrieval_deltas_and_grounded_final(ready_doc):
    client, org, tender, doc_id = ready_doc
    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://llm.test/v1/chat/completions").mock(
            return_value=llm_stream("The EMD is Rs. 22,316/- [1].")
        )
        r = ask(client, tender=tender.pk)
        assert r.status_code == 200 and r["Content-Type"] == "text/event-stream"
        assert r["Cache-Control"] == "no-cache"
        events = sse_events(r)
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "test-model" and sent["stream"] is True
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["messages"][0]["role"] == "system"
    assert "[1] NIT_2026_DDA_928070_1.pdf, p. " in sent["messages"][1]["content"]

    assert [e["type"] for e in events][0] == "retrieval"
    assert events[-1]["type"] == "final" and [e["type"] for e in events].count("final") == 1
    passages = events[0]["passages"]
    assert 1 <= len(passages) <= 5 and passages[0]["n"] == 1
    assert set(passages[0]) == {"n", "document_id", "filename", "page", "text"}
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert len(deltas) >= 2 and "".join(deltas) == "The EMD is Rs. 22,316/- [1]."
    final = events[-1]
    assert final["status"] == "answered" and final["mode"] == "llm"
    assert final["answer"] == "The EMD is Rs. 22,316/- [1]."
    assert final["model"] == "test-model" and final["grounding"] == {"unsupported": []}
    assert isinstance(final["latency_ms"], int)
    (cite,) = final["citations"]
    assert set(cite) == {"n", "document_id", "filename", "page", "quote"}
    assert cite["document_id"] == doc_id and "22,316" in cite["quote"]
    assert used(org, "questions_per_month") == 1


def test_ask_strips_thinking_and_abstains(ready_doc):
    client, *_ = ready_doc
    with respx.mock() as router:
        router.post("http://llm.test/v1/chat/completions").mock(
            return_value=llm_stream(f"<think>let me look</think>{ABSTAIN}")
        )
        events = sse_events(ask(client, "What interest is paid on the security deposit?"))
    assert all("think" not in e.get("text", "") for e in events if e["type"] == "delta")
    final = events[-1]
    assert final["status"] == "abstained" and final["answer"] == ABSTAIN
    assert final["citations"] == [] and final["grounding"] is None


def test_ask_rejects_ungrounded_answer(ready_doc):
    client, *_ = ready_doc
    with respx.mock() as router:
        router.post("http://llm.test/v1/chat/completions").mock(
            return_value=llm_stream("The EMD is Rs. 25,000/- [1].")
        )
        final = sse_events(ask(client))[-1]
    assert final["status"] == "rejected" and final["answer"] == ABSTAIN
    assert final["grounding"]["unsupported"] == ["Rs. 25,000"]
    assert final["citations"] == []


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.Response(503, text="busy")],
)
def test_ask_falls_back_to_extractive_when_llm_is_down(ready_doc, failure):
    client, org, *_ = ready_doc
    with respx.mock() as router:
        route = router.post("http://llm.test/v1/chat/completions")
        if isinstance(failure, httpx.Response):
            route.mock(return_value=failure)
        else:
            route.mock(side_effect=failure)
        r = ask(client, "How much earnest money has to be deposited?")
        events = sse_events(r)
    assert r.status_code == 200
    assert events[0]["type"] == "retrieval" and events[-1]["type"] == "final"
    final = events[-1]
    assert final["mode"] == "extractive" and final["status"] == "answered"
    assert "22,316" in final["answer"] and "[" in final["answer"]
    assert final["citations"] and "22,316" in final["citations"][0]["quote"]
    assert used(org, "questions_per_month") == 1


def test_ask_json_mode_and_validation(ready_doc):
    client, *_ = ready_doc
    with respx.mock() as router:
        router.post("http://llm.test/v1/chat/completions").mock(
            return_value=llm_stream("The tender fee is Rs. 500/- [1].")
        )
        r = client.post(
            "/api/copilot/ask?stream=false", {"question": "What is the tender fee?"}, format="json"
        )
    assert r.status_code == 200 and r["Content-Type"] == "application/json"
    assert r.json()["type"] == "final" and r.json()["status"] == "answered"
    assert client.post("/api/copilot/ask", {"question": " "}, format="json").status_code == 400
    assert (
        client.post("/api/copilot/ask", {"question": "x" * 1001}, format="json").status_code == 400
    )


def test_ask_quota_and_refund_without_documents(alice):
    client, org = alice
    r = client.post(
        "/api/copilot/ask?stream=false", {"question": "What is the EMD?"}, format="json"
    )
    assert r.json()["status"] == "no_context"
    assert used(org, "questions_per_month") == 0  # nothing to answer from: refunded
    Usage.objects.filter(organization=org, key="questions_per_month").update(count=20)
    r = client.post("/api/copilot/ask", {"question": "What is the EMD?"}, format="json")
    assert r.status_code == 402
    assert r.json()["code"] == "quota_exceeded" and r.json()["limit"] == "questions_per_month"


# --- brief, eligibility, status -----------------------------------------------------------


def test_document_and_tender_brief(ready_doc):
    client, org, tender, doc_id = ready_doc
    r = client.get(f"/api/copilot/documents/{doc_id}/brief")
    assert r.status_code == 200
    fields = {f["key"]: f for f in r.json()["fields"]}
    assert fields["emd"]["value"] == "Rs. 22,316/-" and fields["emd"]["page"] == 2
    assert fields["emd"]["document_id"] == doc_id
    assert "bid_opening" in r.json()["missing"]
    corr = pdf_bytes(
        "CORRIGENDUM No. 1\nLast date and time for bid submission: 10-Oct-2026 03:00 PM.\n"
        "All other terms remain unchanged."
    )
    upload(client, corr, name="Corrigendum_1.pdf", tender=tender.pk)
    merged = client.get(f"/api/copilot/brief?tender={tender.pk}").json()
    by_key = {f["key"]: f for f in merged["fields"]}
    assert merged["documents"] == 2
    assert by_key["bid_submission_end"]["value"] == "10-Oct-2026 03:00 PM"
    assert by_key["bid_submission_end"]["filename"] == "Corrigendum_1.pdf"
    assert by_key["emd"]["document_id"] == doc_id
    assert client.get("/api/copilot/brief").status_code == 400
    empty = client.get(f"/api/copilot/brief?tender={make_tender('X_2').pk}").json()
    assert empty["fields"] == [] and empty["documents"] == 0


def test_brief_of_unprocessed_document_is_400(alice):
    client, org = alice
    doc = Document.objects.create(organization=org, filename="x.pdf", sha256="0" * 64)
    r = client.get(f"/api/copilot/documents/{doc.pk}/brief")
    assert r.status_code == 400 and r.json()["status"] == "processing"


def test_eligibility_against_company_profile(ready_doc):
    client, org, tender, doc_id = ready_doc
    r = client.get(f"/api/copilot/eligibility?tender={tender.pk}").json()
    assert r["verdict"] == "unknown"  # empty profile: never a guess
    org.annual_turnover_inr = Decimal("600000")
    org.largest_similar_work_inr = Decimal("900000")
    org.save()
    r = client.get(f"/api/copilot/eligibility?tender={tender.pk}").json()
    checks = {c["key"]: c for c in r["checks"]}
    assert r["verdict"] == "eligible"
    assert checks["min_turnover"]["required"] == "Rs. 5,57,890/- (50% of the estimated cost)"
    assert checks["min_turnover"]["source"]["document_id"] == doc_id
    assert set(checks["min_turnover"]) >= {
        "key",
        "requirement",
        "required",
        "yours",
        "status",
        "source",
    }
    org.annual_turnover_inr = Decimal("500000")
    org.save()
    r = client.get(f"/api/copilot/eligibility?document={doc_id}").json()
    assert r["verdict"] == "not_eligible"
    assert client.get("/api/copilot/eligibility").status_code == 400


def test_status(ready_doc):
    client, *_ = ready_doc
    with respx.mock() as router:
        router.get("http://llm.test/v1/models").mock(return_value=httpx.Response(200, json={}))
        up = client.get("/api/copilot/status").json()
    assert up == {
        "llm": {"available": True, "model": "test-model"},
        "embedding_model": "fake",
        "reranker_model": None,
        "documents": 1,
    }
    with respx.mock() as router:
        router.get("http://llm.test/v1/models").mock(side_effect=httpx.ConnectError("down"))
        assert client.get("/api/copilot/status").json()["llm"]["available"] is False
