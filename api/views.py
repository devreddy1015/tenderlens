import logging
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.models import Count, Prefetch, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import (
    BuyerSerializer,
    TenderDetailSerializer,
    TenderPageSerializer,
    TenderQuerySerializer,
    TenderSerializer,
)
from ingest.models import CrawlRun, DeadLetter, Quarantine
from tenders import search
from tenders.models import BuyerAlias, BuyerEntity, Tender

log = logging.getLogger(__name__)

VALUE_BUCKETS = [
    ("under_10_lakh", None, Decimal(1_000_000)),
    ("10_lakh_to_1_crore", Decimal(1_000_000), Decimal(10_000_000)),
    ("1_to_10_crore", Decimal(10_000_000), Decimal(100_000_000)),
    ("over_10_crore", Decimal(100_000_000), None),
]


def _page_link(request, page: int | None) -> str | None:
    if page is None:
        return None
    params = request.query_params.copy()
    params["page"] = page
    return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")


def _db_queryset(p: dict):
    qs = Tender.objects.select_related("buyer_entity")
    if p.get("q"):
        q = p["q"]
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(buyer_raw__icontains=q)
            | Q(ref_no__icontains=q)
            | Q(source_tender_id__iexact=q)
        )
    if p.get("state"):
        qs = qs.filter(state=p["state"])
    if p.get("category"):
        qs = qs.filter(category=p["category"])
    if p.get("source"):
        qs = qs.filter(source=p["source"])
    if p.get("buyer"):
        qs = qs.filter(buyer_entity_id=p["buyer"])
    if p.get("min_value") is not None:
        qs = qs.filter(value_inr__gte=p["min_value"])
    if p.get("max_value") is not None:
        qs = qs.filter(value_inr__lte=p["max_value"])
    if p.get("closes_before"):
        qs = qs.filter(closes_at__lte=p["closes_before"])
    if p.get("closes_after"):
        qs = qs.filter(closes_at__gte=p["closes_after"])
    return qs


def _db_facets(qs) -> dict:
    def terms(field):
        rows = qs.exclude(**{field: ""}).values(field).annotate(n=Count("id")).order_by("-n")[:40]
        return [{"key": r[field], "count": r["n"]} for r in rows]

    ranges = []
    for key, lo, hi in VALUE_BUCKETS:
        sub = qs
        if lo is not None:
            sub = sub.filter(value_inr__gte=lo)
        if hi is not None:
            sub = sub.filter(value_inr__lt=hi)
        ranges.append({"key": key, "count": sub.exclude(value_inr__isnull=True).count()})
    return {"state": terms("state"), "category": terms("category"), "value_range": ranges}


class TenderList(APIView):
    @extend_schema(
        parameters=[TenderQuerySerializer],
        responses=TenderPageSerializer,
        description=(
            "Search and filter tenders. Uses Elasticsearch (fuzzy, partial-word matching, "
            "facets) when it is reachable and falls back to Postgres otherwise; "
            "`search_backend` says which one answered."
        ),
    )
    def get(self, request):
        qs_ser = TenderQuerySerializer(data=request.query_params)
        qs_ser.is_valid(raise_exception=True)
        p = qs_ser.validated_data
        page, size = p["page"], p["page_size"]
        es_params = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in p.items()}

        backend, relaxed = "postgres", False
        if search.available():
            try:
                res = search.search(es_params, page=page, page_size=size)
                by_id = Tender.objects.select_related("buyer_entity").in_bulk(res["ids"])
                rows = [by_id[i] for i in res["ids"] if i in by_id]
                total, facets, backend = res["total"], res["facets"], "elasticsearch"
                relaxed = res["relaxed"]
            except Exception:
                log.exception("elasticsearch query failed; falling back to postgres")
        if backend == "postgres":
            base = _db_queryset(p)
            total = base.count()
            rows = list(base.order_by("closes_at", "id")[(page - 1) * size : page * size])
            facets = _db_facets(base)

        last_page = max(1, -(-total // size))
        return Response(
            {
                "count": total,
                "next": _page_link(request, page + 1 if page < last_page else None),
                "previous": _page_link(request, page - 1 if page > 1 else None),
                "search_backend": backend,
                "relaxed": relaxed,
                "facets": facets,
                "results": TenderSerializer(rows, many=True).data,
            }
        )


class TenderDetail(APIView):
    @extend_schema(
        responses={200: TenderDetailSerializer, 404: OpenApiResponse(description="Not found")}
    )
    def get(self, request, pk: int):
        tender = get_object_or_404(Tender.objects.select_related("buyer_entity"), pk=pk)
        return Response(TenderDetailSerializer(tender).data)


class BuyerDetail(APIView):
    @extend_schema(responses={200: BuyerSerializer, 404: OpenApiResponse(description="Not found")})
    def get(self, request, pk: int):
        now = timezone.now()
        buyer = get_object_or_404(
            BuyerEntity.objects.annotate(
                tender_count=Count("tenders"),
                open_tender_count=Count("tenders", filter=Q(tenders__closes_at__gte=now)),
                total_value_inr=Sum("tenders__value_inr"),
            ).prefetch_related(Prefetch("aliases", queryset=BuyerAlias.objects.order_by("alias"))),
            pk=pk,
        )
        return Response(BuyerSerializer(buyer).data)


class Stats(APIView):
    @extend_schema(
        responses=inline_serializer(
            "Stats",
            {
                "total_tenders": serializers.IntegerField(),
                "open_tenders": serializers.IntegerField(),
                "closing_this_week": serializers.IntegerField(),
                "by_state": serializers.ListField(child=serializers.DictField()),
                "closing_this_week_by_state": serializers.ListField(child=serializers.DictField()),
                "last_crawl": serializers.DictField(allow_null=True),
            },
        )
    )
    def get(self, request):
        now = timezone.now()
        week = now + timedelta(days=7)
        open_qs = Tender.objects.filter(closes_at__gte=now)
        closing = open_qs.filter(closes_at__lt=week)

        def by_state(qs):
            return [
                {"state": r["state"] or "Unknown", "count": r["n"]}
                for r in qs.values("state").annotate(n=Count("id")).order_by("-n")
            ]

        last = CrawlRun.objects.exclude(status=CrawlRun.Status.RUNNING).first()
        return Response(
            {
                "total_tenders": Tender.objects.count(),
                "open_tenders": open_qs.count(),
                "closing_this_week": closing.count(),
                "by_state": by_state(open_qs),
                "closing_this_week_by_state": by_state(closing),
                "last_crawl": _run_summary(last),
            }
        )


def _run_summary(run: CrawlRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.pk,
        "source": run.source,
        "mode": run.mode,
        "status": run.status,
        "started": run.started,
        "finished": run.finished,
        "pages": run.pages,
        "new": run.new,
        "updated": run.updated,
        "unchanged": run.unchanged,
        "skipped": run.skipped,
        "quarantined": run.quarantined,
        "failed": run.failed,
        "problems": (run.reconciliation or {}).get("problems", []),
    }


@extend_schema(
    responses={
        200: OpenApiResponse(description="Database reachable"),
        503: OpenApiResponse(description="Database unreachable"),
    }
)
@api_view(["GET"])
def health(request):
    """Liveness plus crawl monitoring: dependency status and the last 24h of crawl runs."""
    checks: dict[str, str] = {}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
        return JsonResponse({"status": "down", "checks": checks}, status=503)

    try:
        from ingest.tasks import redis_client

        redis_client().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    checks["elasticsearch"] = "ok" if search.available() else "unavailable"

    since = timezone.now() - timedelta(hours=24)
    runs = CrawlRun.objects.filter(started__gte=since)
    by_status = dict(runs.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    last_ok = CrawlRun.objects.filter(status=CrawlRun.Status.SUCCEEDED).first()
    crawl = {
        "runs_24h": by_status,
        "last_run": _run_summary(CrawlRun.objects.first()),
        "last_success_at": last_ok.finished if last_ok else None,
        "open_dead_letters": DeadLetter.objects.filter(resolved=False).count(),
        "quarantined_24h": Quarantine.objects.filter(created_at__gte=since).count(),
    }
    degraded = any(v != "ok" for v in checks.values())
    return Response({"status": "degraded" if degraded else "ok", "checks": checks, "crawl": crawl})
