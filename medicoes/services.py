from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, IntegerField, OuterRef, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce

from .models import (
    FaturamentoDiretoMedicao,
    ItemMedicaoConstrutora,
    ItemMedicaoEmpreiteiro,
    ItemOrcamentoMedicao,
    MedicaoConstrutora,
    MedicaoEmpreiteiro,
)


ZERO = Decimal('0')


def _sum_decimal(values):
    return sum(values, ZERO)


def _percent_decimal(base, percent):
    if not percent:
        return None
    return (base * percent / Decimal('100')).quantize(Decimal('0.01'))


@dataclass(frozen=True)
class ResumoMedicaoConstrutora:
    subtotal_periodo: Decimal
    total_material_periodo: Decimal
    total_mao_obra_periodo: Decimal
    total_equipamentos_periodo: Decimal
    total_faturamento_direto: Decimal
    base_impostos: Decimal
    fator_componentes_nf: Decimal
    valor_material_nf: Decimal
    valor_mao_obra_nf: Decimal
    valor_equipamentos_nf: Decimal
    base_inss: Decimal
    retencao_tecnica_calculada: Decimal
    issqn_calculado: Decimal
    inss_calculado: Decimal
    desconto_adicional_calculado: Decimal
    total_descontos: Decimal
    total_liquido: Decimal


@dataclass(frozen=True)
class ResumoMedicaoEmpreiteiro:
    subtotal_periodo: Decimal
    total_descontos: Decimal
    total_liquido: Decimal


def acumulados_construtora(medicao):
    rows = (
        ItemMedicaoConstrutora.objects.filter(
            medicao__orcamento=medicao.orcamento,
            medicao__numero__lt=medicao.numero,
        )
        .exclude(medicao=medicao)
        .values('item_orcamento_id')
        .annotate(total=Sum('quantidade_periodo'))
    )
    return {row['item_orcamento_id']: row['total'] or ZERO for row in rows}


def acumulados_empreiteiro(medicao):
    if not medicao.orcamento_id:
        return {}
    rows = (
        ItemMedicaoEmpreiteiro.objects.filter(
            medicao__orcamento=medicao.orcamento,
            medicao__numero__lt=medicao.numero,
            item_orcamento_id__isnull=False,
        )
        .exclude(medicao=medicao)
        .values('item_orcamento_id')
        .annotate(total=Sum('quantidade_periodo'))
    )
    return {row['item_orcamento_id']: row['total'] or ZERO for row in rows}


def aplicar_acumulados_itens(itens, acumulados):
    for item in itens:
        item_id = getattr(item, 'item_orcamento_id', None)
        if item_id:
            item._quantidade_acumulada_anterior_cache = acumulados.get(item_id, ZERO)
    return itens


def itens_construtora_com_grupos(medicao):
    acumulados = acumulados_construtora(medicao)
    itens_medicao = {
        item.item_orcamento_id: item
        for item in medicao.itens.select_related('item_orcamento')
    }
    aplicar_acumulados_itens(itens_medicao.values(), acumulados)
    linhas = []
    for item_orcamento in medicao.orcamento.itens.all():
        if item_orcamento.eh_grupo:
            linhas.append(item_orcamento)
        elif item_orcamento.id in itens_medicao:
            linhas.append(itens_medicao[item_orcamento.id])
    return linhas, acumulados


def itens_empreiteiro_com_acumulados(medicao):
    itens = list(medicao.itens.select_related('item_orcamento'))
    aplicar_acumulados_itens(itens, acumulados_empreiteiro(medicao))
    return itens


def calcular_resumo_construtora(medicao, itens=None, faturamentos=None):
    if itens is None:
        itens = list(medicao.itens.select_related('item_orcamento'))
    else:
        itens = [item for item in itens if isinstance(item, ItemMedicaoConstrutora)]
    if faturamentos is None:
        faturamentos = list(medicao.faturamentos_diretos.select_related('faturamento_direto'))

    subtotal = _sum_decimal(item.valor_periodo for item in itens)
    material = _sum_decimal(item.valor_material_periodo for item in itens)
    mao_obra = _sum_decimal(item.valor_mao_obra_periodo for item in itens)
    equipamentos = _sum_decimal(item.valor_equipamentos_periodo for item in itens)
    faturamento_direto = _sum_decimal(v.valor_descontado for v in faturamentos) or medicao.valor_faturamento_direto
    desconto_adicional = _percent_decimal(subtotal, medicao.desconto_adicional_percentual) or medicao.desconto_adicional
    desconto_base = desconto_adicional if medicao.desconto_adicional_reduz_base_nf else ZERO
    base_impostos = max(subtotal - faturamento_direto - desconto_base, ZERO)
    fator_componentes_nf = base_impostos / subtotal if subtotal else ZERO
    valor_material_nf = (material * fator_componentes_nf).quantize(Decimal('0.01'))
    valor_equipamentos_nf = (equipamentos * fator_componentes_nf).quantize(Decimal('0.01'))
    valor_mao_obra_nf = max(base_impostos - valor_material_nf - valor_equipamentos_nf, ZERO).quantize(Decimal('0.01'))
    base_inss = mao_obra
    if medicao.desconto_adicional_reduz_base_nf and subtotal:
        desconto = min(desconto_adicional, subtotal)
        base_inss = mao_obra * ((subtotal - desconto) / subtotal)
    base_inss = max(base_inss, ZERO).quantize(Decimal('0.01'))
    retencao = _percent_decimal(subtotal, medicao.retencao_tecnica_percentual) or medicao.retencao_tecnica
    issqn = _percent_decimal(base_impostos, medicao.issqn_percentual) or medicao.issqn
    inss = _percent_decimal(base_inss, medicao.inss_percentual) or medicao.inss
    total_descontos = retencao + issqn + inss + desconto_adicional + faturamento_direto
    resumo = ResumoMedicaoConstrutora(
        subtotal_periodo=subtotal,
        total_material_periodo=material,
        total_mao_obra_periodo=mao_obra,
        total_equipamentos_periodo=equipamentos,
        total_faturamento_direto=faturamento_direto,
        base_impostos=base_impostos,
        fator_componentes_nf=fator_componentes_nf,
        valor_material_nf=valor_material_nf,
        valor_mao_obra_nf=valor_mao_obra_nf,
        valor_equipamentos_nf=valor_equipamentos_nf,
        base_inss=base_inss,
        retencao_tecnica_calculada=retencao,
        issqn_calculado=issqn,
        inss_calculado=inss,
        desconto_adicional_calculado=desconto_adicional,
        total_descontos=total_descontos,
        total_liquido=subtotal - total_descontos,
    )
    medicao._resumo_construtora_cache = resumo
    return resumo


def calcular_resumo_empreiteiro(medicao, itens=None):
    if itens is None:
        itens = list(medicao.itens.all())
    subtotal = _sum_decimal(item.valor_periodo for item in itens)
    total_descontos = medicao.retencao_tecnica + medicao.desconto_adicional
    resumo = ResumoMedicaoEmpreiteiro(
        subtotal_periodo=subtotal,
        total_descontos=total_descontos,
        total_liquido=subtotal - total_descontos,
    )
    medicao._resumo_empreiteiro_cache = resumo
    return resumo


def percentuais_orcamentos_construtora(orcamento_ids):
    return _percentuais_orcamentos(
        orcamento_ids,
        ItemMedicaoConstrutora,
        'medicao__orcamento_id',
    )


def percentuais_orcamentos_empreiteiro(orcamento_ids):
    return _percentuais_orcamentos(
        orcamento_ids,
        ItemMedicaoEmpreiteiro,
        'medicao__orcamento_id',
    )


def anotar_resumo_planilhas_construtora(qs):
    decimal_field = DecimalField(max_digits=20, decimal_places=4)
    integer_field = IntegerField()
    item_total_expr = ExpressionWrapper(
        F('quantidade')
        * (
            F('preco_unitario_material')
            + F('preco_unitario_mao_obra')
            + F('preco_unitario_equipamentos')
        ),
        output_field=decimal_field,
    )
    contrato_subquery = (
        ItemOrcamentoMedicao.objects.filter(
            orcamento_id=OuterRef('pk'),
            tipo=ItemOrcamentoMedicao.TIPO_ITEM,
        )
        .annotate(valor_total=item_total_expr)
        .values('orcamento_id')
        .annotate(total=Sum('valor_total'))
        .values('total')[:1]
    )
    medido_expr = ExpressionWrapper(
        F('quantidade_periodo')
        * (
            F('item_orcamento__preco_unitario_material')
            + F('item_orcamento__preco_unitario_mao_obra')
            + F('item_orcamento__preco_unitario_equipamentos')
        ),
        output_field=decimal_field,
    )
    medido_subquery = (
        ItemMedicaoConstrutora.objects.filter(
            medicao__orcamento_id=OuterRef('pk'),
            item_orcamento__tipo=ItemOrcamentoMedicao.TIPO_ITEM,
        )
        .annotate(valor_medido=medido_expr)
        .values('medicao__orcamento_id')
        .annotate(total=Sum('valor_medido'))
        .values('total')[:1]
    )
    medicoes_count_subquery = (
        MedicaoConstrutora.objects.filter(orcamento_id=OuterRef('pk'))
        .values('orcamento_id')
        .annotate(total=Count('id'))
        .values('total')[:1]
    )
    qs = qs.annotate(
        total_contrato_otimizado=Coalesce(Subquery(contrato_subquery, output_field=decimal_field), Value(ZERO), output_field=decimal_field),
        total_medido_otimizado=Coalesce(Subquery(medido_subquery, output_field=decimal_field), Value(ZERO), output_field=decimal_field),
        quantidade_medicoes=Coalesce(Subquery(medicoes_count_subquery, output_field=integer_field), Value(0), output_field=integer_field),
    )
    saldo_expr = ExpressionWrapper(
        F('total_contrato_otimizado') - F('total_medido_otimizado'),
        output_field=decimal_field,
    )
    percentual_expr = ExpressionWrapper(
        F('total_medido_otimizado') * Value(Decimal('100.0000'), output_field=decimal_field) / F('total_contrato_otimizado'),
        output_field=decimal_field,
    )
    return qs.annotate(
        saldo_otimizado=saldo_expr,
        percentual_medido_otimizado=Case(
            When(total_contrato_otimizado=ZERO, then=Value(ZERO)),
            default=percentual_expr,
            output_field=decimal_field,
        ),
    )


def anotar_resumo_medicoes_construtora(qs):
    decimal_field = DecimalField(max_digits=20, decimal_places=4)
    item_subtotal_expr = ExpressionWrapper(
        F('quantidade_periodo')
        * (
            F('item_orcamento__preco_unitario_material')
            + F('item_orcamento__preco_unitario_mao_obra')
            + F('item_orcamento__preco_unitario_equipamentos')
        ),
        output_field=decimal_field,
    )
    item_mao_obra_expr = ExpressionWrapper(
        F('quantidade_periodo') * F('item_orcamento__preco_unitario_mao_obra'),
        output_field=decimal_field,
    )
    subtotal_subquery = (
        ItemMedicaoConstrutora.objects.filter(
            medicao_id=OuterRef('pk'),
            item_orcamento__tipo=ItemOrcamentoMedicao.TIPO_ITEM,
        )
        .annotate(valor=item_subtotal_expr)
        .values('medicao_id')
        .annotate(total=Sum('valor'))
        .values('total')[:1]
    )
    mao_obra_subquery = (
        ItemMedicaoConstrutora.objects.filter(
            medicao_id=OuterRef('pk'),
            item_orcamento__tipo=ItemOrcamentoMedicao.TIPO_ITEM,
        )
        .annotate(valor=item_mao_obra_expr)
        .values('medicao_id')
        .annotate(total=Sum('valor'))
        .values('total')[:1]
    )
    faturamento_subquery = (
        FaturamentoDiretoMedicao.objects.filter(medicao_id=OuterRef('pk'))
        .values('medicao_id')
        .annotate(total=Sum('valor_descontado'))
        .values('total')[:1]
    )
    qs = qs.annotate(
        subtotal_otimizado=Coalesce(Subquery(subtotal_subquery, output_field=decimal_field), Value(ZERO), output_field=decimal_field),
        total_mao_obra_otimizado=Coalesce(Subquery(mao_obra_subquery, output_field=decimal_field), Value(ZERO), output_field=decimal_field),
        faturamento_vinculado_otimizado=Coalesce(Subquery(faturamento_subquery, output_field=decimal_field), Value(ZERO), output_field=decimal_field),
    ).annotate(
        faturamento_direto_otimizado=Case(
            When(faturamento_vinculado_otimizado__gt=ZERO, then=F('faturamento_vinculado_otimizado')),
            default=F('valor_faturamento_direto'),
            output_field=decimal_field,
        ),
        desconto_adicional_otimizado=Case(
            When(
                desconto_adicional_percentual__gt=ZERO,
                then=ExpressionWrapper(
                    F('subtotal_otimizado') * F('desconto_adicional_percentual') * Value(Decimal('0.0100'), output_field=decimal_field),
                    output_field=decimal_field,
                ),
            ),
            default=F('desconto_adicional'),
            output_field=decimal_field,
        ),
        retencao_tecnica_otimizada=Case(
            When(
                retencao_tecnica_percentual__gt=ZERO,
                then=ExpressionWrapper(
                    F('subtotal_otimizado') * F('retencao_tecnica_percentual') * Value(Decimal('0.0100'), output_field=decimal_field),
                    output_field=decimal_field,
                ),
            ),
            default=F('retencao_tecnica'),
            output_field=decimal_field,
        ),
    ).annotate(
        desconto_base_nf_otimizado=Case(
            When(desconto_adicional_reduz_base_nf=True, then=F('desconto_adicional_otimizado')),
            default=Value(ZERO),
            output_field=decimal_field,
        ),
        desconto_inss_otimizado=Case(
            When(desconto_adicional_otimizado__gt=F('subtotal_otimizado'), then=F('subtotal_otimizado')),
            default=F('desconto_adicional_otimizado'),
            output_field=decimal_field,
        ),
    ).annotate(
        base_impostos_raw_otimizada=ExpressionWrapper(
            F('subtotal_otimizado') - F('faturamento_direto_otimizado') - F('desconto_base_nf_otimizado'),
            output_field=decimal_field,
        ),
        base_inss_raw_otimizada=Case(
            When(
                desconto_adicional_reduz_base_nf=True,
                subtotal_otimizado__gt=ZERO,
                then=ExpressionWrapper(
                    F('total_mao_obra_otimizado')
                    * (F('subtotal_otimizado') - F('desconto_inss_otimizado'))
                    / F('subtotal_otimizado'),
                    output_field=decimal_field,
                ),
            ),
            default=F('total_mao_obra_otimizado'),
            output_field=decimal_field,
        ),
    ).annotate(
        base_impostos_otimizada=Case(
            When(base_impostos_raw_otimizada__lt=ZERO, then=Value(ZERO)),
            default=F('base_impostos_raw_otimizada'),
            output_field=decimal_field,
        ),
        base_inss_otimizada=Case(
            When(base_inss_raw_otimizada__lt=ZERO, then=Value(ZERO)),
            default=F('base_inss_raw_otimizada'),
            output_field=decimal_field,
        ),
    ).annotate(
        issqn_otimizado=Case(
            When(
                issqn_percentual__gt=ZERO,
                then=ExpressionWrapper(
                    F('base_impostos_otimizada') * F('issqn_percentual') * Value(Decimal('0.0100'), output_field=decimal_field),
                    output_field=decimal_field,
                ),
            ),
            default=F('issqn'),
            output_field=decimal_field,
        ),
        inss_otimizado=Case(
            When(
                inss_percentual__gt=ZERO,
                then=ExpressionWrapper(
                    F('base_inss_otimizada') * F('inss_percentual') * Value(Decimal('0.0100'), output_field=decimal_field),
                    output_field=decimal_field,
                ),
            ),
            default=F('inss'),
            output_field=decimal_field,
        ),
    ).annotate(
        impostos_otimizados=ExpressionWrapper(F('issqn_otimizado') + F('inss_otimizado'), output_field=decimal_field),
        total_liquido_otimizado=ExpressionWrapper(
            F('subtotal_otimizado')
            - F('faturamento_direto_otimizado')
            - F('desconto_adicional_otimizado')
            - F('retencao_tecnica_otimizada')
            - F('issqn_otimizado')
            - F('inss_otimizado'),
            output_field=decimal_field,
        ),
    )
    return qs


def anotar_resumo_medicoes_contratados(qs):
    decimal_field = DecimalField(max_digits=20, decimal_places=4)
    item_subtotal_expr = ExpressionWrapper(
        F('quantidade_periodo') * F('valor_unitario'),
        output_field=decimal_field,
    )
    subtotal_subquery = (
        ItemMedicaoEmpreiteiro.objects.filter(medicao_id=OuterRef('pk'))
        .annotate(valor=item_subtotal_expr)
        .values('medicao_id')
        .annotate(total=Sum('valor'))
        .values('total')[:1]
    )
    qs = qs.annotate(
        subtotal_otimizado=Coalesce(Subquery(subtotal_subquery, output_field=decimal_field), Value(ZERO), output_field=decimal_field),
    ).annotate(
        total_descontos_otimizado=ExpressionWrapper(
            F('retencao_tecnica') + F('desconto_adicional'),
            output_field=decimal_field,
        ),
        total_liquido_otimizado=ExpressionWrapper(
            F('subtotal_otimizado') - F('retencao_tecnica') - F('desconto_adicional'),
            output_field=decimal_field,
        ),
    )
    return qs


def _percentuais_orcamentos(orcamento_ids, item_model, medicao_group_field):
    ids = {orcamento_id for orcamento_id in orcamento_ids if orcamento_id}
    if not ids:
        return {}

    item_total_expr = ExpressionWrapper(
        F('quantidade')
        * (
            F('preco_unitario_material')
            + F('preco_unitario_mao_obra')
            + F('preco_unitario_equipamentos')
        ),
        output_field=DecimalField(max_digits=20, decimal_places=4),
    )
    totais_orcamento = {
        row['orcamento_id']: row['total'] or ZERO
        for row in ItemOrcamentoMedicao.objects.filter(
            orcamento_id__in=ids,
            tipo=ItemOrcamentoMedicao.TIPO_ITEM,
        )
        .annotate(valor_total=item_total_expr)
        .values('orcamento_id')
        .annotate(total=Sum('valor_total'))
    }

    if item_model is ItemMedicaoConstrutora:
        valor_medido_expr = ExpressionWrapper(
            F('quantidade_periodo')
            * (
                F('item_orcamento__preco_unitario_material')
                + F('item_orcamento__preco_unitario_mao_obra')
                + F('item_orcamento__preco_unitario_equipamentos')
            ),
            output_field=DecimalField(max_digits=20, decimal_places=4),
        )
    else:
        valor_medido_expr = ExpressionWrapper(
            F('quantidade_periodo') * F('valor_unitario'),
            output_field=DecimalField(max_digits=20, decimal_places=4),
        )
    totais_medidos = {
        row[medicao_group_field]: row['total'] or ZERO
        for row in item_model.objects.filter(**{f'{medicao_group_field}__in': ids})
        .annotate(valor_medido=valor_medido_expr)
        .values(medicao_group_field)
        .annotate(total=Sum('valor_medido'))
    }

    percentuais = {}
    for orcamento_id in ids:
        total = totais_orcamento.get(orcamento_id, ZERO)
        if not total:
            percentuais[orcamento_id] = ZERO
            continue
        percentuais[orcamento_id] = (
            totais_medidos.get(orcamento_id, ZERO) * Decimal('100') / total
        ).quantize(Decimal('0.01'))
    return percentuais


def faturamentos_diretos_linhas(medicao):
    faturamentos = list(
        medicao.orcamento.obra.faturamentos_diretos.prefetch_related('vinculos_medicao').order_by('data_lancamento', 'id')
    )
    linhas = []
    for faturamento in faturamentos:
        vinculos = list(faturamento.vinculos_medicao.all())
        vinculo_atual = next((v for v in vinculos if v.medicao_id == medicao.id), None)
        percentual_atual = vinculo_atual.percentual_descontado if vinculo_atual else ZERO
        percentual_outros = _sum_decimal(
            v.percentual_descontado for v in vinculos if v.medicao_id != medicao.id
        )
        saldo_percentual = max(Decimal('100') - percentual_outros, ZERO)
        if saldo_percentual <= 0 and not vinculo_atual:
            continue
        linhas.append(
            {
                'faturamento': faturamento,
                'percentual_atual': percentual_atual,
                'percentual_outros': percentual_outros,
                'saldo_percentual': saldo_percentual,
                'valor_atual': vinculo_atual.valor_descontado if vinculo_atual else ZERO,
            }
        )
    return linhas


def faturamentos_vinculados(medicao):
    return list(
        FaturamentoDiretoMedicao.objects.filter(medicao=medicao)
        .select_related('faturamento_direto')
        .order_by('faturamento_direto__data_lancamento', 'id')
    )
