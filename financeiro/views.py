from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from controles.views import _build_simple_pdf

from .forms import CentroCustoForm, ContaPagarForm, ContaReceberForm, FinanceiroFiltroForm
from .models import CentroCusto, ContaPagar, ContaReceber


def _status_visual(conta, tipo):
    if conta.status == 'cancelado':
        return 'Cancelado'
    if tipo == 'receber' and conta.status == ContaReceber.STATUS_RECEBIDO:
        return 'Recebido'
    if tipo == 'pagar' and conta.status == ContaPagar.STATUS_PAGO:
        return 'Pago'
    if conta.data_vencimento < timezone.localdate():
        return 'Atrasado'
    return 'Em aberto'


def _base_receber():
    return ContaReceber.objects.select_related('obra', 'centro_custo', 'nota_fiscal')


def _base_pagar():
    return ContaPagar.objects.select_related('obra', 'centro_custo', 'despesa_obra')


def _filtrar_contas(request):
    form = FinanceiroFiltroForm(request.GET or None)
    receber = _base_receber()
    pagar = _base_pagar()
    tipo = status = ''

    if form.is_valid():
        tipo = form.cleaned_data['tipo']
        status = form.cleaned_data['status']
        data_inicial = form.cleaned_data['data_inicial']
        data_final = form.cleaned_data['data_final']
        obra = form.cleaned_data['obra']
        centro_custo = form.cleaned_data['centro_custo']
        busca = form.cleaned_data['busca']

        if data_inicial:
            receber = receber.filter(data_vencimento__gte=data_inicial)
            pagar = pagar.filter(data_vencimento__gte=data_inicial)
        if data_final:
            receber = receber.filter(data_vencimento__lte=data_final)
            pagar = pagar.filter(data_vencimento__lte=data_final)
        if obra:
            receber = receber.filter(obra__nome_obra__icontains=obra)
            pagar = pagar.filter(obra__nome_obra__icontains=obra)
        if centro_custo:
            receber = receber.filter(centro_custo=centro_custo)
            pagar = pagar.filter(centro_custo=centro_custo)
        if busca:
            receber = receber.filter(Q(cliente__icontains=busca) | Q(descricao__icontains=busca) | Q(numero_nf__icontains=busca))
            pagar = pagar.filter(Q(fornecedor__icontains=busca) | Q(descricao__icontains=busca))
        if status == 'aberto':
            receber = receber.filter(status=ContaReceber.STATUS_ABERTO)
            pagar = pagar.filter(status=ContaPagar.STATUS_ABERTO)
        elif status == 'baixado':
            receber = receber.filter(status=ContaReceber.STATUS_RECEBIDO)
            pagar = pagar.filter(status=ContaPagar.STATUS_PAGO)
        elif status == 'cancelado':
            receber = receber.filter(status=ContaReceber.STATUS_CANCELADO)
            pagar = pagar.filter(status=ContaPagar.STATUS_CANCELADO)
        elif status == 'atrasado':
            hoje = timezone.localdate()
            receber = receber.filter(status=ContaReceber.STATUS_ABERTO, data_vencimento__lt=hoje)
            pagar = pagar.filter(status=ContaPagar.STATUS_ABERTO, data_vencimento__lt=hoje)

    if tipo == 'receber':
        pagar = ContaPagar.objects.none()
    elif tipo == 'pagar':
        receber = ContaReceber.objects.none()

    return form, receber, pagar


def _eventos_fluxo(receber, pagar):
    eventos = []
    for conta in receber:
        eventos.append(
            {
                'data': conta.data_recebimento or conta.data_vencimento,
                'tipo': 'Receber',
                'descricao': conta.descricao,
                'pessoa': conta.cliente,
                'obra': conta.obra,
                'centro_custo': conta.centro_custo,
                'status': _status_visual(conta, 'receber'),
                'valor': conta.valor_liquido,
            }
        )
    for conta in pagar:
        eventos.append(
            {
                'data': conta.data_pagamento or conta.data_vencimento,
                'tipo': 'Pagar',
                'descricao': conta.descricao,
                'pessoa': conta.fornecedor,
                'obra': conta.obra,
                'centro_custo': conta.centro_custo,
                'status': _status_visual(conta, 'pagar'),
                'valor': -conta.valor,
            }
        )
    return sorted(eventos, key=lambda item: (item['data'], item['tipo'], item['descricao']))


def _resumo(receber, pagar):
    hoje = timezone.localdate()
    receber = list(receber)
    pagar = list(pagar)
    total_receber_aberto = sum((c.valor_liquido for c in receber if c.status == ContaReceber.STATUS_ABERTO), Decimal('0'))
    total_recebido = sum((c.valor_liquido for c in receber if c.status == ContaReceber.STATUS_RECEBIDO), Decimal('0'))
    total_pagar_aberto = sum((c.valor for c in pagar if c.status == ContaPagar.STATUS_ABERTO), Decimal('0'))
    total_pago = sum((c.valor for c in pagar if c.status == ContaPagar.STATUS_PAGO), Decimal('0'))
    atrasado_receber = sum(
        (c.valor_liquido for c in receber if c.status == ContaReceber.STATUS_ABERTO and c.data_vencimento < hoje),
        Decimal('0'),
    )
    atrasado_pagar = sum(
        (c.valor for c in pagar if c.status == ContaPagar.STATUS_ABERTO and c.data_vencimento < hoje),
        Decimal('0'),
    )
    return {
        'total_receber_aberto': total_receber_aberto,
        'total_recebido': total_recebido,
        'total_pagar_aberto': total_pagar_aberto,
        'total_pago': total_pago,
        'saldo_previsto': total_receber_aberto - total_pagar_aberto,
        'saldo_realizado': total_recebido - total_pago,
        'atrasado_receber': atrasado_receber,
        'atrasado_pagar': atrasado_pagar,
    }


def _grafico_fluxo(eventos):
    meses = defaultdict(lambda: {'receber': Decimal('0'), 'pagar': Decimal('0')})
    for evento in eventos:
        chave = evento['data'].strftime('%Y-%m')
        if evento['tipo'] == 'Receber':
            meses[chave]['receber'] += evento['valor']
        else:
            meses[chave]['pagar'] += abs(evento['valor'])
    labels = sorted(meses.keys())
    return {
        'labels': labels,
        'receber': [float(meses[label]['receber']) for label in labels],
        'pagar': [float(meses[label]['pagar']) for label in labels],
    }


def financeiro_home(request):
    receber = _base_receber()
    pagar = _base_pagar()
    eventos = _eventos_fluxo(receber, pagar)
    contexto = {
        **_resumo(receber, pagar),
        'ultimos_eventos': eventos[-10:],
        'grafico_fluxo': _grafico_fluxo(eventos),
    }
    return render(request, 'financeiro/home.html', contexto)


def lista_contas_receber(request):
    contas = _base_receber()
    return render(request, 'financeiro/lista_contas_receber.html', {'contas': contas})


def lista_contas_pagar(request):
    contas = _base_pagar()
    return render(request, 'financeiro/lista_contas_pagar.html', {'contas': contas})


def nova_conta_receber(request):
    if request.method == 'POST':
        form = ContaReceberForm(request.POST)
        if form.is_valid():
            conta = form.save()
            messages.success(request, 'Conta a receber cadastrada com sucesso.')
            return redirect('lista_contas_receber')
    else:
        form = ContaReceberForm()
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Nova Conta a Receber'})


def editar_conta_receber(request, conta_id):
    conta = get_object_or_404(ContaReceber, id=conta_id)
    if request.method == 'POST':
        form = ContaReceberForm(request.POST, instance=conta)
        if form.is_valid():
            form.save()
            messages.success(request, 'Conta a receber atualizada com sucesso.')
            return redirect('lista_contas_receber')
    else:
        form = ContaReceberForm(instance=conta)
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Editar Conta a Receber'})


def baixar_conta_receber(request, conta_id):
    conta = get_object_or_404(ContaReceber, id=conta_id)
    conta.status = ContaReceber.STATUS_RECEBIDO
    conta.data_recebimento = conta.data_recebimento or timezone.localdate()
    conta.save()
    messages.success(request, 'Recebimento registrado com sucesso.')
    return redirect('lista_contas_receber')


def nova_conta_pagar(request):
    if request.method == 'POST':
        form = ContaPagarForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Conta a pagar cadastrada com sucesso.')
            return redirect('lista_contas_pagar')
    else:
        form = ContaPagarForm()
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Nova Conta a Pagar'})


def editar_conta_pagar(request, conta_id):
    conta = get_object_or_404(ContaPagar, id=conta_id)
    if request.method == 'POST':
        form = ContaPagarForm(request.POST, instance=conta)
        if form.is_valid():
            form.save()
            messages.success(request, 'Conta a pagar atualizada com sucesso.')
            return redirect('lista_contas_pagar')
    else:
        form = ContaPagarForm(instance=conta)
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Editar Conta a Pagar'})


def baixar_conta_pagar(request, conta_id):
    conta = get_object_or_404(ContaPagar, id=conta_id)
    conta.status = ContaPagar.STATUS_PAGO
    conta.data_pagamento = conta.data_pagamento or timezone.localdate()
    conta.save()
    messages.success(request, 'Pagamento registrado com sucesso.')
    return redirect('lista_contas_pagar')


def lista_centros_custo(request):
    centros = CentroCusto.objects.all()
    return render(request, 'financeiro/lista_centros_custo.html', {'centros': centros})


def novo_centro_custo(request):
    if request.method == 'POST':
        form = CentroCustoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Centro de custo cadastrado com sucesso.')
            return redirect('lista_centros_custo')
    else:
        form = CentroCustoForm()
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Novo Centro de Custo'})


def editar_centro_custo(request, centro_id):
    centro = get_object_or_404(CentroCusto, id=centro_id)
    if request.method == 'POST':
        form = CentroCustoForm(request.POST, instance=centro)
        if form.is_valid():
            form.save()
            messages.success(request, 'Centro de custo atualizado com sucesso.')
            return redirect('lista_centros_custo')
    else:
        form = CentroCustoForm(instance=centro)
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Editar Centro de Custo'})


def relatorio_financeiro(request):
    form, receber, pagar = _filtrar_contas(request)
    eventos = _eventos_fluxo(receber, pagar)
    contexto = {
        'filtro_form': form,
        'eventos': eventos,
        **_resumo(receber, pagar),
    }
    return render(request, 'financeiro/relatorio.html', contexto)


def relatorio_financeiro_pdf(request):
    form, receber, pagar = _filtrar_contas(request)
    eventos = _eventos_fluxo(receber, pagar)
    resumo = _resumo(receber, pagar)
    filtros = request.GET.urlencode()
    lines = [
        'RELATORIO FINANCEIRO',
        f'Emitido em {date.today().strftime("%d/%m/%Y")}',
        f'Filtros: {filtros or "sem filtros"}',
        '',
        f'A receber aberto: R$ {resumo["total_receber_aberto"]:,.2f}',
        f'Recebido: R$ {resumo["total_recebido"]:,.2f}',
        f'A pagar aberto: R$ {resumo["total_pagar_aberto"]:,.2f}',
        f'Pago: R$ {resumo["total_pago"]:,.2f}',
        f'Saldo previsto: R$ {resumo["saldo_previsto"]:,.2f}',
        '',
        'DATA | TIPO | DESCRICAO | PESSOA | CENTRO | STATUS | VALOR',
    ]
    for evento in eventos:
        lines.append(
            ' | '.join(
                [
                    evento['data'].strftime('%d/%m/%Y'),
                    evento['tipo'],
                    evento['descricao'][:28],
                    evento['pessoa'][:22],
                    str(evento['centro_custo'] or '-')[:18],
                    evento['status'],
                    f'R$ {evento["valor"]:,.2f}',
                ]
            )
        )

    pages = [lines[i : i + 34] for i in range(0, len(lines), 34)] or [[]]
    response = HttpResponse(_build_simple_pdf(pages), content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="relatorio_financeiro.pdf"'
    return response
