from django.apps import AppConfig


class BillingConfig(AppConfig):
    """Plans, monthly usage quotas and (later) Razorpay subscriptions."""

    name = "billing"
