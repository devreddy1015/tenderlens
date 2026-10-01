from django.db import models


class CrawlRun(models.Model):
    """One crawl of one source. Counters are computed from CrawlItem at finalize time,
    so a task redelivered after a worker crash cannot double-count."""

    class Status(models.TextChoices):
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        MISMATCH = "mismatch"  # finished, but reconciliation found a gap
        FAILED = "failed"
        INCOMPLETE = "incomplete"  # closed by the stale-run sweeper

    source = models.CharField(max_length=32)
    mode = models.CharField(max_length=16, default="incremental")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    started = models.DateTimeField(auto_now_add=True)
    finished = models.DateTimeField(null=True, blank=True)
    pages = models.IntegerField(default=0)
    new = models.IntegerField(default=0)
    updated = models.IntegerField(default=0)
    unchanged = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)
    quarantined = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    # Count the portal claims (sum of per-organisation counts on the index page)
    expected = models.IntegerField(null=True, blank=True)
    listed = models.IntegerField(null=True, blank=True)
    reconciliation = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "crawl_run"
        ordering = ["-started"]

    def __str__(self):
        return f"CrawlRun#{self.pk} {self.source} {self.mode} {self.status}"


class RawPage(models.Model):
    """Every fetched page is stored before it is parsed. Re-parsing stored pages is
    what makes backfills possible without re-crawling."""

    class Kind(models.TextChoices):
        INDEX = "index"
        LISTING = "listing"
        DETAIL = "detail"

    source = models.CharField(max_length=32)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    url = models.TextField()
    fetched_at = models.DateTimeField(db_index=True)
    status = models.IntegerField()
    body_hash = models.CharField(max_length=64)
    body = models.TextField()  # TOAST-compressed with lz4 (see migration)
    crawl_run = models.ForeignKey(CrawlRun, null=True, on_delete=models.SET_NULL)
    # The listing row that led here; lets us find the detail page of a tender quickly.
    source_tender_id = models.CharField(max_length=128, blank=True, default="", db_index=True)

    class Meta:
        db_table = "raw_page"
        indexes = [models.Index(fields=["kind", "fetched_at"])]


class CrawlItem(models.Model):
    """The fate of one tender within one crawl run. Unique per (run, tender), so
    re-delivered tasks overwrite their own row instead of adding counts."""

    class Outcome(models.TextChoices):
        PENDING = "pending"
        NEW = "new"
        UPDATED = "updated"
        UNCHANGED = "unchanged"
        SKIPPED = "skipped"  # incremental crawl: listing row unchanged, detail not fetched
        QUARANTINED = "quarantined"
        FAILED = "failed"  # dead-lettered

    crawl_run = models.ForeignKey(CrawlRun, on_delete=models.CASCADE, related_name="items")
    source_tender_id = models.CharField(max_length=128)
    organisation = models.TextField(blank=True, default="")
    outcome = models.CharField(max_length=16, choices=Outcome.choices, default=Outcome.PENDING)
    raw_page = models.ForeignKey(RawPage, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "crawl_item"
        constraints = [
            models.UniqueConstraint(
                fields=["crawl_run", "source_tender_id"], name="uniq_crawl_item_per_run"
            )
        ]


class DeadLetter(models.Model):
    url = models.TextField()
    error = models.TextField()
    attempts = models.IntegerField(default=0)
    last_tried = models.DateTimeField(auto_now=True)
    task_name = models.CharField(max_length=128, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        db_table = "dead_letter"


class Quarantine(models.Model):
    """Rows that failed validation. Never silently dropped."""

    payload = models.JSONField()
    errors = models.JSONField()
    source = models.CharField(max_length=32, blank=True, default="")
    raw_page = models.ForeignKey(RawPage, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "quarantine"
