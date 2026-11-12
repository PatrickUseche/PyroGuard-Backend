from django.db import migrations, models
from django.db.models import Count


def remove_duplicate_readings(apps, schema_editor):
    """Deja una sola lectura por (nodo, timestamp) antes de crear la restricción.

    Se conserva la que tiene alertas (para no perder el historial) y, si ninguna
    o varias las tienen, la más antigua. Las demás se borran.
    """
    reading_model = apps.get_model("api", "SensorReading")
    alias = schema_editor.connection.alias
    groups = (
        reading_model.objects.using(alias)
        .values("node_id", "timestamp")
        .annotate(total=Count("pk"))
        .filter(total__gt=1)
    )
    for group in groups:
        rows = list(
            reading_model.objects.using(alias)
            .filter(node_id=group["node_id"], timestamp=group["timestamp"])
            .annotate(alert_total=Count("alerts"))
            .order_by("-alert_total", "pk")
        )
        reading_model.objects.using(alias).filter(
            pk__in=[row.pk for row in rows[1:]]
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0010_operators_group"),
    ]

    operations = [
        migrations.RunPython(remove_duplicate_readings, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="sensorreading",
            constraint=models.UniqueConstraint(
                fields=("node", "timestamp"),
                name="reading_unique_node_timestamp",
            ),
        ),
    ]
