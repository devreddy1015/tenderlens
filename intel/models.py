"""Historical award data and the models trained on it.

A HistoricalAward is one awarded contract (or lot) from any source: an open dataset, a
multilateral bank, or a TenderLens user recording the result of a bid. Everything the
price model needs is normalised here once, at import time, so training and the advisor
read one table instead of knowing every source's quirks.
"""

from django.db import models

# A ratio outside this band is almost always a unit or data-entry error (estimate in lakh,
# award in rupees; a lot value against the whole tender's estimate), not a real bid.
RATIO_MIN = 0.2
RATIO_MAX = 3.0


class DatasetImport(models.Model):
    """One run of `manage.py intel_import <source>`: what was read, from where, under which
    licence, and what it changed. The audit trail behind every training row."""

    class Status(models.TextChoices):
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    source = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    params = models.JSONField(default=dict, blank=True)
    files = models.JSONField(default=list, blank=True)  # [{url, sha256, bytes}]
    rows_seen = models.PositiveIntegerField(default=0)
    rows_inserted = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    license = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "intel_dataset_import"
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"{self.source} {self.started_at:%Y-%m-%d %H:%M} {self.status}"


class HistoricalAward(models.Model):
    """One awarded contract. Amounts keep their original currency; the *_inr_real columns
    are the same amounts in today's rupees (CPI-deflated, converted at that year's rate)."""

    class Category(models.TextChoices):
        WORKS = "works"
        GOODS = "goods"
        SERVICES = "services"
        CONSULTANCY = "consultancy"

    class Method(models.TextChoices):
        OPEN = "open"
        LIMITED = "limited"
        SINGLE = "single"
        QCBS = "qcbs"
        REVERSE_AUCTION = "reverse_auction"
        OTHER = "other"

    source = models.CharField(max_length=32)
    source_id = models.CharField(max_length=255)
    country = models.CharField(max_length=2, default="IN")  # ISO 3166-1 alpha-2
    state = models.CharField(max_length=64, blank=True, default="")
    district = models.CharField(max_length=128, blank=True, default="")
    buyer = models.TextField(blank=True, default="")
    buyer_key = models.TextField(blank=True, default="", db_index=True)
    title = models.TextField(blank=True, default="")
    category = models.CharField(max_length=16, choices=Category.choices, blank=True, default="")
    sector = models.CharField(max_length=32, blank=True, default="")  # tenders.sectors slug
    method = models.CharField(max_length=16, choices=Method.choices, blank=True, default="")
    currency = models.CharField(max_length=3, default="INR")
    estimated_value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    award_value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    estimated_inr_real = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    award_inr_real = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    ratio = models.FloatField(null=True, blank=True)  # award / estimate, within RATIO_MIN..MAX
    num_bidders = models.PositiveSmallIntegerField(null=True, blank=True)
    bids = models.JSONField(null=True, blank=True)  # every bid amount, when the source has them
    winner = models.TextField(blank=True, default="")
    winner_key = models.TextField(blank=True, default="", db_index=True)
    tender_date = models.DateField(null=True, blank=True)
    award_date = models.DateField(null=True, blank=True)
    year = models.SmallIntegerField(null=True, blank=True, db_index=True)
    url = models.TextField(blank=True, default="")
    tender = models.ForeignKey(
        "tenders.Tender", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # A user-recorded outcome (source "tenderlens"). shared=False rows only ever feed that
    # organisation's own comparables, never the pooled model.
    organization = models.ForeignKey(
        "workspaces.Organization",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
    shared = models.BooleanField(default=True)
    imported = models.ForeignKey(
        DatasetImport, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "intel_historical_award"
        constraints = [
            models.UniqueConstraint(fields=["source", "source_id"], name="award_source_id"),
            models.CheckConstraint(
                condition=models.Q(ratio__isnull=True)
                | models.Q(ratio__gte=RATIO_MIN, ratio__lte=RATIO_MAX),
                name="award_ratio_band",
            ),
        ]
        indexes = [
            models.Index(fields=["country", "sector", "year"], name="award_country_sector_year"),
            models.Index(fields=["state", "sector", "year"], name="award_state_sector_year"),
            models.Index(
                fields=["sector", "year"],
                name="award_with_ratio",
                condition=models.Q(ratio__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.source_id}"


class PriceIndex(models.Model):
    """Annual series used to put every amount in today's rupees: consumer prices
    ("cpi", any base year; only ratios are used) and the exchange rate in local currency
    units per US dollar ("fx_per_usd")."""

    class Series(models.TextChoices):
        CPI = "cpi"
        FX_PER_USD = "fx_per_usd"

    series = models.CharField(max_length=16, choices=Series.choices)
    country = models.CharField(max_length=2)
    year = models.SmallIntegerField()
    value = models.FloatField()
    source = models.CharField(max_length=64, default="worldbank-wdi")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "intel_price_index"
        constraints = [
            models.UniqueConstraint(fields=["series", "country", "year"], name="price_index_key")
        ]

    def __str__(self) -> str:
        return f"{self.series} {self.country} {self.year} = {self.value}"


class ModelVersion(models.Model):
    """A trained bid price model on disk (data/intel/models/<version>/). Exactly one is
    active; rolling back is activating an older row."""

    version = models.CharField(max_length=32, unique=True)
    trained_at = models.DateTimeField()
    path = models.TextField()
    is_active = models.BooleanField(default=False)
    rows_train = models.PositiveIntegerField(default=0)
    rows_calibration = models.PositiveIntegerField(default=0)
    rows_holdout = models.PositiveIntegerField(default=0)
    metrics = models.JSONField(default=dict, blank=True)
    features = models.JSONField(default=list, blank=True)
    data_sources = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "intel_model_version"
        ordering = ["-trained_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="one_active_model",
            )
        ]

    def __str__(self) -> str:
        return f"{self.version}{' (active)' if self.is_active else ''}"
