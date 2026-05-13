from django.db import migrations


def importar_relatorios_credores(apps, schema_editor):
    # Importacao operacional foi removida da migration.
    # Use: python manage.py importar_credores_sienge <arquivo.csv> --tipo aberto|pago
    return


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0006_contapagar_codigo_externo_and_more'),
    ]

    operations = [
        migrations.RunPython(importar_relatorios_credores, migrations.RunPython.noop),
    ]
