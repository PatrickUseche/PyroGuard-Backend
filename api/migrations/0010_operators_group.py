from django.db import migrations


GROUP_NAME = "Operadores"


def create_operators_group(apps, schema_editor):
    group_model = apps.get_model("auth", "Group")
    group_model.objects.using(schema_editor.connection.alias).get_or_create(
        name=GROUP_NAME
    )


def remove_operators_group(apps, schema_editor):
    group_model = apps.get_model("auth", "Group")
    group_model.objects.using(schema_editor.connection.alias).filter(
        name=GROUP_NAME
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0009_googleaccount"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(
            create_operators_group,
            reverse_code=remove_operators_group,
        ),
    ]
