from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from .views import (
    AcknowledgeAlertView,
    ActiveAlertListView,
    AlertDetailView,
    AlertListView,
    CloseAlertView,
    DashboardSummaryView,
    NodeReadingsView,
    NodeStatusView,
    NodeViewSet,
    ReceiveMeasurementView,
)

router = DefaultRouter()
router.register("nodes", NodeViewSet, basename="node")

urlpatterns = [
    path("readings/", ReceiveMeasurementView.as_view(), name="receive_reading"),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard_summary"),
    path("auth/login/", obtain_auth_token, name="api_token_auth"),
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