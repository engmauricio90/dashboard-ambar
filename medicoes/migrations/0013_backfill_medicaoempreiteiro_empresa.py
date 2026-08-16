# Generated during multiempresa phase 3B-2.

from django.db import migrations


def backfill_medicaoempreiteiro_empresa(apps, schema_editor):
    Empresa = apps.get_model('empresas', 'Empresa')
    MedicaoEmpreiteiro = apps.get_model('medicoes', 'MedicaoEmpreiteiro')
    empresa_padrao = Empresa.objects.get(slug='ambar')

    for medicao in MedicaoEmpreiteiro.objects.select_related('obra', 'orcamento__obra', 'empreiteiro_cadastro'):
        empresa = None
        if medicao.obra_id:
            empresa = medicao.obra.empresa
        elif medicao.orcamento_id:
            empresa = medicao.orcamento.obra.empresa
        elif medicao.empreiteiro_cadastro_id:
            empresa = medicao.empreiteiro_cadastro.empresa
        medicao.empresa = empresa or empresa_padrao
        medicao.save(update_fields=['empresa'])


class Migration(migrations.Migration):

    dependencies = [
        ('medicoes', '0012_medicaoempreiteiro_empresa'),
    ]

    operations = [
        migrations.RunPython(backfill_medicaoempreiteiro_empresa, migrations.RunPython.noop),
    ]
