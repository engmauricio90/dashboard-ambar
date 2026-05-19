from django.db import migrations, transaction


def limpar_contas_pagar_e_pagas(apps, schema_editor):
    ContaPagar = apps.get_model('financeiro', 'ContaPagar')
    DespesaObra = apps.get_model('obras', 'DespesaObra')
    NotaFiscalOrdemCompraGeral = apps.get_model('controles', 'NotaFiscalOrdemCompraGeral')

    with transaction.atomic():
        contas = ContaPagar.objects.filter(status__in=['aberto', 'pago'])
        conta_ids = list(contas.values_list('id', flat=True))
        despesa_ids = list(
            DespesaObra.objects.filter(conta_pagar_origem__id__in=conta_ids).values_list('id', flat=True)
        )

        NotaFiscalOrdemCompraGeral.objects.filter(conta_pagar_id__in=conta_ids).update(conta_pagar=None)
        contas.delete()
        DespesaObra.objects.filter(id__in=despesa_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0011_cria_grupos_permissoes_financeiro'),
        ('controles', '0017_faturamentodireto_data_oc_e_dados_park_mall'),
    ]

    operations = [
        migrations.RunPython(limpar_contas_pagar_e_pagas, migrations.RunPython.noop),
    ]
