from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.db import transaction
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import google
from accounts.models import GoogleIdentity

User = get_user_model()

UserSchema = inline_serializer(
    "Me",
    {
        "authenticated": serializers.BooleanField(),
        "user": inline_serializer(
            "MeUser",
            {
                "email": serializers.EmailField(),
                "name": serializers.CharField(),
                "picture": serializers.CharField(),
            },
            allow_null=True,
        ),
    },
)


class DevLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(required=False, allow_blank=True, max_length=150)


def me_payload(request) -> dict:
    u = request.user
    if not u.is_authenticated:
        return {"authenticated": False, "user": None}
    picture = getattr(getattr(u, "google", None), "picture", "")
    return {
        "authenticated": True,
        "user": {"email": u.email, "name": u.get_full_name() or u.email, "picture": picture},
    }


def _sign_in(request, *, email: str, name: str, sub: str | None, picture: str = "") -> None:
    with transaction.atomic():
        identity = (
            GoogleIdentity.objects.select_related("user").filter(sub=sub).first() if sub else None
        )
        if identity:
            user = identity.user
            if user.email != email:  # Google account email changed
                user.email = email
                user.save(update_fields=["email"])
        else:
            user, _ = User.objects.get_or_create(username=email, defaults={"email": email})
            if sub:
                GoogleIdentity.objects.update_or_create(
                    user=user, defaults={"sub": sub, "picture": picture}
                )
        first, _, last = name.partition(" ")
        if name and (user.first_name, user.last_name) != (first, last):
            user.first_name, user.last_name = first[:150], last[:150]
            user.save(update_fields=["first_name", "last_name"])
        if sub and identity and picture != identity.picture:
            identity.picture = picture
            identity.save(update_fields=["picture"])
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")


@method_decorator(ensure_csrf_cookie, name="dispatch")
class Me(APIView):
    """Who is signed in. Also sets the CSRF cookie the frontend sends back on POSTs."""

    @extend_schema(responses=UserSchema)
    def get(self, request):
        return Response(me_payload(request))


@method_decorator(csrf_protect, name="dispatch")
class GoogleLogin(APIView):
    throttle_scope = "auth"
    authentication_classes = []  # CSRF is enforced by csrf_protect, even before sign-in

    @extend_schema(
        request=inline_serializer("GoogleCredential", {"credential": serializers.CharField()}),
        responses=UserSchema,
    )
    def post(self, request):
        credential = request.data.get("credential", "")
        try:
            g = google.verify(credential)
        except google.InvalidGoogleToken as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _sign_in(request, email=g.email, name=g.name, sub=g.sub, picture=g.picture)
        return Response(me_payload(request))


@method_decorator(csrf_protect, name="dispatch")
class DevLogin(APIView):
    """Local development only (DEBUG and DEV_LOGIN_ENABLED): sign in with any email."""

    throttle_scope = "auth"
    authentication_classes = []

    @extend_schema(exclude=True)
    def post(self, request):
        if not settings.DEV_LOGIN_ENABLED:
            raise Http404
        ser = DevLoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        _sign_in(
            request,
            email=ser.validated_data["email"].lower(),
            name=ser.validated_data.get("name", ""),
            sub=None,
        )
        return Response(me_payload(request))


class Logout(APIView):
    @extend_schema(request=None, responses=UserSchema)
    def post(self, request):
        logout(request)
        return Response(me_payload(request))
