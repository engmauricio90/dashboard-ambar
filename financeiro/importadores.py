import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
import re
import unicodedata

from django.db import transaction

from obras.models import DespesaObra
from obras.models import Obra

from .models import CentroCusto, ContaPagar, Fornecedor


ORIGEM_SIENGE_CREDORES = 'sienge_credores'
ORIGEM_SIENGE_PAGOS = 'sienge_pagos'


OBRAS_POR_CODIGO_CENTRO = {
    '4': 'Orla de Ipanema',
    '6': 'Jardim das Extremosas',
    '7': 'Hulha Negra - Senar',
    '8': 'Casa Ramona E Patrick',
    '9': 'Casa Kj',
    '10': 'Condomínio Rithmo',
    '11': 'Orla Do Lami',
    '12': 'Escritório Ana Patrícia Orsi',
    '15': 'Parque Harmonia',
    '20': 'POS OBRA',
    '26': 'Contenções BR 116',
    '27': 'SUELO',
    '28': 'PHORBIS',
    '31': 'MC3 ENGENHARIA LTDA',
    '33': 'Orla do Guaiba - Trecho 3',
    '34': 'Rede de Esgoto Sapiranga (CORSAN)',
    '35': 'ORLA 1',
    '36': 'ORLA 1',
    '37': 'HERTZ',
    '38': 'CASA RA',
    '40': 'EMEI JOÃO DE BARRO',
    '41': 'EMEB DARCY BORGES DE CASTILHOS',
}


ALIASES_OBRAS = {
    'Orla de Ipanema': ['IPANEMA'],
    'Condomínio Rithmo': ['Condominio Rithmo'],
    'Orla Do Lami': ['LAMI'],
    'MC3 ENGENHARIA LTDA': ['MC3'],
    'Jardim das Extremosas': ['GARTEN HAUS'],
    'Rede de Esgoto Sapiranga (CORSAN)': ['Rede de Esgoto - CORSAN', 'CORSAN'],
    'ORLA 1': ['Orla 1 - Ambulantes', 'Orla 1 - Bares 1,2 e 3'],
    'EMEB DARCY BORGES DE CASTILHOS': ['EMEB DARCY BORGES', 'EMEB Darcy Borges de Castilhos'],
}


CENTROS_CUSTO_POR_CODIGO = {
    '14': 'Maquinas E Veículos',
    '16': 'Escritório Âmbar',
}


@dataclass
class ResultadoImportacaoCredores:
    criadas: int = 0
    atualizadas: int = 0
    ignoradas: int = 0
    obras_criadas: int = 0
    centros_criados: int = 0

    @property
    def total_processado(self):
        return self.criadas + self.atualizadas


def decodificar_csv_upload(arquivo):
    conteudo = arquivo.read()
    for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return conteudo.decode(encoding)
        except UnicodeDecodeError:
            continue
    return conteudo.decode('latin-1', errors='replace')


def garantir_cadastros_relatorio_credores():
    resultado = ResultadoImportacaoCredores()

    for nome in sorted(set(OBRAS_POR_CODIGO_CENTRO.values())):
        _, created = _get_or_create_obra_normalizada(nome)
        if created:
            resultado.obras_criadas += 1

    for nome in sorted(set(CENTROS_CUSTO_POR_CODIGO.values())):
        _, created = CentroCusto.objects.get_or_create(nome=nome)
        if created:
            resultado.centros_criados += 1

    return resultado


def importar_contas_pagar_credores_csv(conteudo):
    resultado = garantir_cadastros_relatorio_credores()
    centro_atual = None
    ultima_conta = None

    reader = csv.reader(StringIO(conteudo), delimiter=';')
    for row in reader:
        if not row or not any((coluna or '').strip() for coluna in row):
            continue

        primeira_coluna = (row[0] or '').strip()
        if primeira_coluna.startswith('Centro de Custo'):
            centro_atual = _parse_centro_custo(row[1] if len(row) > 1 else '')
            ultima_conta = None
            continue

        if primeira_coluna == 'Credor':
            continue

        if primeira_coluna.startswith('Obs:'):
            if ultima_conta:
                observacao = primeira_coluna.replace('Obs:', '', 1).strip()
                if observacao and observacao not in ultima_conta.observacoes:
                    ultima_conta.observacoes = (ultima_conta.observacoes.rstrip() + '\n' + observacao).strip()
                    ultima_conta.save(update_fields=['observacoes', 'updated_at'])
            continue

        if not centro_atual or len(row) < 12:
            resultado.ignoradas += 1
            continue

        try:
            ultima_conta, created = _importar_linha_conta(row, centro_atual)
        except (ValueError, InvalidOperation):
            resultado.ignoradas += 1
            ultima_conta = None
            continue

        if created:
            resultado.criadas += 1
        else:
            resultado.atualizadas += 1

    return resultado


def importar_contas_pagas_credores_csv(conteudo):
    resultado = garantir_cadastros_relatorio_credores()
    centro_atual = None
    linhas_validas = []

    reader = csv.reader(StringIO(conteudo), delimiter=';')
    for row in reader:
        if not row or not any((coluna or '').strip() for coluna in row):
            continue

        primeira_coluna = (row[0] or '').strip()
        if _is_linha_centro_custo(primeira_coluna):
            centro_atual = _parse_centro_custo(row[1] if len(row) > 1 else '')
            continue

        if primeira_coluna == 'Credor':
            continue

        if not centro_atual or len(row) < 11:
            resultado.ignoradas += 1
            continue

        try:
            linhas_validas.append(_preparar_linha_conta_paga(row, centro_atual))
        except (ValueError, InvalidOperation):
            resultado.ignoradas += 1
            continue

    codigos_criados = _criar_contas_pagas_em_lote(linhas_validas)
    resultado.criadas += len(codigos_criados)

    for codigo_externo, dados in linhas_validas:
        if codigo_externo in codigos_criados:
            continue
        updated = ContaPagar.objects.filter(
            origem_importacao=ORIGEM_SIENGE_PAGOS,
            codigo_externo=codigo_externo,
        ).update(**dados)
        if not updated:
            continue
        conta = ContaPagar.objects.get(
            origem_importacao=ORIGEM_SIENGE_PAGOS,
            codigo_externo=codigo_externo,
        )
        conta.sincronizar_obra()
        resultado.atualizadas += 1

    return resultado


def _criar_contas_pagas_em_lote(linhas_validas):
    if not linhas_validas:
        return 0

    codigos = [codigo for codigo, _ in linhas_validas]
    existentes = set(
        ContaPagar.objects.filter(
            origem_importacao=ORIGEM_SIENGE_PAGOS,
            codigo_externo__in=codigos,
        ).values_list('codigo_externo', flat=True)
    )
    novas_linhas = [(codigo, dados) for codigo, dados in linhas_validas if codigo not in existentes]
    if not novas_linhas:
        return set()

    contas = [
        ContaPagar(
            origem_importacao=ORIGEM_SIENGE_PAGOS,
            codigo_externo=codigo,
            **dados,
        )
        for codigo, dados in novas_linhas
    ]
    with transaction.atomic():
        contas_criadas = ContaPagar.objects.bulk_create(contas, batch_size=500)
        despesas = [
            DespesaObra(
                obra=conta.obra,
                data_referencia=conta.data_emissao,
                categoria=conta.categoria,
                descricao=conta.descricao,
                valor=conta.valor,
            )
            for conta in contas_criadas
            if conta.obra_id
        ]
        despesas_criadas = DespesaObra.objects.bulk_create(despesas, batch_size=500)
        despesa_index = 0
        contas_com_despesa = []
        for conta in contas_criadas:
            if not conta.obra_id:
                continue
            conta.despesa_obra = despesas_criadas[despesa_index]
            contas_com_despesa.append(conta)
            despesa_index += 1
        ContaPagar.objects.bulk_update(contas_com_despesa, ['despesa_obra'], batch_size=500)

    return {codigo for codigo, _ in novas_linhas}


def _importar_linha_conta_paga(row, centro_atual):
    codigo_externo, dados = _preparar_linha_conta_paga(row, centro_atual)
    return ContaPagar.objects.update_or_create(
        origem_importacao=ORIGEM_SIENGE_PAGOS,
        codigo_externo=codigo_externo,
        defaults=dados,
    )


def _preparar_linha_conta_paga(row, centro_atual):
    credor = row[0].strip()
    codigo_credor = row[1].strip()
    documento = row[2].strip()
    lancamento = row[3].strip()
    quantidade = row[4].strip()
    data_pagamento = _parse_data(row[5])
    sequencia = row[6].strip()
    valor_baixa = _parse_decimal(row[7])
    acrescimo = _parse_decimal(row[8])
    desconto = _parse_decimal(row[9])
    liquido = _parse_decimal(row[10])

    codigo = centro_atual['codigo']
    obra, centro_custo = _resolver_destino(codigo)
    fornecedor_cadastro, _ = Fornecedor.objects.get_or_create(nome=credor, cpf_cnpj='')
    codigo_externo = f'{codigo}:{lancamento}:{sequencia}:{documento}:{data_pagamento.isoformat()}'
    descricao = _limitar_texto(f'{documento or "Documento sem numero"} - lancamento {lancamento}', 255)
    observacoes = '\n'.join(
        [
            f'Importado do relatorio de contas pagas. Centro original: {centro_atual["original"]}.',
            f'Valor baixa: R$ {valor_baixa:.2f}. Acrescimo: R$ {acrescimo:.2f}. Desconto: R$ {desconto:.2f}.',
            f'Codigo credor: {codigo_credor}. Qt.: {quantidade}. Seq.: {sequencia}.',
        ]
    )

    return codigo_externo, {
        'fornecedor': credor,
        'fornecedor_cadastro': fornecedor_cadastro,
        'obra': obra,
        'centro_custo': centro_custo,
        'categoria': 'outra',
        'numero_nf': documento,
        'descricao': descricao,
        'data_emissao': data_pagamento,
        'data_vencimento': data_pagamento,
        'data_pagamento': data_pagamento,
        'valor': valor_baixa,
        'valor_pago': liquido,
        'status': ContaPagar.STATUS_PAGO,
        'observacoes': observacoes,
    }


def _importar_linha_conta(row, centro_atual):
    credor = row[0].strip()
    documento = row[1].strip()
    lancamento = row[2].strip()
    quantidade = row[3].strip()
    indice = row[4].strip()
    data_vencimento = _parse_data(row[5])
    percentual = row[6].strip()
    dias = row[7].strip()
    valor_vencimento = _parse_decimal(row[8])
    acrescimo = _parse_decimal(row[9])
    desconto = _parse_decimal(row[10])
    total = _parse_decimal(row[11])

    codigo = centro_atual['codigo']
    obra, centro_custo = _resolver_destino(codigo)
    fornecedor_cadastro, _ = Fornecedor.objects.get_or_create(nome=credor, cpf_cnpj='')
    codigo_externo = f'{codigo}:{lancamento}:{documento}:{data_vencimento.isoformat()}'
    descricao = _limitar_texto(f'{documento or "Documento sem numero"} - lancamento {lancamento}', 255)
    observacoes = '\n'.join(
        [
            f'Importado do relatorio de credores. Centro original: {centro_atual["original"]}.',
            f'Valor no vencimento: R$ {valor_vencimento:.2f}. Acrescimo: R$ {acrescimo:.2f}. Desconto: R$ {desconto:.2f}.',
            f'Qt.: {quantidade}. Ind.: {indice}. Percentual: {percentual}%. Dias: {dias}.',
        ]
    )

    dados = {
        'fornecedor': credor,
        'fornecedor_cadastro': fornecedor_cadastro,
        'obra': obra,
        'centro_custo': centro_custo,
        'categoria': 'outra',
        'numero_nf': documento,
        'descricao': descricao,
        'data_emissao': data_vencimento,
        'data_vencimento': data_vencimento,
        'valor': total,
        'observacoes': observacoes,
    }

    conta, created = ContaPagar.objects.get_or_create(
        origem_importacao=ORIGEM_SIENGE_CREDORES,
        codigo_externo=codigo_externo,
        defaults={**dados, 'status': ContaPagar.STATUS_ABERTO},
    )
    if not created:
        for field, value in dados.items():
            setattr(conta, field, value)
        conta.save()
    return conta, created


def _resolver_destino(codigo):
    if codigo in CENTROS_CUSTO_POR_CODIGO:
        centro, _ = CentroCusto.objects.get_or_create(nome=CENTROS_CUSTO_POR_CODIGO[codigo])
        return None, centro

    nome_obra = OBRAS_POR_CODIGO_CENTRO.get(codigo)
    if not nome_obra:
        raise ValueError(f'Centro de custo nao mapeado: {codigo}')

    obra, _ = _get_or_create_obra_normalizada(nome_obra)
    return obra, None


def _get_or_create_obra_normalizada(nome):
    existente = _buscar_obra_normalizada(nome)
    if existente:
        return existente, False
    return Obra.objects.get_or_create(nome_obra=nome)


def _buscar_obra_normalizada(nome):
    alvo_canonico = _normalizar(nome)
    for obra in Obra.objects.all():
        if _normalizar(obra.nome_obra) == alvo_canonico:
            return obra

    alvos = {_normalizar(nome_possivel) for nome_possivel in ALIASES_OBRAS.get(nome, [])}
    for obra in Obra.objects.all():
        if _normalizar(obra.nome_obra) in alvos:
            obra.nome_obra = nome
            obra.save(update_fields=['nome_obra', 'updated_at'])
            return obra
    return None


def _parse_centro_custo(valor):
    original = (valor or '').strip()
    match = re.match(r'(?P<codigo>\d+)\s*-\s*(?P<nome>.*)', original)
    if not match:
        raise ValueError(f'Centro de custo invalido: {original}')
    return {
        'codigo': match.group('codigo').strip(),
        'nome': match.group('nome').strip(),
        'original': original,
    }


def _is_linha_centro_custo(valor):
    return _normalizar(valor).startswith('centro de custo')


def _parse_data(valor):
    return datetime.strptime((valor or '').strip(), '%d/%m/%Y').date()


def _parse_decimal(valor):
    texto = (valor or '0').strip().replace('T', '').replace('.', '').replace(',', '.')
    return Decimal(texto or '0')


def _normalizar(valor):
    sem_acento = unicodedata.normalize('NFKD', valor or '').encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', sem_acento).strip().casefold()


def _limitar_texto(valor, tamanho):
    return valor[:tamanho]
