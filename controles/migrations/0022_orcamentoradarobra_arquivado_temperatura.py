from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('controles', '0021_alter_itemordemcomprageral_quantidade_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='orcamentoradarobra',
            name='arquivado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='orcamentoradarobra',
            name='temperatura',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (5, 'Muito quente'),
                    (4, 'Quente'),
                    (3, 'Morno'),
                    (2, 'Frio'),
                    (1, 'Muito frio'),
                ],
                default=3,
            ),
        ),
    ]
