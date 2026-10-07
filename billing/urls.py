# Mounted at /api/billing/ (api/urls.py).
from django.urls import path

from billing import views

urlpatterns = [
    path("plans", views.Plans.as_view(), name="billing-plans"),
    path("subscription", views.CurrentSubscription.as_view(), name="billing-subscription"),
    path("checkout", views.Checkout.as_view(), name="billing-checkout"),
    path("cancel", views.Cancel.as_view(), name="billing-cancel"),
    path("webhook", views.webhook, name="billing-webhook"),
]
