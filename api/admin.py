from django.contrib import admin

from .models import Alert, Node, NodeLink, NotificationOutbox, ReadingHourly, RiskAssessment, SensorReading


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = (
        "node_id",
        "name",
        "connection_status",
        "is_active",
        "last_communication",
    )
    list_filter = ("is_active",)
    search_fields = ("node_id", "name", "description")


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
    list_filter = ("flame", "timestamp")
    search_fields = ("node__node_id", "node__name")


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
    list_filter = ("status", "level", "created_at")
    search_fields = ("node__node_id", "node__name", "message")


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
