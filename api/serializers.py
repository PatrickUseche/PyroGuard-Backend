from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from .models import Alert, Node, RiskAssessment, SensorReading


class JsonBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if type(data) is bool:
            return data
        if type(data) is int and data in (0, 1):
            return bool(data)
        self.fail("invalid", input=data)


class SensorReadingSerializer(serializers.ModelSerializer):
    node_id = serializers.CharField(
        write_only=True,
        max_length=50,
        error_messages={
            "required": "El identificador del nodo es obligatorio.",
            "blank": "El identificador del nodo no puede estar vacío.",
        },
    )
    temperature = serializers.FloatField(
        min_value=-50,
        max_value=150,
        error_messages={
            "required": "La temperatura es obligatoria.",
            "invalid": "La temperatura debe ser un número válido.",
            "min_value": "La temperatura no puede ser menor que -50.",
            "max_value": "La temperatura no puede ser mayor que 150.",
        },
    )
    humidity = serializers.FloatField(
        min_value=0,
        max_value=100,
        error_messages={
            "required": "La humedad es obligatoria.",
            "invalid": "La humedad debe ser un número válido.",
            "min_value": "La humedad no puede ser menor que 0.",
            "max_value": "La humedad no puede ser mayor que 100.",
        },
    )
    smoke = serializers.FloatField(
        min_value=0,
        error_messages={
            "required": "El nivel de humo es obligatorio.",
            "invalid": "El nivel de humo debe ser un número válido.",
            "min_value": "El nivel de humo no puede ser menor que 0.",
        },
    )
    gas = serializers.FloatField(
        min_value=0,
        required=False,
        allow_null=True,
        error_messages={
            "invalid": "El nivel de gas debe ser un número válido.",
            "min_value": "El nivel de gas no puede ser menor que 0.",
        },
    )
    flame = JsonBooleanField(
        error_messages={
            "required": "El estado de llama es obligatorio.",
            "invalid": "La llama debe ser un booleano o 0/1.",
        },
    )
    timestamp = serializers.DateTimeField(
        error_messages={
            "required": "La fecha de la lectura es obligatoria.",
            "invalid": "La fecha debe estar en formato ISO 8601.",
        },
    )
    risk_level = serializers.SerializerMethodField()

    class Meta:
        model = SensorReading
        fields = [
            "node_id",
            "temperature",
            "humidity",
            "smoke",
            "gas",
            "flame",
            "timestamp",
            "risk_level",
        ]

    def validate_node_id(self, value):
        if (
            not settings.AUTO_REGISTER_NODES
            and not Node.objects.filter(node_id=value).exists()
        ):
            raise serializers.ValidationError(
                f"El nodo '{value}' no existe."
            )
        return value

    def validate_timestamp(self, value):
        if value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError(
                "La fecha de la lectura no puede superar 5 minutos en el futuro."
            )
        return value

    def create(self, validated_data):
        node_id = validated_data.pop("node_id")
        if settings.AUTO_REGISTER_NODES:
            node, _ = Node.objects.get_or_create(node_id=node_id)
        else:
            node = Node.objects.get(node_id=node_id)
        return SensorReading.objects.create(node=node, **validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["node_id"] = instance.node.node_id
        return data

    def get_risk_level(self, instance):
        try:
            return instance.assessment.risk_level
        except RiskAssessment.DoesNotExist:
            return None


class AlertSerializer(serializers.ModelSerializer):
    node_id = serializers.CharField(source="node.node_id", read_only=True)
    reading_id = serializers.IntegerField(source="reading.pk", read_only=True)

    class Meta:
        model = Alert
        fields = [
            "id",
            "node_id",
            "reading_id",
            "level",
            "probability",
            "message",
            "status",
            "occurrences",
            "created_at",
            "last_seen_at",
            "acknowledged_at",
            "closed_at",
        ]