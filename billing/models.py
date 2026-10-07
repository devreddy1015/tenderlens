from django.db import models


class Usage(models.Model):
    """How much of a monthly quota an organisation used. One row per (org, key, month);
    billing.entitlements.consume increments it atomically."""

    organization = models.ForeignKey(
        "workspaces.Organization", on_delete=models.CASCADE, related_name="usage"
    )
    key = models.CharField(max_length=48)  # billing.plans.MONTHLY_KEYS
    period = models.CharField(max_length=7)  # "YYYY-MM", Asia/Kolkata
    count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_usage"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key", "period"], name="usage_org_key_period"
            )
        ]

    def __str__(self):
        return f"{self.organization_id} {self.key} {self.period}: {self.count}"


class Subscription(models.Model):
    """A paid plan bought through a payment provider. Organization.plan_code is derived
    from these (billing.services.sync_plan): the newest active subscription's plan, else
    free. Razorpay drives status changes through its webhook; "fake" is for development
    and tests; "manual" is an admin-made subscription (e.g. an Enterprise contract)."""

    class Status(models.TextChoices):
        CREATED = "created"  # checkout opened, not paid yet
        ACTIVE = "active"
        PENDING = "pending"  # a renewal charge failed; Razorpay retries, the plan stays
        HALTED = "halted"  # retries exhausted
        CANCELLED = "cancelled"
        COMPLETED = "completed"

    class Provider(models.TextChoices):
        RAZORPAY = "razorpay"
        FAKE = "fake"
        MANUAL = "manual"

    class Interval(models.TextChoices):
        MONTH = "month"
        YEAR = "year"

    # Statuses that grant the plan.
    ENTITLED = (Status.ACTIVE, Status.PENDING)
    # A cancelled or completed subscription never comes back; Razorpay creates a new one.
    TERMINAL = (Status.CANCELLED, Status.COMPLETED)

    organization = models.ForeignKey(
        "workspaces.Organization", on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan_code = models.CharField(max_length=32)
    interval = models.CharField(max_length=8, choices=Interval.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED)
    provider = models.CharField(max_length=16, choices=Provider.choices)
    provider_subscription_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_subscription"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.organization_id} {self.plan_code}/{self.interval} {self.status}"


class WebhookEvent(models.Model):
    """Every provider webhook delivery we accepted, by the provider's event id: a retried
    delivery finds its row and is acknowledged without being applied twice."""

    provider = models.CharField(max_length=16)
    event_id = models.CharField(max_length=128, unique=True)
    event = models.CharField(max_length=64)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "billing_webhook_event"
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.provider} {self.event} {self.event_id}"
