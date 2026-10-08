from rest_framework import serializers
from .models import Node, SensorReading

class SensorReadingSerializer(serializers.ModelSerializer):
    node_id = serializers.SlugRelatedField(
        queryset=Node.objects.all(),
        slug_field='node_id',
        source='node' 
    )
    
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