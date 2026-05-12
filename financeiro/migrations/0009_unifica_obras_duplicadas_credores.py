from django.db import migrations


ALIASES_OBRAS = {
    'Orla de Ipanema': ['IPANEMA'],
    'Condomínio Rithmo': ['Condominio Rithmo'],
    'Orla Do Lami': ['LAMI'],
    'MC3 ENGENHARIA LTDA': ['MC3'],
    'Rede de Esgoto - CORSAN': ['CORSAN'],
    'ORLA 1': ['Orla 1 - Ambulantes', 'Orla 1 - Bares 1,2 e 3'],
}


def unificar_obras_duplicadas(apps, schema_editor):
    Obra = apps.get_model('obras', 'Obra')
    ContaPagar = apps.get_model('financeiro', 'ContaPagar')
    ContaReceber = apps.get_model('financeiro', 'ContaReceber')
    DespesaObra = apps.get_model('obras', 'DespesaObra')
    NotaFiscal = apps.get_model('obras', 'NotaFiscal')
    AditivoContrato = apps.get_model('obras', 'AditivoContrato')
    RetencaoTecnicaObra = apps.get_model('obras', 'RetencaoTecnicaObra')

    for nome_canonico, aliases in ALIASES_OBRAS.items():
        destino = Obra.objects.filter(nome_obra__iexact=nome_canonico).order_by('id').first()
        origens = list(Obra.objects.filter(nome_obra__in=aliases).order_by('id'))

        if not destino and origens:
            destino = origens.pop(0)
            destino.nome_obra = nome_canonico
            destino.save(update_fields=['nome_obra', 'updated_at'])

        if not destino:
            continue

        for origem in origens:
            if origem.id == destino.id:
                continue

            ContaPagar.objects.filter(obra=origem).update(obra=destino)
            ContaReceber.objects.filter(obra=origem).update(obra=destino)
            DespesaObra.objects.filter(obra=origem).update(obra=destino)
            AditivoContrato.objects.filter(obra=origem).update(obra=destino)
            RetencaoTecnicaObra.objects.filter(obra=origem).update(obra=destino)

            for nota in NotaFiscal.objects.filter(obra=origem).order_by('id'):
                if NotaFiscal.objects.filter(obra=destino, numero=nota.numero).exists():
                    nota.delete()
                else:
                    nota.obra = destino
                    nota.save(update_fields=['obra', 'updated_at'])

            origem.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0008_unifica_obra_ipanema'),
    ]

    operations = [
        migrations.RunPython(unificar_obras_duplicadas, migrations.RunPython.noop),
    ]
