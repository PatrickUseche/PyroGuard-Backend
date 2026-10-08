from rest_framework import serializers
from .models import Node, SensorReading

class SensorReadingSerializer(serializers.ModelSerializer):
    node_id = serializers.CharField(write_only=True)
    
    class Meta:
        model = SensorReading
        fields = [
            'node_id',
            'temperature',
            'humidity',
            'smoke',
            'flame',
            'timestamp'
        ]
        
    def create(self, validated_data):
        node_id_str = validated_data.pop('node_id')
            
        try:
            node = Node.objects.get(node_id = node_id_str)
        except Node.DoesNotExist:
            raise serializers.ValidationError({"node_id": f"El nodo '{node_id_str}' no esta registrado."})
            
        reading = SensorReading.objects.create(node = node, **validated_data)
        return reading