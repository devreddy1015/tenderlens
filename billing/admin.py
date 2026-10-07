from django.contrib import admin

from billing import services
from billing.models import Subscription, Usage, WebhookEvent


@admin.register(Usage)
class UsageAdmin(admin.ModelAdmin):
    list_display = ["id", "organization", "key", "period", "count", "updated_at"]
    list_filter = ["key", "period"]
    raw_id_fields = ["organization"]
    search_fields = ["organization__name", "organization__slug"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """Saving here re-derives the organisation's plan, so an Enterprise contract is a
    "manual" subscription rather than a hand-edited plan_code."""

    list_display = [
        "id",
        "organization",
        "plan_code",
        "interval",
        "status",
        "provider",
        "current_period_end",
        "updated_at",
    ]
    list_filter = ["status", "provider", "plan_code"]
    raw_id_fields = ["organization"]
    search_fields = ["organization__name", "provider_subscription_id"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        services.sync_plan(obj.organization)


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["id", "provider", "event", "event_id", "received_at", "processed_at", "result"]
    list_filter = ["provider", "event"]
    search_fields = ["event_id"]
    readonly_fields = ["provider", "event_id", "event", "payload", "received_at", "processed_at"]
