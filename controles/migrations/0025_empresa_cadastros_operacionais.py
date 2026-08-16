# Generated during multiempresa phase 3B-2.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('controles', '0024_alter_cronogramaobra_empresa_and_more'),
        ('empresas', '0002_cria_empresa_ambar_e_vincula_usuarios'),
    ]

    operations = [
        migrations.AddField(
            model_name='veiculomaquina',
            name='empresa',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='veiculos_maquinas', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='bombonacombustivel',
            name='empresa',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='bombonas_combustivel', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='ordemcompracombustivel',
            name='empresa',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ordens_compra_combustivel', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='locadoraequipamento',
            name='empresa',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='locadoras_equipamentos', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='fornecedormaquinalocacao',
            name='empresa',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='fornecedores_maquinas_locacao', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='solicitanteconcretagem',
            name='empresa',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='solicitantes_concretagem', to='empresas.empresa'),
        ),
        migrations.AlterField(model_name='veiculomaquina', name='placa', field=models.CharField(max_length=20)),
        migrations.AlterField(model_name='bombonacombustivel', name='identificacao', field=models.CharField(max_length=80)),
        migrations.AlterField(model_name='ordemcompracombustivel', name='numero', field=models.CharField(blank=True, max_length=40)),
        migrations.AlterField(model_name='ordemcomprageral', name='numero', field=models.CharField(blank=True, max_length=40)),
        migrations.AlterField(model_name='locadoraequipamento', name='nome', field=models.CharField(max_length=150)),
        migrations.AlterField(model_name='fornecedormaquinalocacao', name='nome', field=models.CharField(max_length=150)),
        migrations.AlterField(model_name='ordemservicolocacaomaquina', name='numero', field=models.CharField(blank=True, max_length=40)),
        migrations.AlterField(model_name='orcamentoradarobra', name='numero', field=models.CharField(max_length=50)),
        migrations.AlterField(model_name='solicitanteconcretagem', name='nome', field=models.CharField(max_length=120)),
    ]
