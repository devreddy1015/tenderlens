from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


class AlertSubscription(models.Model):
    """'Email me about tenders like this.'

    Area = any of `states` OR any of `pin_prefixes` (e.g. "490" for Bhilai/Durg). An empty
    area means all of India. `sectors`, `keywords` and `min_value_inr` narrow it further.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alerts"
    )
    name = models.CharField(max_length=120)
    states = ArrayField(models.CharField(max_length=64), default=list, blank=True)
    pin_prefixes = ArrayField(models.CharField(max_length=6), default=list, blank=True)
    sectors = ArrayField(models.CharField(max_length=32), default=list, blank=True)
    keywords = models.CharField(max_length=200, blank=True, default="")
    min_value_inr = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # High-water mark: tenders first seen after this are "new" for this alert. Null until
    # the first digest, which lists what is open right now.
    checked_until = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "alert_subscription"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user.email})"


class AlertDelivery(models.Model):
    """One tender emailed for one alert. The unique key makes resends impossible even if
    the send task runs twice."""

    subscription = models.ForeignKey(
        AlertSubscription, on_delete=models.CASCADE, related_name="deliveries"
    )
    tender = models.ForeignKey("tenders.Tender", on_delete=models.CASCADE, related_name="+")
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "alert_delivery"
        constraints = [
            models.UniqueConstraint(fields=["subscription", "tender"], name="uniq_alert_delivery")
        ]
