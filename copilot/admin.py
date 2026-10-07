from django.contrib import admin

from copilot.models import Chunk, Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "organization",
        "tender",
        "status",
        "pages",
        "ocr_pages",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("filename", "sha256", "organization__name", "tender__source_tender_id")
    raw_id_fields = ("organization", "uploaded_by", "tender")
    readonly_fields = ("sha256", "bytes", "pages", "ocr_pages", "created_at", "processed_at")
    exclude = ("page_texts",)  # whole-document text: too big for a form


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "ord", "page_from", "page_to", "heading", "tokens")
    search_fields = ("heading", "text")
    raw_id_fields = ("document",)
    exclude = ("embedding",)
