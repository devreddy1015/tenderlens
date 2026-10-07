from datetime import timedelta

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


def _page_link(request, page: int | None) -> str | None:
    if page is None:
        return None
    params = request.query_params.copy()
    params["page"] = page
    return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")


class TenderList(APIView):
    @extend_schema(
        operation_id="api_tenders_list",
        parameters=[TenderQuerySerializer],
        responses=TenderPageSerializer,
        description=(
            "Search and filter tenders: Postgres full-text search with prefix matching, "
            "typo correction (`corrected`), an any-word fallback (`relaxed`) and disjunctive "
            "facets. `search_backend` is always `postgres`."
        ),
    )
    def get(self, request):
        qs_ser = TenderQuerySerializer(data=request.query_params)
        qs_ser.is_valid(raise_exception=True)
        p = qs_ser.validated_data
        page, size = p["page"], p["page_size"]
        res = search.search(p, page=page, page_size=size)
        total = res["total"]
        last_page = max(1, -(-total // size))
        return Response(
            {
                "count": total,
                "next": _page_link(request, page + 1 if page < last_page else None),
                "previous": _page_link(request, page - 1 if page > 1 else None),
                "search_backend": "postgres",
                "relaxed": res["relaxed"],
                "corrected": res["corrected"],
                "facets": res["facets"],
                "results": TenderSerializer(res["results"], many=True).data,
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

        last = (
            CrawlRun.objects.exclude(status=CrawlRun.Status.RUNNING).order_by("-finished").first()
        )
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

    since = timezone.now() - timedelta(hours=24)
    runs = CrawlRun.objects.filter(started__gte=since)
    by_status = dict(runs.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    last_ok = (
        CrawlRun.objects.filter(status=CrawlRun.Status.SUCCEEDED).order_by("-finished").first()
    )
    crawl = {
        "runs_24h": by_status,
        "last_run": _run_summary(CrawlRun.objects.first()),
        "last_success_at": last_ok.finished if last_ok else None,
        "open_dead_letters": DeadLetter.objects.filter(resolved=False).count(),
        "quarantined_24h": Quarantine.objects.filter(created_at__gte=since).count(),
    }
    degraded = any(v != "ok" for v in checks.values())
    return Response({"status": "degraded" if degraded else "ok", "checks": checks, "crawl": crawl})


class SimilarTenders(APIView):
    @extend_schema(responses=TenderSerializer(many=True))
    def get(self, request, pk: int):
        tender = get_object_or_404(Tender, pk=pk)
        rows = search.similar(tender)
        return Response(TenderSerializer(rows, many=True).data)


SectorSchema = inline_serializer(
    "SectorStat",
    {
        "slug": serializers.CharField(),
        "label": serializers.CharField(),
        "description": serializers.CharField(),
        "open": serializers.IntegerField(),
        "closing_this_week": serializers.IntegerField(),
        "value_inr": serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True),
    },
    many=True,
)


class Sectors(APIView):
    @extend_schema(responses=SectorSchema)
    def get(self, request):
        from tenders.sectors import SECTORS

        now = timezone.now()
        week = now + timedelta(days=7)
        stats = {
            r["sector"]: r
            for r in Tender.objects.filter(closes_at__gte=now)
            .values("sector")
            .annotate(
                open=Count("id"),
                closing_this_week=Count("id", filter=Q(closes_at__lt=week)),
                value_inr=Sum("value_inr"),
            )
        }
        return Response(
            [
                {
                    "slug": s.slug,
                    "label": s.label,
                    "description": s.description,
                    "open": stats.get(s.slug, {}).get("open", 0),
                    "closing_this_week": stats.get(s.slug, {}).get("closing_this_week", 0),
                    "value_inr": stats.get(s.slug, {}).get("value_inr"),
                }
                for s in SECTORS
            ]
        )


MapSchema = inline_serializer(
    "StateStat",
    {
        "state": serializers.CharField(),
        "open": serializers.IntegerField(),
        "closing_this_week": serializers.IntegerField(),
        "value_inr": serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True),
        "top_sector": serializers.CharField(allow_null=True),
    },
    many=True,
)


class MapStats(APIView):
    """Open tenders per state, for the India map. Optional ?sector= narrows it."""

    @extend_schema(
        parameters=[
            inline_serializer("MapQuery", {"sector": serializers.CharField(required=False)})
        ],
        responses=MapSchema,
    )
    def get(self, request):
        now = timezone.now()
        week = now + timedelta(days=7)
        qs = Tender.objects.filter(closes_at__gte=now).exclude(state="")
        if request.query_params.get("sector"):
            qs = qs.filter(sector=request.query_params["sector"])
        rows = (
            qs.values("state")
            .annotate(
                open=Count("id"),
                closing_this_week=Count("id", filter=Q(closes_at__lt=week)),
                value_inr=Sum("value_inr"),
            )
            .order_by("-open")
        )
        top: dict[str, str] = {}
        for r in qs.values("state", "sector").annotate(n=Count("id")).order_by("state", "-n"):
            top.setdefault(r["state"], r["sector"])
        return Response([{**r, "top_sector": top.get(r["state"])} for r in rows])


@extend_schema(
    responses=inline_serializer(
        "SiteConfig",
        {
            "google_client_id": serializers.CharField(),
            "dev_login": serializers.BooleanField(),
            "sources": serializers.ListField(child=serializers.DictField()),
        },
    )
)
@api_view(["GET"])
def site_config(request):
    """Public settings the frontend needs at runtime (no rebuild when they change)."""
    from django.conf import settings

    from ingest.sources import SOURCES

    return Response(
        {
            "google_client_id": settings.GOOGLE_CLIENT_ID,
            "dev_login": settings.DEV_LOGIN_ENABLED,
            "sources": [{"key": s.key, "name": s.name} for s in SOURCES.values()],
        }
    )
