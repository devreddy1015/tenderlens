from django.db import models


class BuyerEntity(models.Model):
    """One real-world buying organisation. Many raw spellings point here via BuyerAlias."""

    canonical_name = models.TextField()
    norm_key = models.TextField(db_index=True)
    state = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "buyer_entity"

    def __str__(self):
        return self.canonical_name


class BuyerAlias(models.Model):
    class Method(models.TextChoices):
        EXACT = "exact"  # same normalised key
        FUZZY = "fuzzy"  # token_set_ratio >= auto-merge threshold
        MANUAL = "manual"  # approved from the review list
        SEED = "seed"  # first spelling seen; created the entity

    alias = models.TextField(primary_key=True)
    entity = models.ForeignKey(BuyerEntity, on_delete=models.CASCADE, related_name="aliases")
    score = models.FloatField()
    method = models.CharField(max_length=16, choices=Method.choices)

    class Meta:
        db_table = "buyer_alias"


class BuyerReview(models.Model):
    """Candidate merges in the 80-90 band: not confident enough to merge automatically."""

    class Status(models.TextChoices):
        OPEN = "open"
        MERGED = "merged"
        REJECTED = "rejected"

    alias = models.TextField()
    candidate = models.ForeignKey(BuyerEntity, on_delete=models.CASCADE, related_name="+")
    score = models.FloatField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "buyer_review"
        constraints = [
            models.UniqueConstraint(fields=["alias", "candidate"], name="uniq_review_pair")
        ]


class Tender(models.Model):
    # Writes go through ingest.loader.upsert_tender (INSERT ... ON CONFLICT), not the ORM.
    source = models.CharField(max_length=32)
    source_tender_id = models.CharField(max_length=128)
    ref_no = models.TextField(blank=True, default="")
    title = models.TextField()
    buyer_raw = models.TextField()
    buyer_entity = models.ForeignKey(
        BuyerEntity, null=True, blank=True, on_delete=models.SET_NULL, related_name="tenders"
    )
    org_chain = models.TextField(blank=True, default="")
    category = models.CharField(max_length=64, blank=True, default="")
    product_category = models.CharField(max_length=128, blank=True, default="")
    tender_type = models.CharField(max_length=64, blank=True, default="")
    value_inr = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    emd_inr = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    fee_inr = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    published_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    opens_at = models.DateTimeField(null=True, blank=True)
    location = models.TextField(blank=True, default="")
    pincode = models.CharField(max_length=6, blank=True, default="")
    state = models.CharField(max_length=64, blank=True, default="")
    url = models.TextField(blank=True, default="")
    content_hash = models.CharField(max_length=64)
    # fetched_at of the page this row was parsed from; stops a backfill of an
    # older page from overwriting newer data.
    fetched_at = models.DateTimeField()
    raw_page = models.ForeignKey(
        "ingest.RawPage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    class Meta:
        db_table = "tender"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_tender_id"], name="tender_source_source_tender_id_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(closes_at__gte=models.F("published_at")),
                name="tender_closes_after_published",
            ),
            models.CheckConstraint(
                condition=models.Q(value_inr__isnull=True) | models.Q(value_inr__gte=0),
                name="tender_value_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["closes_at"]),
            models.Index(fields=["state"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return f"{self.source}:{self.source_tender_id}"
