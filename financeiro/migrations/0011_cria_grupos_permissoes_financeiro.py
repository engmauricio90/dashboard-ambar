from django.db import migrations


GRUPOS = ['Financeiro', 'Compras', 'Engenharia', 'Diretoria']


def criar_grupos(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    for nome_grupo in GRUPOS:
        Group.objects.get_or_create(name=nome_grupo)


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0010_unifica_obras_duplicadas_por_prioridade'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(criar_grupos, migrations.RunPython.noop),
    ]
