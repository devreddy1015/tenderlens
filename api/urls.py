from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from api import views

urlpatterns = [
    path("tenders", views.TenderList.as_view(), name="tender-list"),
    path("tenders/<int:pk>", views.TenderDetail.as_view(), name="tender-detail"),
    path("buyers/<int:pk>", views.BuyerDetail.as_view(), name="buyer-detail"),
    path("stats", views.Stats.as_view(), name="stats"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
