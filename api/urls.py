from django.urls import include, path
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.routers import DefaultRouter

from .throttles import LoginThrottle
from .views import (
    AcknowledgeAlertView,
    ActiveAlertListView,
    AuthLogoutView,
    AuthMeView,
    AlertDetailView,
    AlertListView,
    CloseAlertView,
    DashboardSummaryView,
    DashboardTopRiskView,
    DashboardZonesView,
    GoogleLoginView,
    HealthView,
    NodeLinkDetailView,
    NodeLinksView,
    NodeNeighborsView,
    NodeReadingsView,
    NodeRecentReadingsView,
    NodeSearchView,
    NodeStatusView,
    NodeViewSet,
    ReadingSeriesView,
    ReceiveMeasurementView,
)

router = DefaultRouter()
router.register("nodes", NodeViewSet, basename="node")

urlpatterns = [
    path("readings/series/", ReadingSeriesView.as_view(), name="reading_series"),
    path("readings/", ReceiveMeasurementView.as_view(), name="receive_reading"),
    path("health/", HealthView.as_view(), name="health"),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard_summary"),
    path("dashboard/zones/", DashboardZonesView.as_view(), name="dashboard_zones"),
    path("dashboard/top-risk/", DashboardTopRiskView.as_view(), name="dashboard_top_risk"),
    path(
        "auth/login/",
        ObtainAuthToken.as_view(throttle_classes=[LoginThrottle]),
        name="api_token_auth",
    ),
    path("auth/google/", GoogleLoginView.as_view(), name="google_login"),
    path("auth/me/", AuthMeView.as_view(), name="auth_me"),
    path("auth/logout/", AuthLogoutView.as_view(), name="auth_logout"),
    path("nodes/<str:node_id>/neighbors/", NodeNeighborsView.as_view(), name="node_neighbors"),
    path("nodes/<str:node_id>/links/", NodeLinksView.as_view(), name="node_links"),
    path(
        "nodes/<str:node_id>/links/<str:neighbor_id>/",
        NodeLinkDetailView.as_view(),
        name="node_link_detail",
    ),
    # Antes del router: si no, «search» se tomaría como el node_id de un nodo.
    path("nodes/search/", NodeSearchView.as_view(), name="node_search"),
    path(
        "nodes/<str:node_id>/status/",
        NodeStatusView.as_view(),
        name="node_status",
    ),
    path(
        "nodes/<str:node_id>/readings/",
        NodeReadingsView.as_view(),
        name="node_readings",
    ),
    path(
        "nodes/<str:node_id>/recent/",
        NodeRecentReadingsView.as_view(),
        name="node_recent_readings",
    ),
    path("alerts/", AlertListView.as_view(), name="alert_list"),
    path("alerts/active/", ActiveAlertListView.as_view(), name="active_alerts"),
    path("alerts/<int:alert_id>/", AlertDetailView.as_view(), name="alert_detail"),
    path(
        "alerts/<int:alert_id>/acknowledge/",
        AcknowledgeAlertView.as_view(),
        name="alert_acknowledge",
    ),
    path(
        "alerts/<int:alert_id>/close/",
        CloseAlertView.as_view(),
        name="alert_close",
    ),
    path("", include(router.urls)),
]
