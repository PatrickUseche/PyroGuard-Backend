import logging
from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Alert, SensorReading
from .permissions import IsAuthenticatedOrIngestAPIKey
from .serializers import AlertSerializer, SensorReadingSerializer
from .services.ingestion import ingest_reading


logger = logging.getLogger("api.readings")


def _parse_datetime_parameter(value, parameter_name):
    parsed_value = parse_datetime(value)
    if parsed_value is None:
        raise ParseError(
            f"El parámetro '{parameter_name}' debe tener formato ISO 8601."
        )
    if timezone.is_naive(parsed_value):
        parsed_value = timezone.make_aware(parsed_value)
    return parsed_value


class ReceiveMeasurementView(APIView):
    permission_classes = [IsAuthenticatedOrIngestAPIKey]

    def post(self, request):
        serializer = SensorReadingSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Lectura rechazada por datos inválidos.")
            return Response(
                {"status": "error", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reading, risk_level, alert_id = ingest_reading(serializer)
        return Response(
            {
                "status": "success",
                "message": "Lectura registrada correctamente.",
                "reading": SensorReadingSerializer(reading).data,
                "risk_level": risk_level,
                "alert_id": alert_id,
            },
            status=status.HTTP_201_CREATED,
        )

    def get(self, request):
        readings = SensorReading.objects.select_related("node", "assessment")

        node_id = request.query_params.get("node_id")
        if node_id:
            readings = readings.filter(node__node_id=node_id)

        try:
            from_value = request.query_params.get("from")
            to_value = request.query_params.get("to")
            from_date = (
                _parse_datetime_parameter(from_value, "from")
                if from_value
                else None
            )
            to_date = (
                _parse_datetime_parameter(to_value, "to") if to_value else None
            )
            if from_date and to_date and from_date > to_date:
                raise ParseError(
                    "El parámetro 'from' no puede ser posterior a 'to'."
                )
            if from_date:
                readings = readings.filter(timestamp__gte=from_date)
            if to_date:
                readings = readings.filter(timestamp__lte=to_date)

            range_value = request.query_params.get("range")
            if range_value:
                range_durations = {
                    "24h": timedelta(hours=24),
                    "7d": timedelta(days=7),
                }
                if range_value not in range_durations:
                    raise ParseError("'range' debe ser '24h' o '7d'.")
                readings = readings.filter(
                    timestamp__gte=timezone.now() - range_durations[range_value]
                )

            limit = int(request.query_params.get("limit", "20"))
            if not 1 <= limit <= 500:
                raise ParseError("'limit' debe estar entre 1 y 500.")
        except (TypeError, ValueError):
            raise ParseError("'limit' debe ser un número entero.")
        except ParseError as error:
            logger.warning("Consulta de lecturas rechazada: %s", error.detail)
            raise

        order = request.query_params.get("order", "desc")
        if order not in {"asc", "desc"}:
            logger.warning("Consulta de lecturas rechazada: orden inválido.")
            raise ParseError("'order' debe ser 'asc' o 'desc'.")

        timestamp_order = "timestamp" if order == "asc" else "-timestamp"
        readings = readings.order_by(timestamp_order, "pk")[:limit]
        return Response(
            SensorReadingSerializer(readings, many=True).data,
            status=status.HTTP_200_OK,
        )


class AlertListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        alerts = Alert.objects.select_related("node", "reading")
        status_filter = request.query_params.get("status")
        level_filter = request.query_params.get("level")
        node_id = request.query_params.get("node_id")
        if status_filter:
            alerts = alerts.filter(status=status_filter)
        if level_filter:
            alerts = alerts.filter(level=level_filter)
        if node_id:
            alerts = alerts.filter(node__node_id=node_id)

        from_value = request.query_params.get("from")
        to_value = request.query_params.get("to")
        from_date = (
            _parse_datetime_parameter(from_value, "from") if from_value else None
        )
        to_date = _parse_datetime_parameter(to_value, "to") if to_value else None
        if from_date and to_date and from_date > to_date:
            raise ParseError("El parámetro 'from' no puede ser posterior a 'to'.")
        if from_date:
            alerts = alerts.filter(created_at__gte=from_date)
        if to_date:
            alerts = alerts.filter(created_at__lte=to_date)

        alerts = alerts.order_by("-created_at", "-pk")
        return Response(AlertSerializer(alerts, many=True).data)


class ActiveAlertListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        alerts = Alert.objects.filter(
            status__in=[Alert.Status.ACTIVE, Alert.Status.ACKNOWLEDGED]
        ).select_related("node", "reading")
        alerts = alerts.order_by("-created_at", "-pk")
        return Response(AlertSerializer(alerts, many=True).data)


class AlertDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, alert_id):
        alert = get_object_or_404(
            Alert.objects.select_related("node", "reading"),
            pk=alert_id,
        )
        return Response(AlertSerializer(alert).data)


class AlertTransitionView(APIView):
    permission_classes = [IsAuthenticated]
    target_status = None

    def post(self, request, alert_id):
        with transaction.atomic():
            alert = get_object_or_404(
                Alert.objects.select_for_update(),
                pk=alert_id,
            )
            allowed_sources = {
                Alert.Status.ACKNOWLEDGED: {Alert.Status.ACTIVE},
                Alert.Status.CLOSED: {
                    Alert.Status.ACTIVE,
                    Alert.Status.ACKNOWLEDGED,
                },
            }
            if alert.status not in allowed_sources[self.target_status]:
                return Response(
                    {
                        "status": "error",
                        "message": "La transición de alerta no es válida.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            now = timezone.now()
            alert.status = self.target_status
            update_fields = ["status"]
            if self.target_status == Alert.Status.ACKNOWLEDGED:
                alert.acknowledged_at = now
                update_fields.append("acknowledged_at")
            else:
                alert.closed_at = now
                update_fields.append("closed_at")
            alert.save(update_fields=update_fields)
        return Response(AlertSerializer(alert).data, status=status.HTTP_200_OK)


class AcknowledgeAlertView(AlertTransitionView):
    target_status = Alert.Status.ACKNOWLEDGED


class CloseAlertView(AlertTransitionView):
    target_status = Alert.Status.CLOSED