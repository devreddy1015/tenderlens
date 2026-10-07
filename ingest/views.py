"""GET /api/sources: every portal we crawl, with its freshness (the /coverage page)."""

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ingest.models import CrawlRun
from ingest.sources import SOURCES, resolve_keys
from tenders.models import Tender

_LastRun = inline_serializer(
    "SourceLastRun",
    {
        "status": serializers.CharField(),
        "finished": serializers.DateTimeField(allow_null=True),
        "new": serializers.IntegerField(),
        "updated": serializers.IntegerField(),
    },
    allow_null=True,
)


@extend_schema(
    responses=inline_serializer(
        "Source",
        {
            "key": serializers.CharField(),
            "name": serializers.CharField(),
            "kind": serializers.ChoiceField(["gepnic", "gem", "cppp"]),
            "state": serializers.CharField(allow_null=True),
            "url": serializers.URLField(),
            "open_tenders": serializers.IntegerField(),
            "last_run": _LastRun,
            "last_success": serializers.DateTimeField(allow_null=True),
            "enabled": serializers.BooleanField(),
        },
        many=True,
    )
)
@api_view(["GET"])
def source_list(request):
    """Registry order. `last_run` is the newest run whatever its outcome (a running crawl has
    `finished: null`); `last_success` is when the newest successful crawl finished, so the
    coverage page can show freshness honestly. `enabled` = in this deployment's schedule."""
    keys = list(SOURCES)
    scheduled = set(resolve_keys(settings.CRAWLER["SOURCES"]))
    open_counts = dict(
        Tender.objects.filter(closes_at__gte=timezone.now(), source__in=keys)
        .values_list("source")
        .annotate(n=Count("id"))
        .values_list("source", "n")
    )
    latest = {
        r.source: r
        for r in CrawlRun.objects.filter(source__in=keys)
        .order_by("source", "-started")
        .distinct("source")
        .only("source", "status", "finished", "new", "updated")
    }
    succeeded = dict(
        CrawlRun.objects.filter(source__in=keys, status=CrawlRun.Status.SUCCEEDED)
        .order_by("source", "-finished")
        .distinct("source")
        .values_list("source", "finished")
    )
    out = []
    for s in SOURCES.values():
        run = latest.get(s.key)
        out.append(
            {
                "key": s.key,
                "name": s.name,
                "kind": s.kind,
                "state": s.state,
                "url": s.url,
                "open_tenders": open_counts.get(s.key, 0),
                "last_run": (
                    {
                        "status": run.status,
                        "finished": run.finished,
                        "new": run.new,
                        "updated": run.updated,
                    }
                    if run
                    else None
                ),
                "last_success": succeeded.get(s.key),
                "enabled": s.enabled and s.key in scheduled,
            }
        )
    return Response(out)
