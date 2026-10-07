# Mounted at /api/ (api/urls.py): workspace, pipeline, recommendations, export/..., ocds/...
from django.urls import path

from workspaces import views

urlpatterns = [
    path("workspace", views.Workspace.as_view(), name="workspace"),
    path("workspaces", views.WorkspaceList.as_view(), name="workspace-list"),
    path("workspace/switch", views.WorkspaceSwitch.as_view(), name="workspace-switch"),
    path("workspace/calendar-token", views.CalendarToken.as_view(), name="calendar-token"),
    path("workspace/members", views.Members.as_view(), name="workspace-members"),
    path("workspace/members/<int:pk>", views.MemberDetail.as_view(), name="workspace-member"),
    path("workspace/invites", views.Invites.as_view(), name="workspace-invites"),
    path("workspace/invites/<int:pk>", views.InviteRevoke.as_view(), name="workspace-invite"),
    path("workspace/invites/<str:token>", views.InvitePreview.as_view(), name="invite-preview"),
    path(
        "workspace/invites/<str:token>/accept", views.InviteAccept.as_view(), name="invite-accept"
    ),
    path("workspace/api-keys", views.ApiKeys.as_view(), name="api-keys"),
    path("workspace/api-keys/<int:pk>", views.ApiKeyDetail.as_view(), name="api-key"),
    path("pipeline", views.Pipeline.as_view(), name="pipeline"),
    path("pipeline/summary", views.PipelineSummary.as_view(), name="pipeline-summary"),
    path("pipeline/calendar.ics", views.PipelineCalendar.as_view(), name="pipeline-calendar"),
    path("pipeline/<int:pk>", views.PipelineDetail.as_view(), name="pipeline-detail"),
    path("recommendations", views.Recommendations.as_view(), name="recommendations"),
    path("export/tenders.csv", views.ExportCsv.as_view(), name="export-csv"),
    path("ocds/releases", views.OcdsReleases.as_view(), name="ocds-releases"),
]
