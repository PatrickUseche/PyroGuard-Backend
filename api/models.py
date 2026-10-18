from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Node(models.Model):
    node_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    latitude = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    is_active = models.BooleanField(default=True)
    last_communication = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["node_id"]

    @property
    def connection_status(self):
        if self.last_communication is None:
            return "UNKNOWN"

        offline_threshold = settings.NODE_OFFLINE_THRESHOLD_SECONDS
        elapsed = (timezone.now() - self.last_communication).total_seconds()
        return "OFFLINE" if elapsed > offline_threshold else "ONLINE"

    def __str__(self):
        return self.name or self.node_id


class SensorReading(models.Model):
    node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name='readings')

    temperature = models.FloatField(
        validators=[MinValueValidator(-50), MaxValueValidator(150)],
    )
    humidity = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    smoke = models.FloatField(validators=[MinValueValidator(0)])
    gas = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    flame = models.BooleanField(default = False)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(
                fields=["node", "-timestamp"],
                name="reading_node_time_idx",
            ),
        ]

    def __str__(self):
        return f"{self.node.node_id} - {self.timestamp}"


class RiskAssessment(models.Model):
    class RiskLevel(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        WARNING = "WARNING", "Warning"
        FIRE = "FIRE", "Fire"

    reading = models.OneToOneField(
        SensorReading,
        on_delete=models.CASCADE,
        related_name="assessment",
    )
    risk_level = models.CharField(max_length=10, choices=RiskLevel.choices)
    ai_probability = models.FloatField(null=True, blank=True)
    ai_model_version = models.CharField(max_length=100, blank=True)
    rule_reasons = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.reading} - {self.risk_level}"


class Alert(models.Model):
    class Level(models.TextChoices):
        WARNING = "WARNING", "Warning"
        FIRE = "FIRE", "Fire"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        CLOSED = "CLOSED", "Closed"

    node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="alerts")
    reading = models.ForeignKey(
        SensorReading,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    assessment = models.ForeignKey(
        RiskAssessment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
    )
    level = models.CharField(max_length=10, choices=Level.choices)
    probability = models.FloatField(null=True, blank=True)
    message = models.TextField()
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    occurrences = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["status", "-created_at"],
                name="alert_status_created_idx",
            ),
            models.Index(
                fields=["node", "status"],
                name="alert_node_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.node.node_id} - {self.level} - {self.status}"