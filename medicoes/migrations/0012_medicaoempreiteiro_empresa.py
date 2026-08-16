# Generated during multiempresa phase 3B-2.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('empresas', '0002_cria_empresa_ambar_e_vincula_usuarios'),
        ('medicoes', '0011_alter_empreiteiro_empresa'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicaoempreiteiro',
            name='empresa',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='medicoes_empreiteiros',
                to='empresas.empresa',
            ),
        ),
    ]
