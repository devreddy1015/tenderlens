from django.contrib import admin

from workspaces.models import ApiKey, BidTrack, Invite, Membership, Organization, ReminderLog


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "slug", "plan_code", "created_at"]
    list_filter = ["plan_code"]
    search_fields = ["name", "slug", "gstin", "memberships__user__email"]
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "organization", "role", "is_active", "joined_at"]
    list_filter = ["role"]
    raw_id_fields = ["user", "organization"]
    search_fields = ["user__email", "organization__name"]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "email",
        "organization",
        "role",
        "created_at",
        "expires_at",
        "accepted_at",
    ]
    list_filter = ["role"]
    raw_id_fields = ["organization", "invited_by", "accepted_by"]
    search_fields = ["email", "organization__name"]
    exclude = ["nonce_hash"]


@admin.register(BidTrack)
class BidTrackAdmin(admin.ModelAdmin):
    list_display = ["id", "organization", "tender", "status", "owner", "updated_at"]
    list_filter = ["status"]
    raw_id_fields = ["organization", "tender", "owner", "created_by"]
    search_fields = ["organization__name", "tender__title", "tender__source_tender_id"]


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = ["id", "bid_track", "user", "day", "sent_at"]
    raw_id_fields = ["bid_track", "user"]


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    """Keys are created in the app (the secret is shown once); admins can only revoke."""

    list_display = [
        "id",
        "prefix",
        "name",
        "organization",
        "created_by",
        "last_used_at",
        "revoked_at",
    ]
    raw_id_fields = ["organization", "created_by"]
    readonly_fields = ["prefix", "key_hash", "created_at", "last_used_at"]
    search_fields = ["prefix", "name", "organization__name"]

    def has_add_permission(self, request):
        return False
