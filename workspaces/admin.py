from django.contrib import admin

from workspaces.models import Membership, Organization


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
