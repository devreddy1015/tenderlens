from django.contrib import admin

from feedback.models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["created_at", "kind", "status", "email", "short_message", "page"]
    list_filter = ["kind", "status"]
    search_fields = ["message", "email", "page"]
    list_editable = ["status"]
    readonly_fields = ["created_at", "user", "user_agent"]

    @admin.display(description="message")
    def short_message(self, obj):
        return obj.message[:80]
