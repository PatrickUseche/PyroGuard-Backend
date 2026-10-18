from django.urls import path
from .views import (
    AcknowledgeAlertView,
    ActiveAlertListView,
    AlertDetailView,
    AlertListView,
    CloseAlertView,
    ReceiveMeasurementView,
)

urlpatterns = [
    path("readings/", ReceiveMeasurementView.as_view(), name="receive_reading"),
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
]