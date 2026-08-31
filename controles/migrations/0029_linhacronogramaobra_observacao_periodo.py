from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('controles', '0028_alter_ordemcomprageral_empresa_cnpj_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='linhacronogramaobra',
            name='observacao_periodo',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
