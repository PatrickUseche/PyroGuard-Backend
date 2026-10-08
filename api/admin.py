from django.contrib import admin
from .models import Node, SensorReading

# Register your models here.

admin.site.register(Node)
admin.site.register(SensorReading)