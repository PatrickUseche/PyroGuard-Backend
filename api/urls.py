from django.urls import path
from .views import ReceiveMeasurementView

urlpatterns = [
    path('readings/', ReceiveMeasurementView.as_view(), name='receive_reading'),   
]