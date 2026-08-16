# Generated during multiempresa phase 3B-2.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicoes', '0013_backfill_medicaoempreiteiro_empresa'),
    ]

    operations = [
        migrations.AlterField(
            model_name='medicaoempreiteiro',
            name='empresa',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='medicoes_empreiteiros',
                to='empresas.empresa',
            ),
        ),
    ]
