import logging

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from .models import Alert, Node, NodeLink, SensorReading
from . import openapi as o
from .permissions import IsAuthenticatedOrIngestAPIKey, IsAuthenticatedOrPublicRead
from .serializers import AlertSerializer, NodeSerializer, SensorReadingSerializer
from .services.health import get_health
from .services.ingestion import DuplicateReadingError, ingest_reading
from .services.alert_ordering import order_by_urgency
from .services.live_readings import live_readings
from .services.node_graph import node_graph
from .services.node_search import node_search_index
from .services.risk_zones import get_risk_zones
from .services.series import merge_sorted
from .services.series_queries import load_series, parse_series_query
from .services.nodes import (
    get_dashboard_summary,
    get_node_status,
    get_top_risk_nodes,
    nodes_with_current_risk,
)
from .services.pagination import TOTAL_COUNT_HEADER, paginate
from .throttles import IngestThrottle, ReadThrottle
from .services.reading_queries import filter_readings, parse_datetime_parameter


logger = logging.getLogger("api.readings")


class NodeViewSet(ModelViewSet):
    queryset = Node.objects.all()
    serializer_class = NodeSerializer
    permission_classes = [IsAuthenticatedOrPublicRead]
    lookup_field = "node_id"
    lookup_url_kwarg = "node_id"

    def get_queryset(self):
        return nodes_with_current_risk()


class NodeStatusView(APIView):
    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Estado de un nodo",
        description="Conexión, última lectura, riesgo actual, ventana de temperatura y alertas activas. "
        "Si el nodo está OFFLINE el riesgo es el último conocido (`current_risk_stale=true`).",
        responses={200: o.NodeStatusSerializer, 404: o.ErrorSerializer},
        examples=[o.EXAMPLE_NODE_STATUS],
    )
    def get(self, request, node_id):
        return Response(get_node_status(node_id))


class NodeReadingsView(APIView):
    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Lecturas de un nodo",
        parameters=[o.LIMIT, o.OFFSET, o.FROM, o.TO, o.RANGE, o.ORDER, o.TOTAL_COUNT_HEADER],
        responses={200: SensorReadingSerializer(many=True), 404: o.ErrorSerializer},
    )
    def get(self, request, node_id):
        node = get_object_or_404(Node, node_id=node_id)
        readings = SensorReading.objects.filter(node=node).select_related(
            "node",
            "assessment",
        )
        readings = filter_readings(readings, request.query_params)
        page, total = paginate(readings, request.query_params, default_limit=20)
        return Response(
            SensorReadingSerializer(page, many=True).data,
            headers={TOTAL_COUNT_HEADER: total},
        )


class NodeRecentReadingsView(APIView):
    """Últimas lecturas del nodo servidas desde el buffer en memoria."""

    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Últimas lecturas de un nodo (desde memoria)",
        description="De la más nueva a la más antigua, servidas desde un buffer en memoria sin consultar la base. "
        "La primera consulta tras un reinicio lo carga de la base.",
        parameters=[OpenApiParameter("limit", int, description="1 a `RECENT_READINGS_PER_NODE`; por defecto todas.")],
        responses={200: SensorReadingSerializer(many=True), 400: o.ErrorSerializer, 404: o.ErrorSerializer},
    )
    def get(self, request, node_id):
        node = get_object_or_404(Node, node_id=node_id)
        capacity = settings.RECENT_READINGS_PER_NODE
        raw_limit = request.query_params.get("limit")
        limit = capacity
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except ValueError:
                raise ParseError("'limit' debe ser un número entero.") from None
            if not 1 <= limit <= capacity:
                raise ParseError(f"'limit' debe estar entre 1 y {capacity}.")
        return Response(live_readings.recent(node, limit))


class NodeLinksView(APIView):
    """Vecinos directos de un nodo: listarlos y registrar uno nuevo."""

    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Vecinos directos de un nodo",
        responses={200: o.NodeLinksSerializer, 404: o.ErrorSerializer},
    )
    def get(self, request, node_id):
        get_object_or_404(Node, node_id=node_id)
        return Response(
            {"node_id": node_id, "neighbors": node_graph.direct_neighbors(node_id)}
        )

    @extend_schema(
        summary="Registrar un vecino",
        description="Requiere autenticación. La relación no tiene dirección.",
        request=o.NodeLinkRequestSerializer,
        responses={201: o.NodeLinkCreatedSerializer, 400: o.ErrorSerializer, 404: o.ErrorSerializer, 409: o.ErrorSerializer},
    )
    def post(self, request, node_id):
        node = get_object_or_404(Node, node_id=node_id)
        neighbor_id = request.data.get("neighbor") if hasattr(request.data, "get") else None
        if not isinstance(neighbor_id, str) or not neighbor_id.strip():
            raise ParseError("El campo 'neighbor' con el node_id del vecino es obligatorio.")
        neighbor_id = neighbor_id.strip()
        if neighbor_id == node_id:
            raise ParseError("Un nodo no puede ser vecino de sí mismo.")
        neighbor = Node.objects.filter(node_id=neighbor_id).first()
        if neighbor is None:
            raise ParseError(f"El nodo '{neighbor_id}' no existe.")

        first, second = sorted((node, neighbor), key=lambda item: item.pk)
        with transaction.atomic():
            _, created = NodeLink.objects.get_or_create(node_a=first, node_b=second)
        if not created:
            return Response(
                {"status": "error", "message": "Esos nodos ya son vecinos."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"node_id": node_id, "neighbor": neighbor_id},
            status=status.HTTP_201_CREATED,
        )


class NodeNeighborsView(APIView):
    """Nodos alcanzables desde un nodo en ``hops`` saltos o menos (BFS)."""

    permission_classes = [IsAuthenticatedOrPublicRead]
    default_hops = 1
    max_hops = 10

    @extend_schema(
        summary="Nodos alcanzables en K saltos",
        description="Recorrido en anchura sobre el grafo de vecinos, ordenado por distancia y luego por id.",
        parameters=[OpenApiParameter("hops", int, description="1 a 10; por defecto 1.")],
        responses={200: o.NodeNeighborsSerializer, 400: o.ErrorSerializer, 404: o.ErrorSerializer},
    )
    def get(self, request, node_id):
        get_object_or_404(Node, node_id=node_id)
        raw_hops = request.query_params.get("hops")
        hops = self.default_hops
        if raw_hops is not None:
            try:
                hops = int(raw_hops)
            except ValueError:
                raise ParseError("'hops' debe ser un número entero.") from None
            if not 1 <= hops <= self.max_hops:
                raise ParseError(f"'hops' debe estar entre 1 y {self.max_hops}.")
        reachable = node_graph.neighbors_within(node_id, hops)
        neighbors = [
            {"node_id": neighbor, "hops": distance}
            for neighbor, distance in sorted(reachable.items(), key=lambda item: (item[1], item[0]))
        ]
        return Response({"node_id": node_id, "hops": hops, "neighbors": neighbors})


class NodeLinkDetailView(APIView):
    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Quitar el vínculo entre dos nodos",
        description="Requiere autenticación.",
        responses={204: None, 404: o.ErrorSerializer},
    )
    def delete(self, request, node_id, neighbor_id):
        node = get_object_or_404(Node, node_id=node_id)
        neighbor = get_object_or_404(Node, node_id=neighbor_id)
        first, second = sorted((node, neighbor), key=lambda item: item.pk)
        link = get_object_or_404(NodeLink, node_a=first, node_b=second)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NodeSearchView(APIView):
    """Busca nodos por el comienzo de su ``node_id`` (para autocompletar)."""

    permission_classes = [IsAuthenticatedOrPublicRead]
    default_limit = 20
    max_limit = 100

    @extend_schema(
        summary="Buscar nodos por prefijo",
        description="Autocompletado por el comienzo del `node_id`, sin distinguir mayúsculas.",
        parameters=[
            OpenApiParameter("prefix", str, description="Comienzo del identificador; vacío lista los primeros."),
            OpenApiParameter("limit", int, description="1 a 100; por defecto 20."),
        ],
        responses={200: o.NodeSearchSerializer, 400: o.ErrorSerializer},
    )
    def get(self, request):
        prefix = request.query_params.get("prefix", "").strip()
        raw_limit = request.query_params.get("limit")
        limit = self.default_limit
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except ValueError:
                raise ParseError("'limit' debe ser un número entero.") from None
            if not 1 <= limit <= self.max_limit:
                raise ParseError(f"'limit' debe estar entre 1 y {self.max_limit}.")
        return Response(
            {"prefix": prefix, "results": node_search_index.search(prefix, limit)}
        )


class HealthView(APIView):
    """Estado del backend, la base de datos y la IA. Es público y sin límite de peticiones."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(
        summary="Estado del backend",
        description="200 si la base responde (`ok`, o `degraded` si la IA configurada no responde); 503 si la base está caída.",
        responses={200: o.HealthSerializer, 503: o.HealthSerializer},
        examples=[o.EXAMPLE_HEALTH_DEGRADED],
        auth=[],
    )
    def get(self, request):
        body, http_status = get_health()
        return Response(body, status=http_status)


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Resumen del dashboard",
        description="Conteos de nodos, riesgo global (solo nodos online), alertas activas y última lectura por nodo. "
        "Se reutiliza durante `DASHBOARD_CACHE_SECONDS`.",
        responses={200: o.DashboardSummarySerializer},
    )
    def get(self, request):
        return Response(get_dashboard_summary())


class DashboardTopRiskView(APIView):
    """Los K nodos de mayor riesgo actual."""

    permission_classes = [IsAuthenticatedOrPublicRead]
    default_k = 5
    max_k = 50

    @extend_schema(
        summary="Los K nodos de mayor riesgo",
        parameters=[OpenApiParameter("k", int, description="1 a 50; por defecto 5.")],
        responses={200: o.TopRiskNodeSerializer(many=True), 400: o.ErrorSerializer},
    )
    def get(self, request):
        raw_k = request.query_params.get("k")
        k = self.default_k
        if raw_k is not None:
            try:
                k = int(raw_k)
            except ValueError:
                raise ParseError("'k' debe ser un número entero.") from None
            if not 1 <= k <= self.max_k:
                raise ParseError(f"'k' debe estar entre 1 y {self.max_k}.")
        return Response(get_top_risk_nodes(k))


class DashboardZonesView(APIView):
    """Grupos de nodos vecinos que están en riesgo a la vez."""

    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Zonas de riesgo",
        description="Grupos de nodos vecinos conectados que están en WARNING o FIRE a la vez (solo nodos online).",
        responses={200: o.RiskZoneSerializer(many=True)},
        examples=[o.EXAMPLE_ZONES],
    )
    def get(self, request):
        return Response(get_risk_zones())


class ReadingSeriesView(APIView):
    """Serie histórica de un campo para uno o varios nodos (la usa el gráfico del frontend)."""

    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Serie histórica de un campo",
        description="Uno o varios nodos; con `step` devuelve el promedio por tramos y sin él los puntos. "
        "Con `merge=true` añade todos los nodos en una sola línea de tiempo.",
        parameters=[
            OpenApiParameter("node_id", str, many=True, required=True, description="Hasta 10; repetido o separado por comas."),
            OpenApiParameter("field", str, enum=["temperature", "humidity", "smoke", "gas"], description="Por defecto `temperature`."),
            o.FROM,
            o.TO,
            OpenApiParameter("step", int, description="Segundos por tramo (1 a 86400)."),
            OpenApiParameter("merge", bool, description="Mezcla los nodos en una sola línea de tiempo."),
        ],
        responses={200: o.SeriesResponseSerializer, 400: o.ErrorSerializer, 404: o.ErrorSerializer},
        examples=[o.EXAMPLE_SERIES],
    )
    def get(self, request):
        query = parse_series_query(request.query_params)
        series = []
        for node_id in query.node_ids:
            node_series = load_series(query, node_id)
            first, stop = node_series.index_range(query.start, query.end)
            entry = {
                "node_id": node_id,
                "count": stop - first,
                "average": node_series.mean_between(query.start, query.end),
            }
            if query.step is None:
                entry["points"] = [
                    {"timestamp": timestamp, "value": value}
                    for timestamp, value in node_series.points_between(query.start, query.end)
                ]
            else:
                entry["buckets"] = node_series.buckets(query.start, query.end, query.step)
            series.append(entry)

        body = {
            "field": query.field,
            "from": query.start,
            "to": query.end,
            "step": query.step,
            "series": series,
        }
        if query.merge:
            # Todas las series en una sola línea de tiempo (mezcla de k listas ordenadas).
            detail, time_key = ("points", "timestamp") if query.step is None else ("buckets", "start")
            body["merged"] = merge_sorted(
                [[{"node_id": entry["node_id"], **item} for item in entry[detail]] for entry in series],
                key=lambda item: item[time_key],
            )
        return Response(body)


class ReceiveMeasurementView(APIView):
    permission_classes = [IsAuthenticatedOrIngestAPIKey]
    throttle_classes = [ReadThrottle, IngestThrottle]

    @extend_schema(
        summary="Ingresar una lectura",
        description="Requiere `X-API-Key`. Evalúa el riesgo (reglas + IA) y puede crear o actualizar una alerta. "
        "Una lectura repetida (mismo nodo y `timestamp`) responde 200 con `status: duplicate` y no guarda nada.",
        request=SensorReadingSerializer,
        responses={201: o.IngestResponseSerializer, 200: o.IngestResponseSerializer, 400: o.ErrorSerializer, 401: o.ErrorSerializer},
        examples=[o.EXAMPLE_INGEST_REQUEST, o.EXAMPLE_FIRE_REQUEST],
    )
    def post(self, request):
        serializer = SensorReadingSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Lectura rechazada por datos inválidos.")
            return Response(
                {"status": "error", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            reading, risk_level, alert_id = ingest_reading(serializer)
        except DuplicateReadingError as duplicate:
            existing = duplicate.reading
            return Response(
                {
                    "status": "duplicate",
                    "message": "La lectura ya estaba registrada; no se guardó de nuevo.",
                    "reading": SensorReadingSerializer(existing).data,
                    "risk_level": SensorReadingSerializer(existing).data["risk_level"],
                    "alert_id": None,
                },
                status=status.HTTP_200_OK,
            )
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

    @extend_schema(
        summary="Listar lecturas",
        parameters=[OpenApiParameter("node_id", str, description="Filtra por nodo."), o.LIMIT, o.OFFSET, o.FROM, o.TO, o.RANGE, o.ORDER, o.TOTAL_COUNT_HEADER],
        responses={200: SensorReadingSerializer(many=True)},
    )
    def get(self, request):
        readings = SensorReading.objects.select_related("node", "assessment")

        node_id = request.query_params.get("node_id")
        if node_id:
            readings = readings.filter(node__node_id=node_id)

        readings = filter_readings(readings, request.query_params)
        page, total = paginate(readings, request.query_params, default_limit=20)
        return Response(
            SensorReadingSerializer(page, many=True).data,
            status=status.HTTP_200_OK,
            headers={TOTAL_COUNT_HEADER: total},
        )


class AlertListView(APIView):
    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Historial de alertas",
        parameters=[
            OpenApiParameter("status", str, enum=["ACTIVE", "ACKNOWLEDGED", "CLOSED"]),
            OpenApiParameter("level", str, enum=["WARNING", "FIRE"]),
            OpenApiParameter("node_id", str),
            o.FROM, o.TO, o.LIMIT, o.OFFSET, o.TOTAL_COUNT_HEADER,
        ],
        responses={200: AlertSerializer(many=True)},
    )
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
        page, total = paginate(alerts, request.query_params, default_limit=100)
        return Response(
            AlertSerializer(page, many=True).data,
            headers={TOTAL_COUNT_HEADER: total},
        )


class ActiveAlertListView(APIView):
    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(
        summary="Alertas activas por urgencia",
        description="`FIRE` antes que `WARNING` y, a igual nivel, la más antigua primero.",
        responses={200: AlertSerializer(many=True)},
    )
    def get(self, request):
        alerts = Alert.objects.filter(
            status__in=[Alert.Status.ACTIVE, Alert.Status.ACKNOWLEDGED]
        ).select_related("node", "reading")
        # Las más urgentes primero: gravedad y, a igual gravedad, antigüedad.
        return Response(AlertSerializer(order_by_urgency(alerts), many=True).data)


class AlertDetailView(APIView):
    permission_classes = [IsAuthenticatedOrPublicRead]

    @extend_schema(summary="Detalle de una alerta", responses={200: AlertSerializer, 404: o.ErrorSerializer})
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


@extend_schema(
    summary="Reconocer una alerta",
    description="Requiere autenticación. Transiciones válidas: ACTIVE → ACKNOWLEDGED → CLOSED y ACTIVE → CLOSED.",
    request=None,
    responses={200: AlertSerializer, 404: o.ErrorSerializer, 409: o.ErrorSerializer},
)
class AcknowledgeAlertView(AlertTransitionView):
    target_status = Alert.Status.ACKNOWLEDGED


@extend_schema(
    summary="Cerrar una alerta",
    description="Requiere autenticación. Transiciones válidas: ACTIVE → ACKNOWLEDGED → CLOSED y ACTIVE → CLOSED.",
    request=None,
    responses={200: AlertSerializer, 404: o.ErrorSerializer, 409: o.ErrorSerializer},
)
class CloseAlertView(AlertTransitionView):
    target_status = Alert.Status.CLOSED