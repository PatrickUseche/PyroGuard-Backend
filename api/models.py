from django.db import models
from django.utils import timezone

# Create your models here.

class Node(models.Model):
    # Relacion: Una medicion pertenece a un nodo especifico
    node_id = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    last_communication = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
class SensorReading(models.Model):
    node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name='readings')
    
    # Variables de los sensores acordadas en el contrato
    temperature = models.FloatField
    humidity = models.FloatField
    smoke = models.FloatField
    flame = models.BooleanField(default = False)
    timestamp = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return f"{self.node.node_id} - {self.timestamp}"