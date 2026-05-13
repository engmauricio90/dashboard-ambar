from decimal import Decimal

from django.db import transaction

from obras.models import DespesaObra, NotaFiscal, RetencaoNotaFiscal, RetencaoTecnicaObra


def _valor(value):
    return value or Decimal('0')


def sincronizar_conta_receber_obra(conta):
    if not conta.obra or not conta.numero_nf:
        remover_vinculos_conta_receber_obra(conta)
        return

    status_nf = NotaFiscal.STATUS_CANCELADA if conta.status == conta.STATUS_CANCELADO else NotaFiscal.STATUS_EMITIDA
    if conta.status == conta.STATUS_RECEBIDO:
        status_nf = NotaFiscal.STATUS_RECEBIDA

    nota, _ = NotaFiscal.objects.update_or_create(
        obra=conta.obra,
        numero=conta.numero_nf,
        defaults={
            'data_emissao': conta.data_emissao,
            'valor_bruto': conta.valor_bruto,
            'status': status_nf,
            'observacoes': conta.observacoes or f'Gerada pelo financeiro: {conta.descricao}',
        },
    )

    updates = {}
    if conta.nota_fiscal_id != nota.id:
        updates['nota_fiscal'] = nota

    sincronizar_retencao_nf(nota, RetencaoNotaFiscal.TIPO_ISS, 'ISSQN retido', conta.issqn_retido)
    sincronizar_retencao_nf(nota, RetencaoNotaFiscal.TIPO_INSS, 'INSS retido', conta.inss_retido)
    sincronizar_retencao_nf(nota, RetencaoNotaFiscal.TIPO_OUTRA, 'Outras retencoes', conta.outras_retencoes)

    retencao_tecnica = sincronizar_retencao_tecnica(conta)
    if conta.retencao_tecnica_obra_id != getattr(retencao_tecnica, 'id', None):
        updates['retencao_tecnica_obra'] = retencao_tecnica

    if updates:
        conta.__class__.objects.filter(pk=conta.pk).update(**updates)
        for field, value in updates.items():
            setattr(conta, field, value)


def remover_vinculos_conta_receber_obra(conta):
    updates = {}
    if conta.nota_fiscal_id:
        nota = conta.nota_fiscal
        nota.status = NotaFiscal.STATUS_CANCELADA
        nota.save(update_fields=['status', 'updated_at'])
        updates['nota_fiscal'] = None

    if conta.retencao_tecnica_obra_id:
        conta.retencao_tecnica_obra.delete()
        updates['retencao_tecnica_obra'] = None

    if updates:
        conta.__class__.objects.filter(pk=conta.pk).update(**updates)
        for field, value in updates.items():
            setattr(conta, field, value)


def sincronizar_retencao_nf(nota, tipo, descricao, valor):
    valor = _valor(valor)
    existente = nota.retencoes.filter(tipo=tipo, descricao=descricao).first()
    if valor <= 0:
        if existente:
            existente.delete()
        return
    RetencaoNotaFiscal.objects.update_or_create(
        nota_fiscal=nota,
        tipo=tipo,
        descricao=descricao,
        defaults={'valor': valor},
    )


def sincronizar_retencao_tecnica(conta):
    if conta.status == conta.STATUS_CANCELADO:
        if conta.retencao_tecnica_obra_id:
            conta.retencao_tecnica_obra.delete()
        return None

    valor = _valor(conta.retencao_tecnica)
    if valor <= 0:
        if conta.retencao_tecnica_obra_id:
            conta.retencao_tecnica_obra.delete()
        return None

    if conta.retencao_tecnica_obra_id:
        retencao = conta.retencao_tecnica_obra
        retencao.obra = conta.obra
        retencao.tipo = RetencaoTecnicaObra.TIPO_RETENCAO
        retencao.data_referencia = conta.data_emissao
        retencao.descricao = f'Retencao tecnica NF {conta.numero_nf}'
        retencao.valor = valor
        retencao.save()
        return retencao

    return RetencaoTecnicaObra.objects.create(
        obra=conta.obra,
        tipo=RetencaoTecnicaObra.TIPO_RETENCAO,
        data_referencia=conta.data_emissao,
        descricao=f'Retencao tecnica NF {conta.numero_nf}',
        valor=valor,
    )


def sincronizar_conta_pagar_obra(conta):
    if conta.status == conta.STATUS_CANCELADO:
        if conta.despesa_obra_id:
            conta.despesa_obra.delete()
            conta.__class__.objects.filter(pk=conta.pk).update(despesa_obra=None)
            conta.despesa_obra = None
        return

    if not conta.obra:
        if conta.despesa_obra_id:
            conta.despesa_obra.delete()
            conta.__class__.objects.filter(pk=conta.pk).update(despesa_obra=None)
            conta.despesa_obra = None
        return

    valor_despesa = conta.valor_pago_efetivo
    if conta.despesa_obra_id:
        despesa = conta.despesa_obra
        despesa.obra = conta.obra
        despesa.data_referencia = conta.data_emissao
        despesa.categoria = conta.categoria
        despesa.descricao = conta.descricao
        despesa.valor = valor_despesa
        despesa.save()
        return

    despesa = DespesaObra.objects.create(
        obra=conta.obra,
        data_referencia=conta.data_emissao,
        categoria=conta.categoria,
        descricao=conta.descricao,
        valor=valor_despesa,
    )
    conta.__class__.objects.filter(pk=conta.pk).update(despesa_obra=despesa)
    conta.despesa_obra = despesa


def sincronizar_conta_pagar_ordem_compra(conta):
    from controles.models import NotaFiscalOrdemCompraGeral

    if conta.status == conta.STATUS_CANCELADO:
        conta.notas_ordem_compra.update(status=NotaFiscalOrdemCompraGeral.STATUS_CANCELADA)
        return

    if not conta.ordem_compra_id or not conta.numero_nf:
        conta.notas_ordem_compra.all().delete()
        return

    itens = list(conta.itens_ordem_compra.select_related('item_ordem_compra'))
    if not itens and conta.item_ordem_compra_id and conta.quantidade_oc:
        itens = [
            conta.itens_ordem_compra.model(
                conta=conta,
                item_ordem_compra=conta.item_ordem_compra,
                quantidade=conta.quantidade_oc,
            )
        ]

    item_ids = [item.item_ordem_compra_id for item in itens if item.item_ordem_compra_id]
    conta.notas_ordem_compra.exclude(item_id__in=item_ids).delete()
    for item_conta in itens:
        item_oc = item_conta.item_ordem_compra
        if not item_oc:
            continue
        NotaFiscalOrdemCompraGeral.objects.update_or_create(
            conta_pagar=conta,
            item=item_oc,
            defaults={
                'ordem': conta.ordem_compra,
                'numero': conta.numero_nf,
                'data_emissao': conta.data_emissao,
                'data_vencimento': conta.data_vencimento,
                'quantidade': item_conta.quantidade,
                'valor_unitario': item_oc.valor_unitario,
                'valor_total': item_conta.valor_total,
                'status': NotaFiscalOrdemCompraGeral.STATUS_LANCADA_FINANCEIRO,
                'observacoes': conta.observacoes,
            },
        )


def recalcular_valor_conta_pagar_por_itens_oc(conta):
    if not conta.ordem_compra_id:
        return
    total = sum((item.valor_total for item in conta.itens_ordem_compra.select_related('item_ordem_compra')), Decimal('0'))
    conta.valor = total
    if conta.status == conta.STATUS_PAGO and not conta.valor_pago:
        conta.valor_pago = total


@transaction.atomic
def baixar_conta_pagar(conta, data_pagamento=None, valor_pago=None):
    conta.status = conta.STATUS_PAGO
    conta.data_pagamento = data_pagamento or conta.data_pagamento
    if valor_pago is not None:
        conta.valor_pago = valor_pago
    elif not conta.valor_pago:
        conta.valor_pago = conta.valor
    conta.save()
    return conta


@transaction.atomic
def baixar_conta_receber(conta, data_recebimento=None):
    conta.status = conta.STATUS_RECEBIDO
    conta.data_recebimento = data_recebimento or conta.data_recebimento
    conta.save()
    return conta
