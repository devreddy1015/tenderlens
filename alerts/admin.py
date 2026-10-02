from django.contrib import admin

from alerts.models import AlertSubscription


@admin.register(AlertSubscription)
class AlertAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "active", "states", "pin_prefixes", "sectors", "last_sent_at"]
    list_filter = ["active"]
    search_fields = ["name", "user__email"]
