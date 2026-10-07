"""Copilot API (/api/copilot/, docs/PLATFORM_V2.md section 3). Everything is scoped to the
caller's organisation: a document id from another organisation is a 404, never a 403, so ids
cannot be probed."""

import json
import logging
import os

import pymupdf
from django.conf import settings
from django.db.models import Count
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import get_valid_filename
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.entitlements import consume, refund
from copilot import answer, brief, eligibility, ingest, llm
from copilot.models import Document
from copilot.retrieval import Filters
from copilot.tasks import process_document
from tenders.models import Tender
from workspaces.services import request_org

log = logging.getLogger(__name__)


class DocumentSerializer(serializers.ModelSerializer):
    chunks = serializers.IntegerField(source="n_chunks", read_only=True, default=0)
    tender = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "filename",
            "pages",
            "chunks",
            "status",
            "error",
            "ocr_pages",
            "tender",
            "created_at",
        ]

    def get_tender(self, doc) -> dict | None:
        t = doc.tender
        if t is None:
            return None
        return {"id": t.pk, "title": t.title, "source_tender_id": t.source_tender_id}


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000, trim_whitespace=True)
    tender = serializers.IntegerField(required=False, allow_null=True)
    document_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True, max_length=50
    )


class CopilotView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def org(self, request):
        return request_org(request)

    def documents(self, request):
        return (
            Document.objects.filter(organization=self.org(request))
            .select_related("tender")
            .annotate(n_chunks=Count("chunks"))
        )


def _int_param(request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValidationError({name: "Must be an integer."}) from None


def _validate_pdf(upload) -> None:
    """PDF magic bytes, size and a readable, unencrypted file, before any quota is used."""
    max_bytes = ingest.max_upload_bytes()
    if upload.size > max_bytes:
        raise ValidationError(
            {"file": f"The file is larger than {settings.COPILOT_MAX_UPLOAD_MB} MB."}
        )
    head = upload.read(1024)
    upload.seek(0)
    if b"%PDF-" not in head:
        raise ValidationError({"file": "Only PDF files can be uploaded."})
    try:
        if hasattr(upload, "temporary_file_path"):
            pdf = pymupdf.open(upload.temporary_file_path(), filetype="pdf")
        else:
            pdf = pymupdf.open(stream=upload.read(), filetype="pdf")
            upload.seek(0)
    except Exception:
        raise ValidationError({"file": "The PDF could not be read; it may be damaged."}) from None
    with pdf:
        if pdf.needs_pass:
            raise ValidationError({"file": "Password-protected PDFs cannot be read."})
        if pdf.page_count == 0:
            raise ValidationError({"file": "The PDF has no pages."})
        if pdf.page_count > ingest.MAX_PAGES:
            raise ValidationError({"file": f"The PDF has more than {ingest.MAX_PAGES} pages."})


class DocumentList(CopilotView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        parameters=[OpenApiParameter("tender", int)],
        responses=DocumentSerializer(many=True),
    )
    def get(self, request):
        qs = self.documents(request)
        tender = _int_param(request, "tender")
        if tender is not None:
            qs = qs.filter(tender_id=tender)
        return Response(DocumentSerializer(qs, many=True).data)

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "tender": {"type": "integer"},
                },
                "required": ["file"],
            }
        },
        responses={201: DocumentSerializer, 200: DocumentSerializer},
    )
    def post(self, request):
        """Upload a tender PDF. The same file uploaded again returns the existing document
        (200) without using quota."""
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Attach a PDF as 'file'."})
        tender = None
        if tender_id := request.data.get("tender"):
            try:
                tender = Tender.objects.get(pk=int(tender_id))
            except (ValueError, Tender.DoesNotExist):
                raise ValidationError({"tender": "Unknown tender."}) from None
        _validate_pdf(upload)
        org = self.org(request)
        digest = ingest.sha256_of(upload)

        existing = Document.objects.filter(organization=org, sha256=digest).first()
        if existing and existing.status == Document.Status.FAILED:
            existing.file.delete(save=False)
            existing.delete()  # a failed attempt: start over (its quota was refunded)
        elif existing:
            if tender and existing.tender_id is None:
                existing.tender = tender
                existing.save(update_fields=["tender"])
            doc = self.documents(request).get(pk=existing.pk)
            return Response(DocumentSerializer(doc).data, status=status.HTTP_200_OK)

        consume(org, "documents_per_month")
        name = os.path.basename(upload.name or "document.pdf").strip()[:200] or "document.pdf"
        try:
            doc = Document(
                organization=org,
                uploaded_by=request.user,
                tender=tender,
                filename=name,
                sha256=digest,
                bytes=upload.size,
            )
            doc.file.save(get_valid_filename(name)[:150] or "document.pdf", upload, save=False)
            doc.save()
        except Exception:
            refund(org, "documents_per_month")
            raise
        try:
            process_document.delay(doc.pk)
        except Exception as exc:  # broker down: say so instead of "processing" forever
            log.exception("copilot: could not queue document %s", doc.pk)
            doc.status, doc.error = Document.Status.FAILED, f"Processing queue unavailable: {exc}"
            doc.save(update_fields=["status", "error"])
            refund(org, "documents_per_month")
        doc = self.documents(request).get(pk=doc.pk)
        return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class DocumentDetail(CopilotView):
    @extend_schema(responses=DocumentSerializer)
    def get(self, request, pk: int):
        return Response(DocumentSerializer(get_object_or_404(self.documents(request), pk=pk)).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk: int):
        doc = get_object_or_404(Document, pk=pk, organization=self.org(request))
        doc.file.delete(save=False)
        doc.delete()  # chunks cascade
        return Response(status=status.HTTP_204_NO_CONTENT)


def _ready(doc: Document) -> None:
    if doc.status != Document.Status.READY:
        detail = (
            "The document is still being processed."
            if doc.status == Document.Status.PROCESSING
            else f"The document could not be processed: {doc.error}"
        )
        raise ValidationError({"detail": detail, "status": doc.status})


class DocumentBrief(CopilotView):
    @extend_schema(responses=dict)
    def get(self, request, pk: int):
        doc = get_object_or_404(Document, pk=pk, organization=self.org(request))
        _ready(doc)
        return Response(brief.brief([doc]))


def _tender_docs(view: CopilotView, request) -> list[Document]:
    tender = _int_param(request, "tender")
    if tender is None:
        raise ValidationError({"tender": "Required."})
    return list(
        Document.objects.filter(
            organization=view.org(request), tender_id=tender, status=Document.Status.READY
        )
    )


class TenderBrief(CopilotView):
    @extend_schema(parameters=[OpenApiParameter("tender", int, required=True)], responses=dict)
    def get(self, request):
        """The brief across every ready document of a tender; `documents` counts them (0:
        nothing uploaded yet, so every key is missing)."""
        docs = _tender_docs(self, request)
        return Response({**brief.brief(docs), "documents": len(docs)})


class Eligibility(CopilotView):
    @extend_schema(
        parameters=[OpenApiParameter("tender", int), OpenApiParameter("document", int)],
        responses=dict,
    )
    def get(self, request):
        org = self.org(request)
        doc_id = _int_param(request, "document")
        if doc_id is not None:
            doc = get_object_or_404(Document, pk=doc_id, organization=org)
            _ready(doc)
            docs = [doc]
        else:
            docs = _tender_docs(self, request)
        fields = brief.merged_fields(docs)
        return Response(eligibility.evaluate(fields, docs, org))


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


class Ask(CopilotView):
    parser_classes = [JSONParser, FormParser]

    @extend_schema(
        request=AskSerializer,
        parameters=[OpenApiParameter("stream", bool, description="false: one JSON object")],
        responses=dict,
    )
    def post(self, request):
        """Server-Sent Events: retrieval, delta..., final. Counts one question; a question
        that could not be answered for lack of documents or an internal error is refunded."""
        s = AskSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        org = self.org(request)
        filters = Filters(
            organization_id=org.pk,
            tender_id=s.validated_data.get("tender"),
            document_ids=s.validated_data.get("document_ids") or None,
        )
        question = s.validated_data["question"]
        consume(org, "questions_per_month")

        def settle(final: dict) -> None:
            if final["status"] in ("no_context", "error"):
                refund(org, "questions_per_month")

        if request.query_params.get("stream", "").lower() in ("false", "0", "no"):
            final = answer.ask(question, filters)
            settle(final)
            return Response(final)

        def events():
            for ev in answer.ask_events(question, filters):
                if ev["type"] == "final":
                    settle(ev)
                yield _sse(ev)

        resp = StreamingHttpResponse(events(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"  # Caddy/nginx: do not buffer the stream
        return resp


class Status(CopilotView):
    @extend_schema(responses=dict)
    def get(self, request):
        return Response(
            {
                "llm": llm.status(),
                "embedding_model": settings.EMBEDDING_MODEL,
                "reranker_model": settings.RERANKER_MODEL or None,
                "documents": Document.objects.filter(organization=self.org(request)).count(),
            }
        )
