# Generated during multiempresa phase 3B-2.

from django.db import migrations


def backfill_empresa_cadastros_operacionais(apps, schema_editor):
    Empresa = apps.get_model('empresas', 'Empresa')
    VeiculoMaquina = apps.get_model('controles', 'VeiculoMaquina')
    BombonaCombustivel = apps.get_model('controles', 'BombonaCombustivel')
    OrdemCompraCombustivel = apps.get_model('controles', 'OrdemCompraCombustivel')
    LocadoraEquipamento = apps.get_model('controles', 'LocadoraEquipamento')
    FornecedorMaquinaLocacao = apps.get_model('controles', 'FornecedorMaquinaLocacao')
    SolicitanteConcretagem = apps.get_model('controles', 'SolicitanteConcretagem')

    empresa_padrao = Empresa.objects.get(slug='ambar')

    VeiculoMaquina.objects.filter(empresa__isnull=True).update(empresa=empresa_padrao)
    BombonaCombustivel.objects.filter(empresa__isnull=True).update(empresa=empresa_padrao)
    LocadoraEquipamento.objects.filter(empresa__isnull=True).update(empresa=empresa_padrao)
    FornecedorMaquinaLocacao.objects.filter(empresa__isnull=True).update(empresa=empresa_padrao)
    SolicitanteConcretagem.objects.filter(empresa__isnull=True).update(empresa=empresa_padrao)

    for ordem in OrdemCompraCombustivel.objects.select_related('fornecedor_cadastro', 'veiculo', 'bombona'):
        empresa = None
        if ordem.fornecedor_cadastro_id:
            empresa = ordem.fornecedor_cadastro.empresa
        elif ordem.veiculo_id:
            empresa = ordem.veiculo.empresa
        elif ordem.bombona_id:
            empresa = ordem.bombona.empresa
        ordem.empresa = empresa or empresa_padrao
        ordem.save(update_fields=['empresa'])


class Migration(migrations.Migration):

    dependencies = [
        ('controles', '0025_empresa_cadastros_operacionais'),
    ]

    operations = [
        migrations.RunPython(backfill_empresa_cadastros_operacionais, migrations.RunPython.noop),
    ]
