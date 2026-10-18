import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from .models import Alert, Node, SensorReading
from .permissions import IsAuthenticatedOrIngestAPIKey
from .serializers import AlertSerializer, NodeSerializer, SensorReadingSerializer
from .services.ingestion import ingest_reading
from .services.nodes import get_dashboard_summary, get_node_status, nodes_with_current_risk
from .services.reading_queries import filter_readings, parse_datetime_parameter


logger = logging.getLogger("api.readings")


class NodeViewSet(ModelViewSet):
    queryset = Node.objects.all()
    serializer_class = NodeSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "node_id"
    lookup_url_kwarg = "node_id"

    def get_queryset(self):
        return nodes_with_current_risk()


class NodeStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, node_id):
        return Response(get_node_status(node_id))


class NodeReadingsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, node_id):
        node = get_object_or_404(Node, node_id=node_id)
        readings = SensorReading.objects.filter(node=node).select_related(
            "node",
            "assessment",
        )
        readings = filter_readings(readings, request.query_params)
        return Response(SensorReadingSerializer(readings, many=True).data)


class DashboardSummaryView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(get_dashboard_summary())


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

        readings = filter_readings(readings, request.query_params)
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
            parse_datetime_parameter(from_value, "from") if from_value else None
        )
        to_date = (
            parse_datetime_parameter(to_value, "to") if to_value else None
        )
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