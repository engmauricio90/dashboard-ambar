from decimal import Decimal

from django.db.models import Prefetch
from django.shortcuts import render

from obras.models import NotaFiscal, Obra

from .forms import DashboardFiltroForm


def _obras_base_queryset():
    notas_queryset = NotaFiscal.objects.prefetch_related('retencoes', 'impostos').order_by('-data_emissao', '-id')
    return Obra.objects.prefetch_related(
        'aditivos_registrados',
        'despesas_registradas',
        'retencoes_tecnicas_registradas',
        Prefetch('notas_fiscais', queryset=notas_queryset),
    )


def _build_dashboard_context(obras):
    obras = list(obras.order_by('nome_obra'))

    totais = {
        'total_contratos': Decimal('0'),
        'total_aditivos': Decimal('0'),
        'total_supressoes': Decimal('0'),
        'total_notas': Decimal('0'),
        'total_impostos': Decimal('0'),
        'total_retencoes': Decimal('0'),
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

    for obra in obras:
        totais['total_contratos'] += obra.valor_contrato
        totais['total_aditivos'] += obra.total_aditivos
        totais['total_supressoes'] += obra.total_supressoes
        totais['total_notas'] += obra.total_notas_fiscais
        totais['total_impostos'] += obra.total_impostos
        totais['total_retencoes'] += obra.total_retencoes
        totais['total_recebido_liquido'] += obra.total_recebido_liquido
        totais['total_despesas'] += obra.total_despesa_real
        totais['total_resultado_projetado'] += obra.projecao_resultado
        totais['total_resultado_real'] += obra.resultado_real

        if obra.resultado_real < 0 or obra.margem_real < 0:
            obras_em_alerta.append(obra)

        status = obra.get_status_obra_display()
        status_counts[status] = status_counts.get(status, 0) + 1
        chart_labels.append(obra.nome_obra)
        chart_faturamento.append(float(obra.total_notas_fiscais))
        chart_despesas.append(float(obra.total_despesa_real))
        chart_resultado_real.append(float(obra.resultado_real))

    obras_ordenadas_por_resultado = sorted(
        obras,
        key=lambda obra: obra.resultado_real,
        reverse=True,
    )

    return {
        **totais,
        'obras': obras_ordenadas_por_resultado,
        'quantidade_obras': len(obras),
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


def _get_filtered_obras(request):
    form = DashboardFiltroForm(request.GET or None)
    obras = _obras_base_queryset()

    if form.is_valid():
        busca = form.cleaned_data['busca']
        cliente = form.cleaned_data['cliente']
        status = form.cleaned_data['status']

        if status:
            obras = obras.filter(status_obra=status)
        if cliente:
            obras = obras.filter(cliente__icontains=cliente)
        if busca:
            obras = obras.filter(nome_obra__icontains=busca)

    return obras, form


def home(request):
    obras, filtro_form = _get_filtered_obras(request)
    contexto = _build_dashboard_context(obras)
    contexto['filtro_form'] = filtro_form
    return render(request, 'dashboard/home.html', contexto)


def relatorio_geral(request):
    obras, filtro_form = _get_filtered_obras(request)
    contexto = _build_dashboard_context(obras)
    contexto['filtro_form'] = filtro_form
    return render(request, 'dashboard/relatorio_geral.html', contexto)
