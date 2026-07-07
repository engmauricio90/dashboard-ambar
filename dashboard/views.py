from decimal import Decimal

from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import render

from obras.models import NotaFiscal, Obra

from .forms import DashboardFiltroForm


def _obras_base_queryset():
    notas_queryset = NotaFiscal.objects.prefetch_related('retencoes', 'impostos').order_by('-data_emissao', '-id')
    return Obra.objects.prefetch_related(
        'aditivos_registrados',
        'despesas_registradas',
        'faturamentos_diretos',
        'retencoes_tecnicas_registradas',
        Prefetch('notas_fiscais', queryset=notas_queryset),
    )


def _build_dashboard_context(obras_resumo, obras_lista=None):
    if hasattr(obras_resumo, 'order_by'):
        obras_resumo = list(obras_resumo.order_by('nome_obra'))
    else:
        obras_resumo = sorted(list(obras_resumo), key=lambda obra: obra.nome_obra.casefold())
    obras_lista = list(obras_lista) if obras_lista is not None else obras_resumo

    totais = {
        'total_contratos': Decimal('0'),
        'total_aditivos': Decimal('0'),
        'total_supressoes': Decimal('0'),
        'total_notas': Decimal('0'),
        'total_impostos': Decimal('0'),
        'total_retencoes_tecnicas': Decimal('0'),
        'total_recebido_liquido': Decimal('0'),
        'total_despesas': Decimal('0'),
        'total_resultado_projetado': Decimal('0'),
        'total_resultado_real': Decimal('0'),
    }

    obras_em_alerta = []
    status_counts = {
        'Em andamento': 0,
        'Concluida': 0,
        'Paralisada': 0,
    }

    chart_labels = []
    chart_faturamento = []
    chart_despesas = []
    chart_resultado_real = []

    for obra in obras_resumo:
        status = obra.get_status_obra_display()
        status_counts[status] = status_counts.get(status, 0) + 1
        chart_labels.append(obra.nome_obra)
        chart_faturamento.append(float(obra.total_notas_fiscais))
        chart_despesas.append(float(obra.total_despesa_real))
        chart_resultado_real.append(float(obra.resultado_real))

        if obra.status_obra == 'concluida':
            continue

        totais['total_contratos'] += obra.contrato_atualizado
        totais['total_aditivos'] += obra.total_aditivos
        totais['total_supressoes'] += obra.total_supressoes
        totais['total_notas'] += obra.total_notas_fiscais
        totais['total_impostos'] += obra.total_impostos_obra
        totais['total_retencoes_tecnicas'] += obra.total_retencoes_tecnicas
        totais['total_recebido_liquido'] += obra.total_recebido_liquido
        totais['total_despesas'] += obra.total_despesa_real
        totais['total_resultado_projetado'] += obra.projecao_resultado
        totais['total_resultado_real'] += obra.resultado_real

        if obra.resultado_real < 0 or obra.margem_real < 0:
            obras_em_alerta.append(obra)

    return {
        **totais,
        'obras': obras_lista,
        'quantidade_obras': len(obras_resumo),
        'quantidade_obras_lista': len(obras_lista),
        'quantidade_obras_em_alerta': len(obras_em_alerta),
        'obras_em_alerta': obras_em_alerta[:5],
        'grafico_operacional': {
            'labels': chart_labels,
            'faturamento': chart_faturamento,
            'despesas': chart_despesas,
        },
        'grafico_resultado_real': {
            'labels': chart_labels,
            'resultados': chart_resultado_real,
        },
        'grafico_status': {
            'labels': list(status_counts.keys()),
            'valores': list(status_counts.values()),
        },
    }


def _ordenar_obras_lista(obras, ordenacao):
    ordenacao = ordenacao or 'resultado_real_desc'
    ordenadores = {
        'resultado_real_desc': (lambda obra: obra.resultado_real, True),
        'resultado_real_asc': (lambda obra: obra.resultado_real, False),
        'nome_asc': (lambda obra: obra.nome_obra.casefold(), False),
        'nome_desc': (lambda obra: obra.nome_obra.casefold(), True),
        'contrato_desc': (lambda obra: obra.contrato_atualizado, True),
        'contrato_asc': (lambda obra: obra.contrato_atualizado, False),
        'faturado_desc': (lambda obra: obra.total_notas_fiscais, True),
        'faturado_asc': (lambda obra: obra.total_notas_fiscais, False),
    }
    key, reverse = ordenadores.get(ordenacao, ordenadores['resultado_real_desc'])
    return sorted(obras, key=key, reverse=reverse)


def _get_filtered_obras(request):
    form = DashboardFiltroForm(request.GET or None)
    obras = _obras_base_queryset()

    if form.is_valid():
        busca = form.cleaned_data['busca']
        cliente = form.cleaned_data['cliente']
        status = form.cleaned_data['status']
        ordenacao = form.cleaned_data['ordenacao']

        if status:
            obras = obras.filter(status_obra=status)
        if cliente:
            obras = obras.filter(cliente__icontains=cliente)
        if busca:
            obras = obras.filter(nome_obra__icontains=busca)

        return _ordenar_obras_lista(list(obras), ordenacao), form

    return _ordenar_obras_lista(list(obras), 'resultado_real_desc'), form


def home(request):
    obras_lista, filtro_form = _get_filtered_obras(request)
    contexto = _build_dashboard_context(_obras_base_queryset(), obras_lista)
    contexto['filtro_form'] = filtro_form
    return render(request, 'dashboard/home.html', contexto)


def relatorio_geral(request):
    obras_lista, filtro_form = _get_filtered_obras(request)
    contexto = _build_dashboard_context(obras_lista, obras_lista)
    contexto['filtro_form'] = filtro_form
    return render(request, 'dashboard/relatorio_geral.html', contexto)


def healthz(request):
    return HttpResponse('ok', content_type='text/plain')
