from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import SensorReadingSerializer

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