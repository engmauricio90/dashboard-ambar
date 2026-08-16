# Generated during multiempresa phase 3B-2.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('controles', '0026_backfill_empresa_cadastros_operacionais'),
    ]

    operations = [
        migrations.AlterField(model_name='veiculomaquina', name='empresa', field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='veiculos_maquinas', to='empresas.empresa')),
        migrations.AlterField(model_name='bombonacombustivel', name='empresa', field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bombonas_combustivel', to='empresas.empresa')),
        migrations.AlterField(model_name='ordemcompracombustivel', name='empresa', field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ordens_compra_combustivel', to='empresas.empresa')),
        migrations.AlterField(model_name='locadoraequipamento', name='empresa', field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='locadoras_equipamentos', to='empresas.empresa')),
        migrations.AlterField(model_name='fornecedormaquinalocacao', name='empresa', field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='fornecedores_maquinas_locacao', to='empresas.empresa')),
        migrations.AlterField(model_name='solicitanteconcretagem', name='empresa', field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='solicitantes_concretagem', to='empresas.empresa')),
        migrations.AddConstraint(model_name='veiculomaquina', constraint=models.UniqueConstraint(fields=('empresa', 'placa'), name='unique_veiculo_empresa_placa')),
        migrations.AddConstraint(model_name='bombonacombustivel', constraint=models.UniqueConstraint(fields=('empresa', 'identificacao'), name='unique_bombona_empresa_identificacao')),
        migrations.AddConstraint(model_name='ordemcompracombustivel', constraint=models.UniqueConstraint(fields=('empresa', 'numero'), name='unique_ordem_combustivel_empresa_numero')),
        migrations.AddConstraint(model_name='ordemcomprageral', constraint=models.UniqueConstraint(fields=('empresa', 'numero'), name='unique_ordem_compra_empresa_numero')),
        migrations.AddConstraint(model_name='locadoraequipamento', constraint=models.UniqueConstraint(fields=('empresa', 'nome'), name='unique_locadora_empresa_nome')),
        migrations.AddConstraint(model_name='fornecedormaquinalocacao', constraint=models.UniqueConstraint(fields=('empresa', 'nome'), name='unique_fornecedor_maquina_empresa_nome')),
        migrations.AddConstraint(model_name='ordemservicolocacaomaquina', constraint=models.UniqueConstraint(fields=('obra', 'numero'), name='unique_os_maquina_obra_numero')),
        migrations.AddConstraint(model_name='orcamentoradarobra', constraint=models.UniqueConstraint(fields=('empresa', 'numero'), name='unique_radar_empresa_numero')),
        migrations.AddConstraint(model_name='solicitanteconcretagem', constraint=models.UniqueConstraint(fields=('empresa', 'nome'), name='unique_solicitante_concretagem_empresa_nome')),
    ]
