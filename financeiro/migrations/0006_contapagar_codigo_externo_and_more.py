from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('controles', '0015_alter_notafiscalordemcomprageral_conta_pagar'),
        ('financeiro', '0005_itemcontapagarordemcompra'),
        ('obras', '0006_carrega_dados_orla_lami'),
    ]

    operations = [
        migrations.AddField(
            model_name='contapagar',
            name='codigo_externo',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='contapagar',
            name='origem_importacao',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddConstraint(
            model_name='contapagar',
            constraint=models.UniqueConstraint(condition=models.Q(models.Q(('origem_importacao', ''), _negated=True), models.Q(('codigo_externo', ''), _negated=True)), fields=('origem_importacao', 'codigo_externo'), name='unique_conta_pagar_origem_codigo_externo'),
        ),
    ]
