from django.contrib import admin

from ingest.models import CrawlRun, DeadLetter, Quarantine


@admin.register(CrawlRun)
class CrawlRunAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "source",
        "mode",
        "status",
        "started",
        "finished",
        "pages",
        "new",
        "updated",
        "skipped",
        "quarantined",
        "failed",
    ]
    list_filter = ["source", "mode", "status"]


@admin.register(Quarantine)
class QuarantineAdmin(admin.ModelAdmin):
    list_display = ["id", "source", "created_at", "errors"]


@admin.register(DeadLetter)
class DeadLetterAdmin(admin.ModelAdmin):
    list_display = ["id", "url", "error", "attempts", "last_tried", "resolved"]
    list_filter = ["resolved"]
