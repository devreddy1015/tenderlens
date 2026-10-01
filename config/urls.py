from django.urls import include, path

from api.views import health

urlpatterns = [
    path("health", health, name="health"),
    path("api/", include("api.urls")),
]
