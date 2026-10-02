from django.core import signing
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.html import escape
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from alerts import emails, matching, tasks
from alerts.models import AlertSubscription
from alerts.serializers import AlertCriteriaSerializer, AlertSerializer
from api.serializers import TenderSerializer

PreviewSchema = inline_serializer(
    "AlertPreview", {"count": serializers.IntegerField(), "sample": TenderSerializer(many=True)}
)


class AlertList(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=AlertSerializer(many=True))
    def get(self, request):
        return Response(AlertSerializer(request.user.alerts.all(), many=True).data)

    @extend_schema(request=AlertSerializer, responses={201: AlertSerializer})
    def post(self, request):
        ser = AlertSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        alert = ser.save(user=request.user)
        # The first digest lists what is open right now, so the alert feels live at once.
        tasks.send_first_digest.delay(alert.pk)
        return Response(AlertSerializer(alert).data, status=status.HTTP_201_CREATED)


class AlertDetail(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get(self, request, pk):
        return get_object_or_404(AlertSubscription, pk=pk, user=request.user)

    @extend_schema(responses=AlertSerializer)
    def get(self, request, pk: int):
        return Response(AlertSerializer(self._get(request, pk)).data)

    @extend_schema(request=AlertSerializer, responses=AlertSerializer)
    def patch(self, request, pk: int):
        alert = self._get(request, pk)
        ser = AlertSerializer(alert, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk: int):
        self._get(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AlertTest(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "alert_test"

    @extend_schema(
        request=None,
        responses=inline_serializer(
            "AlertTestResult",
            {"sent_to": serializers.EmailField(), "matching": serializers.IntegerField()},
        ),
    )
    def post(self, request, pk: int):
        alert = get_object_or_404(
            AlertSubscription.objects.select_related("user"), pk=pk, user=request.user
        )
        total = tasks.send_test(alert)
        return Response({"sent_to": request.user.email, "matching": total})


@extend_schema(request=AlertCriteriaSerializer, responses=PreviewSchema)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def alert_preview(request):
    """How many open tenders match these criteria right now (used while editing an alert)."""
    ser = AlertCriteriaSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    qs = matching.matching_tenders(**ser.validated_data)
    return Response({"count": qs.count(), "sample": TenderSerializer(qs[:3], many=True).data})


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;background:#f1f4f9;color:#0f172a;display:grid;place-items:center;min-height:100vh;margin:0}}
main{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:32px;max-width:440px;margin:16px}}
a{{color:#4338ca}}</style></head><body><main><h1 style="font-size:20px;margin:0 0 8px">{title}</h1>
<p style="color:#475569;line-height:1.5">{body}</p><p><a href="/alerts">Manage your alerts</a></p></main></body></html>"""


@extend_schema(exclude=True)
@api_view(["GET", "POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([])
def unsubscribe(request):
    """One-click unsubscribe from the link in an email. No sign-in needed: the link is signed."""
    token = request.query_params.get("token", "")
    try:
        pk = emails.read_unsubscribe_token(token)
    except signing.BadSignature:
        return HttpResponse(
            PAGE.format(
                title="Link not valid", body="This unsubscribe link is broken or was changed."
            ),
            status=400,
        )
    alert = AlertSubscription.objects.filter(pk=pk).first()
    if alert is None:
        return HttpResponse(
            PAGE.format(title="Already removed", body="This alert no longer exists.")
        )
    alert.active = False
    alert.save(update_fields=["active"])
    return HttpResponse(
        PAGE.format(
            title="Unsubscribed",
            body=f"You will not get emails for “{escape(alert.name)}” any more. You can turn it back on any time.",
        )
    )
