from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    """Organisations (tenants), their members and company profile; later also invites,
    the bid pipeline, API keys and exports."""

    name = "workspaces"
