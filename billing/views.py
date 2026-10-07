"""Billing endpoints (docs/PLATFORM_V2.md section 3, /api/billing/)."""

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import permissions, serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from billing import services
from billing.entitlements import get_plan
from billing.plans import PLANS
from workspaces.models import Membership
from workspaces.services import get_active_org, require_role


def _plan_fields() -> dict:
    return {
        "code": serializers.CharField(),
        "name": serializers.CharField(),
        "price_inr_month": serializers.IntegerField(allow_null=True),
        "price_inr_year": serializers.IntegerField(allow_null=True),
        "limits": serializers.DictField(),
        "features": serializers.ListField(child=serializers.CharField()),
    }


PlanSchema = inline_serializer("Plan", _plan_fields())
SubscriptionSchema = inline_serializer(
    "Subscription",
    {
        "plan": PlanSchema,
        "status": serializers.ChoiceField(
            ["none", "created", "active", "pending", "halted", "cancelled", "completed"]
        ),
        "interval": serializers.CharField(allow_null=True),
        "current_period_end": serializers.DateTimeField(allow_null=True),
        "provider": serializers.CharField(allow_null=True),
        "cancel_at_period_end": serializers.BooleanField(),
    },
)


def subscription_data(org) -> dict:
    sub = services.current_subscription(org)
    return {
        "plan": get_plan(org).as_dict(),
        "status": sub.status if sub else "none",
        "interval": sub.interval if sub else None,
        "current_period_end": sub.current_period_end if sub else None,
        "provider": sub.provider if sub else None,
        "cancel_at_period_end": sub.cancel_at_period_end if sub else False,
    }


class Plans(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=inline_serializer("PlanList", _plan_fields(), many=True))
    def get(self, request):
        return Response([p.as_dict() for p in PLANS.values()])


class BillingView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class CurrentSubscription(BillingView):
    @extend_schema(responses=SubscriptionSchema)
    def get(self, request):
        return Response(subscription_data(get_active_org(request.user)))


class Checkout(BillingView):
    @extend_schema(
        request=inline_serializer(
            "CheckoutIn",
            {
                "plan": serializers.CharField(),
                "interval": serializers.ChoiceField(["month", "year"]),
            },
        ),
        responses=inline_serializer(
            "CheckoutOut",
            {
                "provider": serializers.CharField(),
                "activated": serializers.BooleanField(required=False),
                "key_id": serializers.CharField(required=False),
                "subscription_id": serializers.CharField(required=False),
                "short_url": serializers.CharField(required=False, allow_null=True),
            },
        ),
        description="Owner or admin. Razorpay: open Razorpay Checkout with `key_id` and "
        "`subscription_id`; the plan switches when Razorpay's webhook confirms payment. "
        "Fake provider (development): the plan is active at once.",
    )
    def post(self, request):
        org = get_active_org(request.user)
        require_role(request.user, org, Membership.Role.OWNER, Membership.Role.ADMIN)
        plan = str(request.data.get("plan", ""))
        interval = str(request.data.get("interval", "month"))
        return Response(services.checkout(org, request.user, plan, interval))


class Cancel(BillingView):
    @extend_schema(request=None, responses=SubscriptionSchema)
    def post(self, request):
        org = get_active_org(request.user)
        require_role(request.user, org, Membership.Role.OWNER, Membership.Role.ADMIN)
        services.cancel(org)
        org.refresh_from_db()
        return Response(subscription_data(org))


@csrf_exempt  # called by Razorpay's servers; authenticated by the HMAC signature instead
@require_POST
def webhook(request):
    """Razorpay webhook: HMAC-SHA256 of the raw body with RAZORPAY_WEBHOOK_SECRET in
    X-Razorpay-Signature; idempotent per X-Razorpay-Event-Id."""
    body = request.body
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not services.verify_signature(body, signature, settings.RAZORPAY_WEBHOOK_SECRET):
        return JsonResponse({"detail": "Invalid signature."}, status=400)
    try:
        result = services.handle_webhook(body, request.headers.get("X-Razorpay-Event-Id", ""))
    except serializers.ValidationError as exc:
        return JsonResponse({"detail": str(exc.detail)}, status=400)
    return JsonResponse({"status": result})
