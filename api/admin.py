from datetime import timedelta

from django.conf import settings
from django.contrib import admin
from django.utils import timezone

from .models import (
    Alert,
    GoogleAccount,
    Node,
    NodeLink,
    NotificationOutbox,
    ReadingHourly,
    RiskAssessment,
    SensorReading,
)


class ConnectionStatusFilter(admin.SimpleListFilter):
    """Filtra los nodos por su conexión, con el mismo umbral que usa la API."""

    title = "conexión"
    parameter_name = "connection"

    def lookups(self, request, model_admin):
        return [("ONLINE", "En línea"), ("OFFLINE", "Desconectado"), ("UNKNOWN", "Sin comunicación aún")]

    def queryset(self, request, queryset):
        cutoff = timezone.now() - timedelta(seconds=settings.NODE_OFFLINE_THRESHOLD_SECONDS)
        if self.value() == "ONLINE":
            return queryset.filter(last_communication__gte=cutoff)
        if self.value() == "OFFLINE":
            return queryset.filter(last_communication__lt=cutoff)
        if self.value() == "UNKNOWN":
            return queryset.filter(last_communication__isnull=True)
        return queryset


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = (
        "node_id",
        "name",
        "connection_status",
        "is_active",
        "last_communication",
        "created_at",
    )
    list_filter = (ConnectionStatusFilter, "is_active", "created_at")
    search_fields = ("node_id", "name", "description")
    date_hierarchy = "created_at"
    ordering = ("node_id",)


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = (
        "node",
        "temperature",
        "humidity",
        "smoke",
        "gas",
        "flame",
        "timestamp",
    )
    list_filter = (
        ("node", admin.RelatedOnlyFieldListFilter),
        "flame",
        "assessment__risk_level",
        "timestamp",
    )
    search_fields = ("node__node_id", "node__name")
    date_hierarchy = "timestamp"
    list_select_related = ("node",)
    list_per_page = 50


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "reading",
        "risk_level",
        "ai_status",
        "ai_risk_level",
        "ai_probability",
        "ai_model_version",
        "created_at",
    )
    list_filter = ("risk_level", "ai_status", "ai_risk_level", "created_at")
    search_fields = ("reading__node__node_id", "ai_model_version")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        "node",
        "level",
        "status",
        "occurrences",
        "created_at",
        "last_seen_at",
        "acknowledged_at",
        "closed_at",
    )
    list_filter = (
        "status",
        "level",
        ("node", admin.RelatedOnlyFieldListFilter),
        "created_at",
    )
    search_fields = ("node__node_id", "node__name", "message")
    date_hierarchy = "created_at"
    list_select_related = ("node",)


@admin.register(NodeLink)
class NodeLinkAdmin(admin.ModelAdmin):
    list_display = ("node_a", "node_b", "created_at")
    search_fields = ("node_a__node_id", "node_b__node_id")


@admin.register(ReadingHourly)
class ReadingHourlyAdmin(admin.ModelAdmin):
    list_display = ("node", "hour", "reading_count", "temperature_avg", "temperature_max")
    list_filter = ("hour",)
    search_fields = ("node__node_id",)


@admin.register(NotificationOutbox)
class NotificationOutboxAdmin(admin.ModelAdmin):
    list_display = ("subject", "kind", "priority", "status", "attempts", "created_at", "sent_at")
    list_filter = ("status", "kind")
    search_fields = ("subject", "node__node_id")


@admin.register(GoogleAccount)
class GoogleAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "google_sub", "created_at")
    search_fields = ("user__username", "user__email", "google_sub")
