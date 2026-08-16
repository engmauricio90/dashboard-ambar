# Generated during multiempresa phase 3B-2.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('propostas', '0004_alter_proposta_empresa'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='proposta',
            name='unique_numero_proposta_por_ano',
        ),
        migrations.AddConstraint(
            model_name='proposta',
            constraint=models.UniqueConstraint(
                fields=('empresa', 'numero_sequencial', 'ano'),
                name='unique_numero_proposta_empresa_ano',
            ),
        ),
    ]
