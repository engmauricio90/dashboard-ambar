import re
import unicodedata
from decimal import Decimal

from django.db import migrations


GRUPOS_OBRAS = [
    ['Orla de Ipanema', 'IPANEMA'],
    ['Condomínio Rithmo', 'Condominio Rithmo'],
    ['Orla Do Lami', 'LAMI'],
    ['MC3 ENGENHARIA LTDA', 'MC3'],
    ['Jardim das Extremosas', 'GARTEN HAUS'],
    ['Rede de Esgoto Sapiranga (CORSAN)', 'Rede de Esgoto - CORSAN', 'CORSAN'],
    ['ORLA 1', 'Orla 1 - Ambulantes', 'Orla 1 - Bares 1,2 e 3'],
    ['EMEB DARCY BORGES DE CASTILHOS', 'EMEB DARCY BORGES', 'EMEB Darcy Borges de Castilhos'],
]


def normalizar(valor):
    sem_acento = unicodedata.normalize('NFKD', valor or '').encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', sem_acento).strip().casefold()


def valor_decimal(valor):
    return valor or Decimal('0')


def score_obra(obra, models):
    NotaFiscal, AditivoContrato, DespesaObra, ContaPagar, ContaReceber = models
    notas = NotaFiscal.objects.filter(obra=obra).count()
    aditivos = AditivoContrato.objects.filter(obra=obra).count()
    despesas = DespesaObra.objects.filter(obra=obra).count()
    contas_pagar = ContaPagar.objects.filter(obra=obra).count()
    contas_receber = ContaReceber.objects.filter(obra=obra).count()
    contrato = (
        valor_decimal(obra.valor_contrato)
        + valor_decimal(obra.aditivos)
        + valor_decimal(obra.projecao_despesa)
        + valor_decimal(obra.valor_notas)
    )
    tem_contrato = contrato > 0
    return (
        1 if notas or aditivos or tem_contrato or contas_receber else 0,
        notas,
        1 if tem_contrato else 0,
        aditivos,
        contas_receber,
        despesas + contas_pagar,
        -obra.id,
    )


def escolher_destino(obras, nomes_grupo, models):
    if not obras:
        return None
    melhor = max(obras, key=lambda obra: score_obra(obra, models))
    melhor_score = score_obra(melhor, models)
    if melhor_score[0] > 0:
        return melhor

    nomes_normalizados = [normalizar(nome) for nome in nomes_grupo]
    for nome_normalizado in nomes_normalizados:
        for obra in obras:
            if normalizar(obra.nome_obra) == nome_normalizado:
                return obra
    return obras[0]


def mover_notas_fiscais(origem, destino, NotaFiscal, RetencaoNotaFiscal, ImpostoNotaFiscal):
    for nota in NotaFiscal.objects.filter(obra=origem).order_by('id'):
        existente = NotaFiscal.objects.filter(obra=destino, numero=nota.numero).first()
        if existente:
            RetencaoNotaFiscal.objects.filter(nota_fiscal=nota).update(nota_fiscal=existente)
            ImpostoNotaFiscal.objects.filter(nota_fiscal=nota).update(nota_fiscal=existente)
            nota.delete()
        else:
            nota.obra = destino
            nota.save(update_fields=['obra', 'updated_at'])


def unificar_obras_duplicadas(apps, schema_editor):
    Obra = apps.get_model('obras', 'Obra')
    NotaFiscal = apps.get_model('obras', 'NotaFiscal')
    RetencaoNotaFiscal = apps.get_model('obras', 'RetencaoNotaFiscal')
    ImpostoNotaFiscal = apps.get_model('obras', 'ImpostoNotaFiscal')
    AditivoContrato = apps.get_model('obras', 'AditivoContrato')
    DespesaObra = apps.get_model('obras', 'DespesaObra')
    RetencaoTecnicaObra = apps.get_model('obras', 'RetencaoTecnicaObra')
    ContaPagar = apps.get_model('financeiro', 'ContaPagar')
    ContaReceber = apps.get_model('financeiro', 'ContaReceber')
    OrdemCompraGeral = apps.get_model('controles', 'OrdemCompraGeral')
    LocacaoEquipamento = apps.get_model('controles', 'LocacaoEquipamento')
    OrdemServicoLocacaoMaquina = apps.get_model('controles', 'OrdemServicoLocacaoMaquina')
    ContratoConcretagem = apps.get_model('controles', 'ContratoConcretagem')
    OrcamentoRadarObra = apps.get_model('controles', 'OrcamentoRadarObra')
    OrcamentoMedicao = apps.get_model('medicoes', 'OrcamentoMedicao')
    MedicaoEmpreiteiro = apps.get_model('medicoes', 'MedicaoEmpreiteiro')

    modelos_score = (NotaFiscal, AditivoContrato, DespesaObra, ContaPagar, ContaReceber)
    modelos_update = [
        ContaPagar,
        ContaReceber,
        DespesaObra,
        AditivoContrato,
        RetencaoTecnicaObra,
        OrdemCompraGeral,
        LocacaoEquipamento,
        OrdemServicoLocacaoMaquina,
        ContratoConcretagem,
        OrcamentoRadarObra,
        OrcamentoMedicao,
        MedicaoEmpreiteiro,
    ]

    for nomes_grupo in GRUPOS_OBRAS:
        alvos = {normalizar(nome) for nome in nomes_grupo}
        obras = [obra for obra in Obra.objects.all() if normalizar(obra.nome_obra) in alvos]
        if len(obras) <= 1:
            if obras and normalizar(obras[0].nome_obra) != normalizar(nomes_grupo[0]):
                obras[0].nome_obra = nomes_grupo[0]
                obras[0].save(update_fields=['nome_obra', 'updated_at'])
            continue

        destino = escolher_destino(obras, nomes_grupo, modelos_score)
        if not destino:
            continue

        for origem in obras:
            if origem.id == destino.id:
                continue

            for model in modelos_update:
                model.objects.filter(obra=origem).update(obra=destino)
            mover_notas_fiscais(origem, destino, NotaFiscal, RetencaoNotaFiscal, ImpostoNotaFiscal)
            origem.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0009_unifica_obras_duplicadas_credores'),
        ('controles', '0015_alter_notafiscalordemcomprageral_conta_pagar'),
        ('medicoes', '0002_medicaoconstrutora_desconto_adicional_percentual_and_more'),
    ]

    operations = [
        migrations.RunPython(unificar_obras_duplicadas, migrations.RunPython.noop),
    ]
