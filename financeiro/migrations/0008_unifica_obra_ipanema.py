from django.db import migrations


def unificar_ipanema(apps, schema_editor):
    Obra = apps.get_model('obras', 'Obra')
    ContaPagar = apps.get_model('financeiro', 'ContaPagar')
    ContaReceber = apps.get_model('financeiro', 'ContaReceber')
    DespesaObra = apps.get_model('obras', 'DespesaObra')
    NotaFiscal = apps.get_model('obras', 'NotaFiscal')
    AditivoContrato = apps.get_model('obras', 'AditivoContrato')
    RetencaoTecnicaObra = apps.get_model('obras', 'RetencaoTecnicaObra')

    destino = Obra.objects.filter(nome_obra__iexact='Orla de Ipanema').order_by('id').first()
    origem = Obra.objects.filter(nome_obra__iexact='IPANEMA').order_by('id').first()

    if not origem:
        return

    if not destino:
        origem.nome_obra = 'Orla de Ipanema'
        origem.save(update_fields=['nome_obra', 'updated_at'])
        return

    if origem.id == destino.id:
        return

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
        ('financeiro', '0007_importa_relatorios_credores'),
    ]

    operations = [
        migrations.RunPython(unificar_ipanema, migrations.RunPython.noop),
    ]
