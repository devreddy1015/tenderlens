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
