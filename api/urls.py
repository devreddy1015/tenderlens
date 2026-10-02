from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts import views as accounts
from alerts import views as alerts
from api import views
from feedback import views as feedback

urlpatterns = [
    path("tenders", views.TenderList.as_view(), name="tender-list"),
    path("tenders/<int:pk>", views.TenderDetail.as_view(), name="tender-detail"),
    path("buyers/<int:pk>", views.BuyerDetail.as_view(), name="buyer-detail"),
    path("tenders/<int:pk>/similar", views.SimilarTenders.as_view(), name="tender-similar"),
    path("stats", views.Stats.as_view(), name="stats"),
    path("sectors", views.Sectors.as_view(), name="sectors"),
    path("map", views.MapStats.as_view(), name="map"),
    path("config", views.site_config, name="config"),
    path("auth/me", accounts.Me.as_view(), name="auth-me"),
    path("auth/google", accounts.GoogleLogin.as_view(), name="auth-google"),
    path("auth/dev-login", accounts.DevLogin.as_view(), name="auth-dev-login"),
    path("auth/logout", accounts.Logout.as_view(), name="auth-logout"),
    path("alerts", alerts.AlertList.as_view(), name="alert-list"),
    path("alerts/preview", alerts.alert_preview, name="alert-preview"),
    path("alerts/unsubscribe", alerts.unsubscribe, name="alert-unsubscribe"),
    path("alerts/<int:pk>", alerts.AlertDetail.as_view(), name="alert-detail"),
    path("alerts/<int:pk>/test", alerts.AlertTest.as_view(), name="alert-test"),
    path("feedback", feedback.FeedbackCreate.as_view(), name="feedback"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
