from django.contrib import admin

from intel.models import DatasetImport, HistoricalAward, ModelVersion, PriceIndex


@admin.register(DatasetImport)
class DatasetImportAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "source",
        "status",
        "started_at",
        "finished_at",
        "rows_seen",
        "rows_inserted",
        "rows_updated",
        "rows_skipped",
    ]
    list_filter = ["source", "status"]


@admin.register(HistoricalAward)
class HistoricalAwardAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "source",
        "country",
        "state",
        "sector",
        "year",
        "estimated_value",
        "award_value",
        "ratio",
        "num_bidders",
        "winner",
    ]
    list_filter = ["source", "country", "sector", "category", "shared"]
    search_fields = ["source_id", "title", "buyer", "winner"]
    raw_id_fields = ["tender", "organization", "imported"]


@admin.register(PriceIndex)
class PriceIndexAdmin(admin.ModelAdmin):
    list_display = ["series", "country", "year", "value", "source", "updated_at"]
    list_filter = ["series", "country"]


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ["version", "trained_at", "is_active", "rows_train", "rows_holdout"]
    readonly_fields = ["metrics", "features", "data_sources"]
