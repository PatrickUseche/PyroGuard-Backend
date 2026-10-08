from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import SensorReadingSerializer
from .models import SensorReading

# Create your views here.

class ReceiveMeasurementView(APIView):
    def post(self, request):
        serializer = SensorReadingSerializer(data=request.data)
        
        #Si el JSON es valido segun nuestro contrato.
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"status": "success", "message": "Medicion registrada correctamente."},
                status = status.HTTP_201_CREATED
            )
        
        # Si falta algun dato o el tipo de dato es incorrecto.
        return Response(
            {"status": "error", "errors": serializer.errors},
            status = status.HTTP_400_BAD_REQUEST
        )
    
    # NUEVO METODO: Para entregar los datos al Dashboard (FrontEnd - Angular).
    def get(self, request):
        # Se trae las ultimas 20 mediciones, ordenadas por decha descendente
        latest_readings = SensorReading.objects.all().order_by('-timestamp')[:20]
        
        # many = True le dice a DRF que vamos a serializar una lista de objetos, no solo uno
        serializer = SensorReadingSerializer(latest_readings, many=True)
        return Response(serializer.data, status = status.HTTP_200_OK)