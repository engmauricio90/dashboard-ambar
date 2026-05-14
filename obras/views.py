from collections import defaultdict
from decimal import Decimal
from itertools import chain
from operator import itemgetter

from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    AditivoContratoForm,
    DespesaObraForm,
    ImpostoNotaFiscalForm,
    ImpostoNotaFiscalFormSet,
    NotaFiscalForm,
    ObraForm,
    RelatorioObraFiltroForm,
    RetencaoTecnicaObraForm,
    RetencaoNotaFiscalForm,
    RetencaoNotaFiscalFormSet,
)
from .models import (
    AditivoContrato,
    DespesaObra,
    ImpostoNotaFiscal,
    NotaFiscal,
    Obra,
    RetencaoTecnicaObra,
    RetencaoNotaFiscal,
)


def _obra_base_queryset():
    notas_queryset = NotaFiscal.objects.prefetch_related('retencoes', 'impostos').order_by('-data_emissao', '-id')
    return Obra.objects.prefetch_related(
        'aditivos_registrados',
        'despesas_registradas',
        'faturamentos_diretos',
        'retencoes_tecnicas_registradas',
        Prefetch('notas_fiscais', queryset=notas_queryset),
    )


def _build_nota_formsets(data=None, instance=None):
    return (
        RetencaoNotaFiscalFormSet(data=data, instance=instance, prefix='retencoes'),
        ImpostoNotaFiscalFormSet(data=data, instance=instance, prefix='impostos'),
    )


def _save_inline_formset(formset, fk_name):
    for form in formset.forms:
        if not getattr(form, 'cleaned_data', None):
            continue
        if form.cleaned_data.get('DELETE'):
            if form.instance.pk:
                form.instance.delete()
            continue

        if not any(form.cleaned_data.get(field) not in (None, '') for field in ('tipo', 'descricao', 'valor')):
            continue

        instance = form.save(commit=False)
        setattr(instance, fk_name, formset.instance)
        instance.save()


def lista_obras(request):
    obras = _obra_base_queryset().order_by('nome_obra')
    return render(request, 'obras/lista_obras.html', {'obras': obras})


def nova_obra(request):
    if request.method == 'POST':
        form = ObraForm(request.POST)
        if form.is_valid():
            obra = form.save()
            messages.success(request, 'Obra cadastrada com sucesso.')
            return redirect('detalhe_obra', obra_id=obra.id)
    else:
        form = ObraForm()

    return render(request, 'obras/form_obra.html', {'form': form, 'titulo': 'Nova Obra'})


def editar_obra(request, obra_id):
    obra = get_object_or_404(Obra, id=obra_id)

    if request.method == 'POST':
        form = ObraForm(request.POST, instance=obra)
        if form.is_valid():
            form.save()
            messages.success(request, 'Dados da obra atualizados com sucesso.')
            return redirect('detalhe_obra', obra_id=obra.id)
    else:
        form = ObraForm(instance=obra)

    return render(request, 'obras/form_obra.html', {'form': form, 'titulo': 'Editar Obra', 'obra': obra})


def detalhe_obra(request, obra_id):
    obra = get_object_or_404(_obra_base_queryset(), id=obra_id)

    timeline = defaultdict(lambda: {'faturado': 0, 'despesas': 0, 'aditivos': 0})

    for nota in obra.notas_fiscais.all():
        if nota.status == NotaFiscal.STATUS_CANCELADA:
            continue
        chave = nota.data_emissao.strftime('%Y-%m')
        timeline[chave]['faturado'] += float(nota.valor_bruto)

    for despesa in obra.despesas_registradas.all():
        chave = despesa.data_referencia.strftime('%Y-%m')
        timeline[chave]['despesas'] += float(despesa.valor)

    for aditivo in obra.aditivos_registrados.all():
        chave = aditivo.data_referencia.strftime('%Y-%m')
        fator = 1 if aditivo.tipo == AditivoContrato.TIPO_ADITIVO else -1
        timeline[chave]['aditivos'] += float(aditivo.valor) * fator

    timeline_labels = sorted(timeline.keys())
    timeline_faturado = [timeline[label]['faturado'] for label in timeline_labels]
    timeline_despesas = [timeline[label]['despesas'] for label in timeline_labels]
    timeline_aditivos = [timeline[label]['aditivos'] for label in timeline_labels]

    margem_real = obra.margem_real
    margem_real_float = float(margem_real)
    margem_gauge_percent = max(0, min(margem_real_float, 50))
    margem_gauge_angle = (margem_gauge_percent * 3.6) - 90

    if obra.total_notas_fiscais <= 0:
        margem_status = 'Sem base'
        margem_status_classe = 'text-muted'
    elif margem_real_float < 10:
        margem_status = 'Ruim'
        margem_status_classe = 'text-danger'
    elif margem_real_float < 20:
        margem_status = 'Regular'
        margem_status_classe = 'text-warning'
    elif margem_real_float < 30:
        margem_status = 'Bom'
        margem_status_classe = 'text-success'
    elif margem_real_float < 40:
        margem_status = 'Otimo'
        margem_status_classe = 'text-primary'
    else:
        margem_status = 'Excelente'
        margem_status_classe = 'text-info'

    contexto = {
        'obra': obra,
        'notas_fiscais': obra.notas_fiscais.all()[:5],
        'despesas': obra.despesas_registradas.all()[:5],
        'faturamentos_diretos': obra.faturamentos_diretos.all()[:5],
        'aditivos': obra.aditivos_registrados.all()[:5],
        'retencoes_tecnicas': obra.retencoes_tecnicas_registradas.all()[:5],
        'margem_real_float': margem_real_float,
        'margem_gauge_angle': margem_gauge_angle,
        'margem_status': margem_status,
        'margem_status_classe': margem_status_classe,
        'grafico_evolucao': {
            'labels': timeline_labels,
            'faturado': timeline_faturado,
            'despesas': timeline_despesas,
            'aditivos': timeline_aditivos,
        },
        'grafico_despesas_comparativo': {
            'labels': ['Despesa'],
            'projetada': [float(obra.projecao_despesa)],
            'real': [float(obra.total_despesa_real)],
        },
        'grafico_receitas_comparativo': {
            'labels': ['Receita'],
            'projetada': [float(obra.contrato_atualizado)],
            'realizada': [float(obra.total_notas_fiscais)],
        },
        'grafico_composicao': {
            'labels': ['Faturado', 'Despesas', 'Impostos', 'INSS retido', 'Outras ret. NF', 'Ret. tecnica'],
            'valores': [
                float(obra.total_notas_fiscais),
                float(obra.total_despesa_real),
                float(obra.total_impostos),
                float(obra.total_retencoes_inss),
                float(obra.total_retencoes_nf_sem_inss),
                float(obra.total_retencoes_tecnicas),
            ],
        },
    }
    return render(request, 'obras/detalhe_obra.html', contexto)


def _lista_itens_obra(request, obra_id, tipo):
    obra = get_object_or_404(_obra_base_queryset(), id=obra_id)
    configuracoes = {
        'notas': {
            'titulo': 'Notas fiscais',
            'descricao': 'Faturamentos vinculados a contas a receber da obra.',
            'itens': [nota for nota in obra.notas_fiscais.all() if nota.status != NotaFiscal.STATUS_CANCELADA],
            'total': obra.total_notas_fiscais,
        },
        'despesas': {
            'titulo': 'Despesas',
            'descricao': 'Despesas vindas das contas a pagar vinculadas a esta obra.',
            'itens': list(obra.despesas_registradas.all()),
            'total': obra.total_despesa_real,
        },
        'faturamentos-diretos': {
            'titulo': 'Faturamento direto',
            'descricao': 'Compras diretas do cliente descontadas do saldo contratual.',
            'itens': list(obra.faturamentos_diretos.all()),
            'total': obra.total_faturamento_direto,
        },
        'aditivos': {
            'titulo': 'Movimentacoes contratuais',
            'descricao': 'Aditivos e supressoes do contrato da obra.',
            'itens': list(obra.aditivos_registrados.all()),
            'total': obra.total_movimentacoes_contratuais,
        },
        'retencoes-tecnicas': {
            'titulo': 'Retencoes tecnicas',
            'descricao': 'Retencoes e devolucoes tecnicas vinculadas a obra.',
            'itens': list(obra.retencoes_tecnicas_registradas.all()),
            'total': obra.total_retencoes_tecnicas,
        },
    }
    contexto = configuracoes[tipo]
    contexto.update({'obra': obra, 'tipo': tipo})
    return render(request, 'obras/lista_itens_obra.html', contexto)


def lista_notas_obra(request, obra_id):
    return _lista_itens_obra(request, obra_id, 'notas')


def lista_despesas_obra(request, obra_id):
    return _lista_itens_obra(request, obra_id, 'despesas')


def lista_faturamentos_diretos_obra(request, obra_id):
    return _lista_itens_obra(request, obra_id, 'faturamentos-diretos')


def lista_aditivos_obra(request, obra_id):
    return _lista_itens_obra(request, obra_id, 'aditivos')


def lista_retencoes_tecnicas_obra(request, obra_id):
    return _lista_itens_obra(request, obra_id, 'retencoes-tecnicas')


def relatorio_obra(request, obra_id):
    obra = get_object_or_404(_obra_base_queryset(), id=obra_id)
    filtro_form = RelatorioObraFiltroForm(request.GET or None)

    notas = [nota for nota in obra.notas_fiscais.all() if nota.status != NotaFiscal.STATUS_CANCELADA]
    despesas = list(obra.despesas_registradas.all())
    aditivos = list(obra.aditivos_registrados.all())
    retencoes_tecnicas = list(obra.retencoes_tecnicas_registradas.all())

    if filtro_form.is_valid():
        data_inicial = filtro_form.cleaned_data['data_inicial']
        data_final = filtro_form.cleaned_data['data_final']

        if data_inicial:
            notas = [nota for nota in notas if nota.data_emissao >= data_inicial]
            despesas = [despesa for despesa in despesas if despesa.data_referencia >= data_inicial]
            aditivos = [aditivo for aditivo in aditivos if aditivo.data_referencia >= data_inicial]
            retencoes_tecnicas = [
                retencao for retencao in retencoes_tecnicas if retencao.data_referencia >= data_inicial
            ]
        if data_final:
            notas = [nota for nota in notas if nota.data_emissao <= data_final]
            despesas = [despesa for despesa in despesas if despesa.data_referencia <= data_final]
            aditivos = [aditivo for aditivo in aditivos if aditivo.data_referencia <= data_final]
            retencoes_tecnicas = [
                retencao for retencao in retencoes_tecnicas if retencao.data_referencia <= data_final
            ]

    total_faturado = sum((nota.valor_bruto for nota in notas), Decimal('0'))
    total_despesas = sum((despesa.valor for despesa in despesas), Decimal('0'))
    total_aditivos = sum(
        (aditivo.valor for aditivo in aditivos if aditivo.tipo == AditivoContrato.TIPO_ADITIVO),
        Decimal('0'),
    )
    total_supressoes = sum(
        (aditivo.valor for aditivo in aditivos if aditivo.tipo == AditivoContrato.TIPO_SUPRESSAO),
        Decimal('0'),
    )
    total_impostos = sum((nota.total_impostos for nota in notas), Decimal('0'))
    total_retencoes_nf = sum((nota.total_retencoes for nota in notas), Decimal('0'))
    total_retencoes_inss = sum((nota.total_retencoes_inss for nota in notas), Decimal('0'))
    total_retencoes_nf_sem_inss = total_retencoes_nf - total_retencoes_inss
    total_retencoes_tecnicas = sum((retencao.valor_saldo for retencao in retencoes_tecnicas), Decimal('0'))
    total_retencoes = total_retencoes_nf + total_retencoes_tecnicas
    total_liquido = total_faturado - total_impostos - total_retencoes
    resultado_periodo = total_faturado - total_despesas - total_impostos - total_retencoes

    eventos = sorted(
        chain(
            (
                {
                    'data': nota.data_emissao,
                    'tipo': 'Nota fiscal',
                    'descricao': f'NF {nota.numero}',
                    'valor': nota.valor_bruto,
                }
                for nota in notas
            ),
            (
                {
                    'data': despesa.data_referencia,
                    'tipo': 'Despesa',
                    'descricao': despesa.descricao,
                    'valor': despesa.valor,
                }
                for despesa in despesas
            ),
            (
                {
                    'data': aditivo.data_referencia,
                    'tipo': aditivo.get_tipo_display(),
                    'descricao': aditivo.descricao,
                    'valor': aditivo.valor if aditivo.tipo == AditivoContrato.TIPO_ADITIVO else -aditivo.valor,
                }
                for aditivo in aditivos
            ),
            (
                {
                    'data': retencao.data_referencia,
                    'tipo': 'Devolucao retencao tecnica'
                    if retencao.tipo == RetencaoTecnicaObra.TIPO_DEVOLUCAO
                    else 'Retencao tecnica',
                    'descricao': retencao.descricao,
                    'valor': retencao.valor_evento,
                }
                for retencao in retencoes_tecnicas
            ),
        ),
        key=itemgetter('data'),
        reverse=True,
    )

    return render(
        request,
        'obras/relatorio_obra.html',
        {
            'obra': obra,
            'notas': notas,
            'despesas': despesas,
            'aditivos': aditivos,
            'retencoes_tecnicas': retencoes_tecnicas,
            'eventos': eventos,
            'filtro_form': filtro_form,
            'total_faturado': total_faturado,
            'total_despesas': total_despesas,
            'total_aditivos': total_aditivos,
            'total_supressoes': total_supressoes,
            'total_impostos': total_impostos,
            'total_retencoes_nf': total_retencoes_nf,
            'total_retencoes_inss': total_retencoes_inss,
            'total_retencoes_nf_sem_inss': total_retencoes_nf_sem_inss,
            'total_retencoes_tecnicas': total_retencoes_tecnicas,
            'total_retencoes': total_retencoes,
            'total_liquido': total_liquido,
            'resultado_periodo': resultado_periodo,
        },
    )


def historico_financeiro(request, obra_id):
    obra = get_object_or_404(_obra_base_queryset(), id=obra_id)

    eventos_notas = [
        {
            'data': nota.data_emissao,
            'tipo': 'Nota fiscal',
            'descricao': f'NF {nota.numero} ({nota.get_status_display()})',
            'valor': nota.valor_bruto,
            'classe': 'table-success',
            'link': ('detalhe_nota_fiscal', nota.id),
        }
        for nota in obra.notas_fiscais.all()
        if nota.status != NotaFiscal.STATUS_CANCELADA
    ]

    eventos_despesas = [
        {
            'id': despesa.id,
            'data': despesa.data_referencia,
            'tipo': 'Despesa',
            'descricao': f'{despesa.get_categoria_display()} - {despesa.descricao}',
            'valor': despesa.valor,
            'classe': 'table-danger',
            'link': None,
        }
        for despesa in obra.despesas_registradas.all()
    ]

    eventos_aditivos = [
        {
            'id': aditivo.id,
            'data': aditivo.data_referencia,
            'tipo': aditivo.get_tipo_display(),
            'descricao': aditivo.descricao,
            'valor': aditivo.valor if aditivo.tipo == AditivoContrato.TIPO_ADITIVO else -aditivo.valor,
            'classe': 'table-info',
            'link': None,
        }
        for aditivo in obra.aditivos_registrados.all()
    ]

    eventos_retencoes_tecnicas = [
        {
            'id': retencao.id,
            'data': retencao.data_referencia,
            'tipo': 'Devolucao retencao tecnica'
            if retencao.tipo == RetencaoTecnicaObra.TIPO_DEVOLUCAO
            else 'Retencao tecnica',
            'descricao': retencao.descricao,
            'valor': retencao.valor_evento,
            'classe': 'table-success' if retencao.tipo == RetencaoTecnicaObra.TIPO_DEVOLUCAO else 'table-warning',
            'link': None,
            'retencao_tipo': retencao.tipo,
        }
        for retencao in obra.retencoes_tecnicas_registradas.all()
    ]

    eventos = sorted(
        chain(eventos_notas, eventos_despesas, eventos_aditivos, eventos_retencoes_tecnicas),
        key=itemgetter('data'),
        reverse=True,
    )

    return render(
        request,
        'obras/historico_financeiro.html',
        {'obra': obra, 'eventos': eventos},
    )


def nova_nota_fiscal(request, obra_id):
    obra = get_object_or_404(Obra, id=obra_id)
    messages.info(request, 'As NFs da obra agora devem ser lancadas pelo Financeiro em Contas a Receber.')
    return redirect(f'{reverse("nova_conta_receber")}?obra={obra.id}')


def editar_nota_fiscal(request, obra_id, nota_id):
    obra = get_object_or_404(Obra, id=obra_id)
    nota = get_object_or_404(NotaFiscal, id=nota_id, obra=obra)

    if request.method == 'POST':
        form = NotaFiscalForm(request.POST, instance=nota)
        retencoes_formset, impostos_formset = _build_nota_formsets(request.POST, instance=nota)
        if form.is_valid() and retencoes_formset.is_valid() and impostos_formset.is_valid():
            with transaction.atomic():
                form.save()
                _save_inline_formset(retencoes_formset, 'nota_fiscal')
                _save_inline_formset(impostos_formset, 'nota_fiscal')
            messages.success(request, 'Nota fiscal atualizada com sucesso.')
            return redirect('detalhe_nota_fiscal', obra_id=obra.id, nota_id=nota.id)
    else:
        form = NotaFiscalForm(instance=nota)
        retencoes_formset, impostos_formset = _build_nota_formsets(instance=nota)

    return render(
        request,
        'obras/form_nota_fiscal.html',
        {
            'form': form,
            'obra': obra,
            'titulo': 'Editar Nota Fiscal',
            'nota': nota,
            'retencoes_formset': retencoes_formset,
            'impostos_formset': impostos_formset,
        },
    )


def detalhe_nota_fiscal(request, obra_id, nota_id):
    obra = get_object_or_404(Obra, id=obra_id)
    nota = get_object_or_404(
        NotaFiscal.objects.prefetch_related('retencoes', 'impostos'),
        id=nota_id,
        obra=obra,
    )

    retencao_form = RetencaoNotaFiscalForm(prefix='retencao')
    imposto_form = ImpostoNotaFiscalForm(prefix='imposto')

    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        if form_type == 'retencao':
            retencao_form = RetencaoNotaFiscalForm(request.POST, prefix='retencao')
            if retencao_form.is_valid():
                retencao = retencao_form.save(commit=False)
                retencao.nota_fiscal = nota
                retencao.save()
                messages.success(request, 'Retencao adicionada com sucesso.')
                return redirect('detalhe_nota_fiscal', obra_id=obra.id, nota_id=nota.id)
        elif form_type == 'imposto':
            imposto_form = ImpostoNotaFiscalForm(request.POST, prefix='imposto')
            if imposto_form.is_valid():
                imposto = imposto_form.save(commit=False)
                imposto.nota_fiscal = nota
                imposto.save()
                messages.success(request, 'Imposto adicionado com sucesso.')
                return redirect('detalhe_nota_fiscal', obra_id=obra.id, nota_id=nota.id)

    contexto = {
        'obra': obra,
        'nota': nota,
        'retencao_form': retencao_form,
        'imposto_form': imposto_form,
        'retencoes': nota.retencoes.all(),
        'impostos': nota.impostos.all(),
    }
    return render(request, 'obras/detalhe_nota_fiscal.html', contexto)


def nova_despesa(request, obra_id):
    obra = get_object_or_404(Obra, id=obra_id)
    messages.info(request, 'As despesas da obra agora devem ser lancadas pelo Financeiro em Contas a Pagar.')
    return redirect(f'{reverse("nova_conta_pagar")}?obra={obra.id}')


def novo_aditivo(request, obra_id):
    obra = get_object_or_404(Obra, id=obra_id)

    if request.method == 'POST':
        form = AditivoContratoForm(request.POST)
        if form.is_valid():
            aditivo = form.save(commit=False)
            aditivo.obra = obra
            aditivo.save()
            messages.success(request, 'Movimentacao contratual cadastrada com sucesso.')
            return redirect('historico_financeiro', obra_id=obra.id)
    else:
        form = AditivoContratoForm()

    return render(
        request,
        'obras/form_aditivo.html',
        {'form': form, 'obra': obra, 'titulo': 'Nova Movimentacao Contratual'},
    )


def nova_retencao_tecnica(request, obra_id):
    obra = get_object_or_404(Obra, id=obra_id)

    if request.method == 'POST':
        form = RetencaoTecnicaObraForm(request.POST)
        if form.is_valid():
            retencao = form.save(commit=False)
            retencao.obra = obra
            retencao.save()
            messages.success(request, 'Retencao tecnica cadastrada com sucesso.')
            return redirect('historico_financeiro', obra_id=obra.id)
    else:
        form = RetencaoTecnicaObraForm()

    return render(
        request,
        'obras/form_retencao_tecnica.html',
        {'form': form, 'obra': obra, 'titulo': 'Nova Retencao Tecnica'},
    )


def devolver_retencao_tecnica(request, obra_id, retencao_id):
    obra = get_object_or_404(Obra, id=obra_id)
    retencao_original = get_object_or_404(
        RetencaoTecnicaObra,
        id=retencao_id,
        obra=obra,
        tipo=RetencaoTecnicaObra.TIPO_RETENCAO,
    )

    if request.method == 'POST':
        form = RetencaoTecnicaObraForm(request.POST)
        if form.is_valid():
            devolucao = form.save(commit=False)
            devolucao.obra = obra
            devolucao.tipo = RetencaoTecnicaObra.TIPO_DEVOLUCAO
            devolucao.save()
            messages.success(request, 'Devolucao de retencao tecnica cadastrada com sucesso.')
            return redirect('historico_financeiro', obra_id=obra.id)
    else:
        data_referencia = retencao_original.data_prevista_devolucao or timezone.localdate()
        form = RetencaoTecnicaObraForm(
            initial={
                'tipo': RetencaoTecnicaObra.TIPO_DEVOLUCAO,
                'data_referencia': data_referencia,
                'descricao': f'Devolucao - {retencao_original.descricao}',
                'valor': retencao_original.valor,
                'data_devolucao': data_referencia,
            }
        )

    return render(
        request,
        'obras/form_retencao_tecnica.html',
        {
            'form': form,
            'obra': obra,
            'titulo': 'Registrar Devolucao de Retencao Tecnica',
            'retencao_original': retencao_original,
        },
    )


def excluir_obra(request, obra_id):
    obra = get_object_or_404(Obra, id=obra_id)

    if request.method == 'POST':
        nome_obra = obra.nome_obra
        obra.delete()
        messages.success(request, f'Obra "{nome_obra}" excluida com sucesso.')
        return redirect('lista_obras')

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir obra',
            'mensagem': f'Voce esta prestes a excluir a obra "{obra.nome_obra}".',
            'detalhe': 'Essa acao tambem remove notas fiscais, despesas, aditivos e demais lancamentos vinculados.',
            'confirmar_label': 'Excluir obra',
            'cancelar_href': reverse('detalhe_obra', args=[obra.id]),
        },
    )


def excluir_nota_fiscal(request, obra_id, nota_id):
    obra = get_object_or_404(Obra, id=obra_id)
    nota = get_object_or_404(NotaFiscal, id=nota_id, obra=obra)

    if request.method == 'POST':
        numero = nota.numero
        nota.delete()
        messages.success(request, f'NF {numero} excluida com sucesso.')
        return redirect('historico_financeiro', obra_id=obra.id)

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir nota fiscal',
            'mensagem': f'Voce esta prestes a excluir a NF {nota.numero}.',
            'detalhe': 'As retencoes e os impostos vinculados a essa nota tambem serao removidos.',
            'confirmar_label': 'Excluir nota fiscal',
            'cancelar_href': reverse('detalhe_nota_fiscal', args=[obra.id, nota.id]),
        },
    )


def excluir_despesa(request, obra_id, despesa_id):
    obra = get_object_or_404(Obra, id=obra_id)
    despesa = get_object_or_404(DespesaObra, id=despesa_id, obra=obra)

    if request.method == 'POST':
        descricao = despesa.descricao
        despesa.delete()
        messages.success(request, f'Despesa "{descricao}" excluida com sucesso.')
        return redirect('historico_financeiro', obra_id=obra.id)

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir despesa',
            'mensagem': f'Voce esta prestes a excluir a despesa "{despesa.descricao}".',
            'detalhe': 'O total financeiro da obra sera recalculado automaticamente.',
            'confirmar_label': 'Excluir despesa',
            'cancelar_href': reverse('historico_financeiro', args=[obra.id]),
        },
    )


def excluir_aditivo(request, obra_id, aditivo_id):
    obra = get_object_or_404(Obra, id=obra_id)
    aditivo = get_object_or_404(AditivoContrato, id=aditivo_id, obra=obra)

    if request.method == 'POST':
        descricao = aditivo.descricao
        tipo = aditivo.get_tipo_display()
        aditivo.delete()
        messages.success(request, f'{tipo} "{descricao}" excluido com sucesso.')
        return redirect('historico_financeiro', obra_id=obra.id)

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': f'Excluir {aditivo.get_tipo_display().lower()}',
            'mensagem': f'Voce esta prestes a excluir o registro "{aditivo.descricao}".',
            'detalhe': 'O contrato atualizado da obra sera recalculado automaticamente.',
            'confirmar_label': f'Excluir {aditivo.get_tipo_display().lower()}',
            'cancelar_href': reverse('historico_financeiro', args=[obra.id]),
        },
    )


def excluir_retencao_tecnica(request, obra_id, retencao_id):
    obra = get_object_or_404(Obra, id=obra_id)
    retencao = get_object_or_404(RetencaoTecnicaObra, id=retencao_id, obra=obra)

    if request.method == 'POST':
        descricao = retencao.descricao
        retencao.delete()
        messages.success(request, f'Retencao tecnica "{descricao}" excluida com sucesso.')
        return redirect('historico_financeiro', obra_id=obra.id)

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir retencao tecnica',
            'mensagem': f'Voce esta prestes a excluir a retencao tecnica "{retencao.descricao}".',
            'detalhe': 'O valor liquido e os indicadores da obra serao recalculados automaticamente.',
            'confirmar_label': 'Excluir retencao tecnica',
            'cancelar_href': reverse('historico_financeiro', args=[obra.id]),
        },
    )


def excluir_retencao(request, obra_id, nota_id, retencao_id):
    obra = get_object_or_404(Obra, id=obra_id)
    nota = get_object_or_404(NotaFiscal, id=nota_id, obra=obra)
    retencao = get_object_or_404(RetencaoNotaFiscal, id=retencao_id, nota_fiscal=nota)

    if request.method == 'POST':
        descricao = retencao.descricao or retencao.get_tipo_display()
        retencao.delete()
        messages.success(request, f'Retencao "{descricao}" excluida com sucesso.')
        return redirect('detalhe_nota_fiscal', obra_id=obra.id, nota_id=nota.id)

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir retencao',
            'mensagem': f'Voce esta prestes a excluir a retencao "{retencao.descricao or retencao.get_tipo_display()}".',
            'detalhe': 'O valor liquido da nota sera recalculado automaticamente.',
            'confirmar_label': 'Excluir retencao',
            'cancelar_href': reverse('detalhe_nota_fiscal', args=[obra.id, nota.id]),
        },
    )


def excluir_imposto(request, obra_id, nota_id, imposto_id):
    obra = get_object_or_404(Obra, id=obra_id)
    nota = get_object_or_404(NotaFiscal, id=nota_id, obra=obra)
    imposto = get_object_or_404(ImpostoNotaFiscal, id=imposto_id, nota_fiscal=nota)

    if request.method == 'POST':
        descricao = imposto.descricao or imposto.get_tipo_display()
        imposto.delete()
        messages.success(request, f'Imposto "{descricao}" excluido com sucesso.')
        return redirect('detalhe_nota_fiscal', obra_id=obra.id, nota_id=nota.id)

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir imposto',
            'mensagem': f'Voce esta prestes a excluir o imposto "{imposto.descricao or imposto.get_tipo_display()}".',
            'detalhe': 'O valor liquido da nota sera recalculado automaticamente.',
            'confirmar_label': 'Excluir imposto',
            'cancelar_href': reverse('detalhe_nota_fiscal', args=[obra.id, nota.id]),
        },
    )
