from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def connection_status_at(last_communication):
    """UNKNOWN, ONLINE u OFFLINE según cuándo fue la última comunicación."""
    if last_communication is None:
        return "UNKNOWN"

    offline_threshold = settings.NODE_OFFLINE_THRESHOLD_SECONDS
    elapsed = (timezone.now() - last_communication).total_seconds()
    return "OFFLINE" if elapsed > offline_threshold else "ONLINE"


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
        return connection_status_at(self.last_communication)

    def __str__(self):
        return self.name or self.node_id


class NodeLink(models.Model):
    """Dos nodos vecinos (cercanos entre sí). La relación no tiene dirección.

    Cada par se guarda una sola vez y siempre con ``node_a`` como el nodo de menor
    ``pk``: ``save`` reordena los extremos, así que unir A con B o B con A da la
    misma fila y no se puede duplicar el enlace.
    """

    node_a = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="links_as_a")
    node_b = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="links_as_b")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(node_a=models.F("node_b")),
                name="nodelink_not_self",
            ),
            models.UniqueConstraint(
                fields=["node_a", "node_b"],
                name="nodelink_unique_pair",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.node_a_id and self.node_b_id and self.node_a_id > self.node_b_id:
            self.node_a, self.node_b = self.node_b, self.node_a
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.node_a.node_id} <-> {self.node_b.node_id}"


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


class NotificationOutbox(models.Model):
    """Aviso pendiente de enviar por los canales de notificación.

    Guardar los avisos en la base (en vez de enviarlos en el momento) evita que un
    canal lento retrase la ingesta y permite reintentar si falla. ``priority`` menor
    significa más urgente.
    """

    class Kind(models.TextChoices):
        FIRE_ALERT = "FIRE_ALERT", "Alerta de incendio"
        OFFLINE_ALERT = "OFFLINE_ALERT", "Nodo desconectado con alerta activa"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        SENT = "SENT", "Enviado"
        FAILED = "FAILED", "Fallido"

    node = models.ForeignKey(Node, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    priority = models.PositiveSmallIntegerField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    delivered_channels = models.JSONField(default=list, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"], name="outbox_status_created_idx"),
            models.Index(fields=["node", "kind", "created_at"], name="outbox_node_kind_created_idx"),
        ]

    def __str__(self):
        return f"{self.kind} - {self.subject} - {self.status}"


class ReadingHourly(models.Model):
    """Resumen de las lecturas de un nodo durante una hora (se conserva tras la purga)."""

    node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="hourly_readings")
    hour = models.DateTimeField(help_text="Inicio de la hora, en UTC.")
    reading_count = models.PositiveIntegerField()
    temperature_min = models.FloatField()
    temperature_avg = models.FloatField()
    temperature_max = models.FloatField()
    humidity_avg = models.FloatField()
    smoke_max = models.FloatField()
    flame_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["node", "hour"]
        constraints = [
            models.UniqueConstraint(fields=["node", "hour"], name="readinghourly_unique_node_hour"),
        ]

    def __str__(self):
        return f"{self.node.node_id} - {self.hour:%Y-%m-%d %H:00}"


class RiskAssessment(models.Model):
    class RiskLevel(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        WARNING = "WARNING", "Warning"
        FIRE = "FIRE", "Fire"

    class AIStatus(models.TextChoices):
        OK = "OK", "Ok"
        DISABLED = "DISABLED", "Disabled"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        REJECTED = "REJECTED", "Rejected"
        INVALID_RESPONSE = "INVALID_RESPONSE", "Invalid response"
        PENDING = "PENDING", "Pending"

    reading = models.OneToOneField(
        SensorReading,
        on_delete=models.CASCADE,
        related_name="assessment",
    )
    risk_level = models.CharField(max_length=10, choices=RiskLevel.choices)
    ai_probability = models.FloatField(null=True, blank=True)
    ai_model_version = models.CharField(max_length=100, blank=True)
    # Resultado de PyroGuard-IA guardado para trazabilidad; risk_level es la decisión final.
    ai_status = models.CharField(
        max_length=20,
        choices=AIStatus.choices,
        default=AIStatus.DISABLED,
    )
    ai_risk_level = models.CharField(
        max_length=10,
        choices=RiskLevel.choices,
        blank=True,
    )
    ai_probabilities = models.JSONField(default=dict, blank=True)
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
