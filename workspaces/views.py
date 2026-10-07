"""Workspace, members, invites, API keys, bid pipeline, iCal feed, recommendations and
exports (docs/PLATFORM_V2.md sections 3 and 5).

Every query is scoped to the caller's organisation (services.request_org), and objects of
another organisation answer 404, never 403, so ids cannot be probed. Account management
(workspace settings, members, invites, keys) needs a browser session: an API key can read
data but cannot mint more keys or invite people.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import permissions, serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from alerts.models import AlertSubscription
from api.serializers import TenderQuerySerializer
from billing.entitlements import get_plan, require_feature, usage_summary
from intel import outcomes
from tenders import search
from tenders.models import Tender
from workspaces import exports, ical, invites, recommendations
from workspaces.auth import create_key
from workspaces.models import ApiKey, BidTrack, Invite, Membership, Organization
from workspaces.serializers import (
    ApiKeyCreateSerializer,
    ApiKeySerializer,
    BidTrackCreateSerializer,
    BidTrackSerializer,
    BidTrackUpdateSerializer,
    InviteCreateSerializer,
    InviteSerializer,
    MemberSerializer,
    OrganizationUpdateSerializer,
    RecommendedTenderSerializer,
)
from workspaces.services import (
    calendar_token,
    get_active_org,
    request_org,
    require_role,
    set_active_org,
)

OWNER, ADMIN = Membership.Role.OWNER, Membership.Role.ADMIN
Detail = inline_serializer("Detail", {"detail": serializers.CharField()})


def _page_link(request, page: int | None) -> str | None:
    if page is None:
        return None
    params = request.query_params.copy()
    params["page"] = page
    return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")


class SessionView(APIView):
    """Signed-in browser users only (not API keys)."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class MemberView(APIView):
    """Signed-in users or API keys, acting in their organisation."""

    permission_classes = [permissions.IsAuthenticated]


# --- workspace ----------------------------------------------------------------------------


def calendar_url(request, org: Organization) -> str:
    from django.conf import settings

    return f"{settings.SITE_URL}/api/pipeline/calendar.ics?token={calendar_token(org)}"


def workspace_data(request, org: Organization, membership: Membership) -> dict:
    alerts = AlertSubscription.objects.filter(user__memberships__organization=org).count()
    return {
        "id": org.pk,
        "name": org.name,
        "slug": org.slug,
        "role": membership.role,
        "plan": get_plan(org).as_dict(),
        "usage": {**usage_summary(org), "alerts": alerts, "seats": org.memberships.count()},
        "profile": {
            k: v
            for k, v in OrganizationUpdateSerializer(org).data.items()
            if k not in {"name", "contribute_outcomes"}
        },
        "contribute_outcomes": org.contribute_outcomes,
        "calendar_url": calendar_url(request, org),
    }


WorkspaceSchema = inline_serializer(
    "Workspace",
    {
        "id": serializers.IntegerField(),
        "name": serializers.CharField(),
        "slug": serializers.CharField(),
        "role": serializers.CharField(),
        "plan": serializers.DictField(),
        "usage": serializers.DictField(child=serializers.IntegerField()),
        "profile": serializers.DictField(),
        "contribute_outcomes": serializers.BooleanField(),
        "calendar_url": serializers.CharField(),
    },
)


class Workspace(SessionView):
    @extend_schema(responses=WorkspaceSchema)
    def get(self, request):
        org = get_active_org(request.user)
        return Response(workspace_data(request, org, require_role(request.user, org)))

    @extend_schema(request=OrganizationUpdateSerializer, responses=WorkspaceSchema)
    def patch(self, request):
        org = get_active_org(request.user)
        membership = require_role(request.user, org, OWNER, ADMIN)
        sharing = org.contribute_outcomes
        ser = OrganizationUpdateSerializer(org, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            ser.save()
            if org.contribute_outcomes != sharing:
                outcomes.set_sharing(org)
        return Response(workspace_data(request, org, membership))


class WorkspaceList(SessionView):
    """The organisations the user belongs to (for the workspace switcher)."""

    @extend_schema(
        responses=inline_serializer(
            "WorkspaceRef",
            {
                "id": serializers.IntegerField(),
                "name": serializers.CharField(),
                "slug": serializers.CharField(),
                "role": serializers.CharField(),
                "active": serializers.BooleanField(),
            },
            many=True,
        )
    )
    def get(self, request):
        active = get_active_org(request.user)
        rows = request.user.memberships.select_related("organization").order_by("joined_at")
        return Response(
            [
                {
                    "id": m.organization_id,
                    "name": m.organization.name,
                    "slug": m.organization.slug,
                    "role": m.role,
                    "active": m.organization_id == active.pk,
                }
                for m in rows
            ]
        )


class WorkspaceSwitch(SessionView):
    """Make another of the user's organisations the active one. The choice is stored on
    Membership.is_active, so it follows the user across devices and sessions."""

    @extend_schema(
        request=inline_serializer("SwitchIn", {"organization": serializers.IntegerField()}),
        responses=WorkspaceSchema,
    )
    def post(self, request):
        org_id = request.data.get("organization")
        if not isinstance(org_id, int):
            raise ValidationError({"organization": "An organisation id is required."})
        org = Organization.objects.filter(pk=org_id, memberships__user=request.user).first()
        if org is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        membership = set_active_org(request.user, org)
        return Response(workspace_data(request, org, membership))


class CalendarToken(SessionView):
    @extend_schema(
        request=None,
        responses=inline_serializer("CalendarUrl", {"calendar_url": serializers.CharField()}),
    )
    def post(self, request):
        org = get_active_org(request.user)
        require_role(request.user, org, OWNER, ADMIN)
        calendar_token(org, rotate=True)
        return Response({"calendar_url": calendar_url(request, org)})


# --- members and invites ------------------------------------------------------------------


class Members(SessionView):
    @extend_schema(responses=MemberSerializer(many=True))
    def get(self, request):
        org = get_active_org(request.user)
        require_role(request.user, org)
        rows = org.memberships.select_related("user").order_by("joined_at", "id")
        return Response(MemberSerializer(rows, many=True).data)


def _owners(org) -> int:
    return org.memberships.filter(role=OWNER).count()


class MemberDetail(SessionView):
    def _get(self, request):
        org = get_active_org(request.user)
        me = require_role(request.user, org)
        return org, me

    @extend_schema(
        request=inline_serializer(
            "MemberRole", {"role": serializers.ChoiceField(Membership.Role.choices)}
        ),
        responses=MemberSerializer,
    )
    def patch(self, request, pk: int):
        """Change a member's role (owner only)."""
        org, me = self._get(request)
        target = get_object_or_404(
            Membership.objects.select_related("user"), pk=pk, organization=org
        )
        require_role(request.user, org, OWNER)
        role = request.data.get("role")
        if role not in Membership.Role.values:
            raise ValidationError({"role": f"One of {', '.join(Membership.Role.values)}."})
        with transaction.atomic():
            Organization.objects.select_for_update().filter(pk=org.pk).first()
            if target.role == OWNER and role != OWNER and _owners(org) <= 1:
                raise ValidationError({"role": "An organisation needs at least one owner."})
            target.role = role
            target.save(update_fields=["role"])
        return Response(MemberSerializer(target).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk: int):
        """Remove a member (owner: anyone; admin: members), or leave (your own id)."""
        org, me = self._get(request)
        target = get_object_or_404(Membership, pk=pk, organization=org)
        if target.pk != me.pk and (
            me.role == Membership.Role.MEMBER or (me.role == ADMIN and target.role != "member")
        ):
            return Response(
                {"detail": "You cannot remove this member."}, status=status.HTTP_403_FORBIDDEN
            )
        with transaction.atomic():
            Organization.objects.select_for_update().filter(pk=org.pk).first()
            if target.role == OWNER and _owners(org) <= 1:
                raise ValidationError(
                    {"detail": "The last owner cannot leave. Make someone else owner first."}
                )
            BidTrack.objects.filter(organization=org, owner_id=target.user_id).update(owner=None)
            target.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class Invites(SessionView):
    @extend_schema(responses=InviteSerializer(many=True))
    def get(self, request):
        org = get_active_org(request.user)
        require_role(request.user, org, OWNER, ADMIN)
        rows = org.invites.filter(
            accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
        )
        return Response(InviteSerializer(rows, many=True).data)

    @extend_schema(request=InviteCreateSerializer, responses={201: InviteSerializer})
    def post(self, request):
        """Invite by email (owner/admin). Counts against the plan's seats: members plus
        open invites."""
        org = get_active_org(request.user)
        require_role(request.user, org, OWNER, ADMIN)
        ser = InviteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        invite, _token = invites.create_invite(
            org, request.user, ser.validated_data["email"], ser.validated_data["role"]
        )
        return Response(InviteSerializer(invite).data, status=status.HTTP_201_CREATED)


class InviteRevoke(SessionView):
    @extend_schema(responses={204: None})
    def delete(self, request, pk: int):
        org = get_active_org(request.user)
        require_role(request.user, org, OWNER, ADMIN)
        invite = get_object_or_404(Invite, pk=pk, organization=org, accepted_at__isnull=True)
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitePreview(APIView):
    """What an invite link is for, so the /invite/<token> page can say "Join <org>"."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses=inline_serializer(
            "InvitePreview",
            {
                "organization": serializers.CharField(),
                "email": serializers.EmailField(),
                "role": serializers.CharField(),
                "expires_at": serializers.DateTimeField(),
            },
        )
    )
    def get(self, request, token: str):
        invite = invites.read_token(token)
        return Response(
            {
                "organization": invite.organization.name,
                "email": invite.email,
                "role": invite.role,
                "expires_at": invite.expires_at,
            }
        )


class InviteAccept(SessionView):
    @extend_schema(request=None, responses=WorkspaceSchema)
    def post(self, request, token: str):
        membership = invites.accept(token, request.user)
        return Response(workspace_data(request, membership.organization, membership))


# --- API keys -----------------------------------------------------------------------------


class ApiKeys(SessionView):
    @extend_schema(responses=ApiKeySerializer(many=True))
    def get(self, request):
        org = get_active_org(request.user)
        require_role(request.user, org, OWNER, ADMIN)
        rows = org.api_keys.filter(revoked_at__isnull=True).select_related("created_by")
        return Response(ApiKeySerializer(rows, many=True).data)

    @extend_schema(
        request=ApiKeyCreateSerializer,
        responses={201: ApiKeySerializer},
        description="The response's `key` is the only time the secret is shown.",
    )
    def post(self, request):
        org = get_active_org(request.user)
        require_role(request.user, org, OWNER, ADMIN)
        require_feature(org, "api")
        ser = ApiKeyCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        row, key = create_key(org, request.user, ser.validated_data["name"])
        return Response({**ApiKeySerializer(row).data, "key": key}, status=status.HTTP_201_CREATED)


class ApiKeyDetail(SessionView):
    @extend_schema(responses={204: None})
    def delete(self, request, pk: int):
        org = get_active_org(request.user)
        require_role(request.user, org, OWNER, ADMIN)
        row = get_object_or_404(ApiKey, pk=pk, organization=org, revoked_at__isnull=True)
        row.revoked_at = timezone.now()
        row.save(update_fields=["revoked_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- pipeline -----------------------------------------------------------------------------


def _tracks(org):
    return BidTrack.objects.filter(organization=org).select_related("tender__buyer_entity", "owner")


class Pipeline(MemberView):
    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=BidTrack.Status.values)],
        responses=BidTrackSerializer(many=True),
    )
    def get(self, request):
        org = request_org(request)
        qs = _tracks(org)
        wanted = request.query_params.get("status")
        if wanted:
            if wanted not in BidTrack.Status.values:
                raise ValidationError({"status": f"One of {', '.join(BidTrack.Status.values)}."})
            qs = qs.filter(status=wanted)
        return Response(BidTrackSerializer(qs, many=True).data)

    @extend_schema(
        request=BidTrackCreateSerializer,
        responses={200: BidTrackSerializer, 201: BidTrackSerializer},
        description="Idempotent per organisation and tender: tracking a tracked tender "
        "returns the existing entry (200) unchanged.",
    )
    def post(self, request):
        org = request_org(request)
        ser = BidTrackCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tender = Tender.objects.filter(pk=ser.validated_data["tender"]).first()
        if tender is None:
            raise ValidationError({"tender": "No such tender."})
        track, created = BidTrack.objects.get_or_create(
            organization=org,
            tender=tender,
            defaults={
                "status": ser.validated_data.get("status", BidTrack.Status.WATCHING),
                "owner": request.user,
                "created_by": request.user,
            },
        )
        track = _tracks(org).get(pk=track.pk)
        return Response(
            BidTrackSerializer(track).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PipelineDetail(MemberView):
    @extend_schema(responses=BidTrackSerializer)
    def get(self, request, pk: int):
        return Response(
            BidTrackSerializer(get_object_or_404(_tracks(request_org(request)), pk=pk)).data
        )

    @extend_schema(request=BidTrackUpdateSerializer, responses=BidTrackSerializer)
    def patch(self, request, pk: int):
        org = request_org(request)
        track = get_object_or_404(_tracks(org), pk=pk)
        ser = BidTrackUpdateSerializer(track, data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        if "owner" in data:
            owner_id = data.pop("owner")
            if owner_id is None:
                track.owner = None
            else:
                m = Membership.objects.filter(user_id=owner_id, organization=org).first()
                if m is None:
                    raise ValidationError(
                        {"owner": "The owner must be a member of this workspace."}
                    )
                track.owner = m.user
        for field, value in data.items():
            setattr(track, field, value)
        with transaction.atomic():
            track.save()
            # Won/lost with an L1 price becomes a training row; anything else removes it.
            outcomes.record_outcome(track)
        return Response(BidTrackSerializer(_tracks(org).get(pk=track.pk)).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk: int):
        track = get_object_or_404(BidTrack, pk=pk, organization=request_org(request))
        with transaction.atomic():
            outcomes.forget_outcome(track)
            track.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


CLOSING_SOON_DAYS = 7


class PipelineSummary(MemberView):
    @extend_schema(
        responses=inline_serializer(
            "PipelineSummary",
            {
                "by_status": serializers.DictField(child=serializers.IntegerField()),
                "closing_soon": BidTrackSerializer(many=True),
                "value_inr_in_play": serializers.DecimalField(max_digits=20, decimal_places=2),
            },
        ),
        description=f"closing_soon: not yet submitted, closing within {CLOSING_SOON_DAYS} days. "
        "value_inr_in_play: watching + preparing + submitted, each at its bid amount if set, "
        "else the tender's estimated value.",
    )
    def get(self, request):
        org = request_org(request)
        tracks = BidTrack.objects.filter(organization=org)
        counts = dict(tracks.values_list("status").annotate(n=Count("id")).order_by())
        now = timezone.now()
        soon = _tracks(org).filter(
            status__in=BidTrack.OPEN_STATUSES,
            tender__closes_at__gte=now,
            tender__closes_at__lte=now + timedelta(days=CLOSING_SOON_DAYS),
        )
        value = tracks.filter(status__in=BidTrack.LIVE_STATUSES).aggregate(
            v=Sum(
                Coalesce("bid_amount_inr", "tender__value_inr"),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )
        )["v"] or Decimal(0)
        return Response(
            {
                "by_status": {s: counts.get(s, 0) for s in BidTrack.Status.values},
                "closing_soon": BidTrackSerializer(
                    soon.order_by("tender__closes_at", "id")[:20], many=True
                ).data,
                "value_inr_in_play": f"{value:.2f}",
            }
        )


class PipelineCalendar(APIView):
    """iCal feed for calendar apps; authenticated by the organisation's token in the URL."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("token", str, required=True)],
        responses={(200, "text/calendar"): str},
    )
    def get(self, request):
        token = request.query_params.get("token", "")
        org = (
            Organization.objects.filter(calendar_token=token).first()
            if 20 <= len(token) <= 64
            else None
        )
        if org is None:
            return HttpResponse("Calendar not found.", status=404, content_type="text/plain")
        resp = HttpResponse(ical.calendar(org), content_type="text/calendar; charset=utf-8")
        resp["Content-Disposition"] = 'inline; filename="tenderlens-pipeline.ics"'
        resp["Cache-Control"] = "private, max-age=300"
        return resp


# --- recommendations and exports ----------------------------------------------------------


class Recommendations(MemberView):
    @extend_schema(
        parameters=[TenderQuerySerializer],
        responses=inline_serializer(
            "RecommendationPage",
            {
                "count": serializers.IntegerField(),
                "next": serializers.CharField(allow_null=True),
                "previous": serializers.CharField(allow_null=True),
                "profile_incomplete": serializers.BooleanField(),
                "results": RecommendedTenderSerializer(many=True),
            },
        ),
        description=recommendations.__doc__,
    )
    def get(self, request):
        ser = TenderQuerySerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        p = ser.validated_data
        org = request_org(request)
        if not recommendations.profile_complete(org):
            return Response(
                {
                    "count": 0,
                    "next": None,
                    "previous": None,
                    "profile_incomplete": True,
                    "results": [],
                }
            )
        page, size = p["page"], p["page_size"]
        qs = recommendations.queryset(org, p)
        total = qs.count()
        rows = list(qs[(page - 1) * size : page * size])
        for t in rows:
            t.reasons = recommendations.reasons(org, t)
        last_page = max(1, -(-total // size))
        return Response(
            {
                "count": total,
                "next": _page_link(request, page + 1 if page < last_page else None),
                "previous": _page_link(request, page - 1 if page > 1 else None),
                "profile_incomplete": False,
                "results": RecommendedTenderSerializer(rows, many=True).data,
            }
        )


class ExportCsv(MemberView):
    @extend_schema(
        parameters=[TenderQuerySerializer],
        responses={(200, "text/csv"): str},
        description=f"The tenders /api/tenders lists for these filters, in the same order, "
        f"up to {exports.MAX_CSV_ROWS:,} rows (X-Total-Count has the full count). "
        "Needs the plan feature `export`.",
    )
    def get(self, request):
        org = request_org(request)
        require_feature(org, "export")
        ser = TenderQuerySerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        qs = search.queryset(ser.validated_data)
        total = qs.count()
        rows = qs[: exports.MAX_CSV_ROWS].iterator(chunk_size=1000)
        resp = StreamingHttpResponse(exports.csv_rows(rows), content_type="text/csv; charset=utf-8")
        day = timezone.localdate().strftime("%Y%m%d")
        resp["Content-Disposition"] = f'attachment; filename="tenderlens-tenders-{day}.csv"'
        resp["X-Total-Count"] = str(total)
        resp["X-Export-Truncated"] = "true" if total > exports.MAX_CSV_ROWS else "false"
        return resp


class OcdsReleases(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[TenderQuerySerializer],
        responses=inline_serializer("OcdsReleasePackage", {"releases": serializers.ListField()}),
        description="OCDS 1.1 release package of the tenders /api/tenders lists for these "
        "filters; 100 releases per page unless page_size is given. Pagination is in `links`.",
    )
    def get(self, request):
        ser = TenderQuerySerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        p = ser.validated_data
        page = p["page"]
        size = p["page_size"] if "page_size" in request.query_params else 100
        qs = search.queryset(p)
        total = qs.count()
        rows = list(qs[(page - 1) * size : page * size])
        last_page = max(1, -(-total // size))
        links = {}
        if page < last_page:
            links["next"] = _page_link(request, page + 1)
        if page > 1:
            links["prev"] = _page_link(request, page - 1)
        body = exports.release_package(rows, uri=request.build_absolute_uri(), links=links)
        if not links:
            body.pop("links")
        resp = Response(body)
        resp["X-Total-Count"] = str(total)
        return resp
