import logging

from django.conf import settings
from django.core.mail import send_mail
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from feedback.models import Feedback

log = logging.getLogger(__name__)


class FeedbackSerializer(serializers.ModelSerializer):
    # Honeypot: hidden in the form. People leave it empty; naive bots fill it in.
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Feedback
        fields = ["id", "kind", "message", "email", "page", "website", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        if attrs.get("kind") == Feedback.Kind.PRIVATE_WAITLIST:
            if not attrs.get("email"):
                raise serializers.ValidationError(
                    {"email": "an email is needed to join the waitlist"}
                )
        elif len(attrs.get("message", "").strip()) < 5:
            raise serializers.ValidationError({"message": "please write a few words"})
        return attrs


class FeedbackCreate(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "feedback"

    @extend_schema(
        request=FeedbackSerializer,
        responses={201: inline_serializer("FeedbackOk", {"id": serializers.IntegerField()})},
    )
    def post(self, request):
        ser = FeedbackSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data.pop("website", ""):
            # Pretend success so the bot learns nothing.
            return Response({"id": 0}, status=status.HTTP_201_CREATED)
        user = request.user if request.user.is_authenticated else None
        fb = ser.save(
            user=user,
            email=ser.validated_data.get("email") or (user.email if user else ""),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        )
        if settings.FEEDBACK_NOTIFY_EMAIL and fb.kind != Feedback.Kind.PRIVATE_WAITLIST:
            try:
                send_mail(
                    subject=f"[TenderLens feedback] {fb.get_kind_display()}",
                    message=f"{fb.message}\n\nFrom: {fb.email or 'anonymous'}\nPage: {fb.page}\nUA: {fb.user_agent}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.FEEDBACK_NOTIFY_EMAIL],
                    fail_silently=False,
                )
            except OSError:
                log.exception("feedback %s saved but the notification email failed", fb.pk)
        return Response({"id": fb.pk}, status=status.HTTP_201_CREATED)
