# Mounted at /api/copilot/ (api/urls.py). Contract: docs/PLATFORM_V2.md section 3.
from django.urls import path

from copilot import views

urlpatterns = [
    path("documents", views.DocumentList.as_view(), name="copilot-documents"),
    path("documents/<int:pk>", views.DocumentDetail.as_view(), name="copilot-document"),
    path("documents/<int:pk>/brief", views.DocumentBrief.as_view(), name="copilot-document-brief"),
    path("brief", views.TenderBrief.as_view(), name="copilot-brief"),
    path("ask", views.Ask.as_view(), name="copilot-ask"),
    path("eligibility", views.Eligibility.as_view(), name="copilot-eligibility"),
    path("status", views.Status.as_view(), name="copilot-status"),
]
