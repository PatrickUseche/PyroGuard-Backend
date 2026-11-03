"""Invalida las cachés en memoria cuando cambian los datos de los que dependen."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Alert, Node, RiskAssessment, SensorReading
from .services.dashboard_cache import dashboard_cache
from .services.node_status_cache import node_status_cache


@receiver([post_save, post_delete], sender=Node)
def invalidate_on_node_change(sender, instance, **kwargs):
    node_status_cache.invalidate(instance.node_id)
    dashboard_cache.invalidate()


@receiver(post_save, sender=SensorReading)
def invalidate_on_reading_saved(sender, instance, **kwargs):
    node_status_cache.invalidate(instance.node.node_id)
    dashboard_cache.invalidate()


@receiver(post_save, sender=RiskAssessment)
def invalidate_on_assessment_saved(sender, instance, **kwargs):
    node_status_cache.invalidate(instance.reading.node.node_id)
    dashboard_cache.invalidate()


@receiver(post_save, sender=Alert)
def invalidate_on_alert_saved(sender, instance, **kwargs):
    node_status_cache.invalidate(instance.node.node_id)
    dashboard_cache.invalidate()
