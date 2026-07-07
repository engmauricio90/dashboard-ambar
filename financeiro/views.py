from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image, ImageDraw, ImageFont

from config.permissions import group_required

from .forms import (
    CentroCustoForm,
    ContaPagarBaixaForm,
    ContaPagarForm,
    ContaReceberBaixaForm,
    ContaReceberForm,
    FinanceiroFiltroForm,
    FornecedorForm,
    ImportarCredoresSiengeForm,
    ItemContaPagarOrdemCompraFormSet,
)
from .importadores import decodificar_csv_upload, importar_contas_pagar_credores_csv, importar_contas_pagas_credores_csv
from .models import CentroCusto, ContaPagar, ContaReceber, Fornecedor
from .services import baixar_conta_pagar as baixar_conta_pagar_service
from .services import baixar_conta_receber as baixar_conta_receber_service


financeiro_required = group_required('Financeiro', 'Diretoria')


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


def _paginar(request, queryset, per_page=50):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get('page'))


def _formset_tem_itens_oc(formset):
    return any(
        form.cleaned_data.get('item_ordem_compra') and not form.cleaned_data.get('DELETE')
        for form in formset.forms
        if hasattr(form, 'cleaned_data')
    )


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
                'valor_abs': conta.valor_liquido,
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
                'valor_abs': conta.valor_pago_efetivo if conta.status == ContaPagar.STATUS_PAGO else conta.valor,
                'valor': -conta.valor_pago_efetivo if conta.status == ContaPagar.STATUS_PAGO else -conta.valor,
            }
        )
    return sorted(eventos, key=lambda item: (item['data'], item['tipo'], item['descricao']))


def _ordenar_eventos(eventos, ordenacao):
    ordenacao = ordenacao or 'data_asc'
    key_map = {
        'data_asc': lambda item: (item['data'], item['pessoa'], item['descricao']),
        'data_desc': lambda item: (item['data'], item['pessoa'], item['descricao']),
        'fornecedor': lambda item: ((item['pessoa'] or '').lower(), item['data'], item['descricao']),
        'centro_custo': lambda item: (str(item['centro_custo'] or '').lower(), item['data'], item['pessoa']),
        'obra': lambda item: (str(item['obra'] or '').lower(), item['data'], item['pessoa']),
        'valor_desc': lambda item: (item['valor_abs'], item['data']),
        'valor_asc': lambda item: (item['valor_abs'], item['data']),
    }
    reverse = ordenacao in {'data_desc', 'valor_desc'}
    return sorted(eventos, key=key_map.get(ordenacao, key_map['data_asc']), reverse=reverse)


def _grupo_evento(evento, agrupamento):
    if agrupamento == 'centro_custo':
        return str(evento['centro_custo'] or 'Sem centro de custo')
    if agrupamento == 'fornecedor':
        return evento['pessoa'] or 'Sem fornecedor/cliente'
    if agrupamento == 'obra':
        return str(evento['obra'] or 'Sem obra')
    if agrupamento == 'status':
        return evento['status'] or 'Sem status'
    if agrupamento == 'tipo':
        return evento['tipo'] or 'Sem tipo'
    return 'Lancamentos'


def _agrupar_eventos(eventos, agrupamento):
    if not agrupamento:
        return [{'titulo': 'Lancamentos', 'eventos': eventos, 'total': sum((e['valor'] for e in eventos), Decimal('0'))}]
    grupos = []
    indices = {}
    for evento in eventos:
        titulo = _grupo_evento(evento, agrupamento)
        if titulo not in indices:
            indices[titulo] = len(grupos)
            grupos.append({'titulo': titulo, 'eventos': [], 'total': Decimal('0')})
        grupo = grupos[indices[titulo]]
        grupo['eventos'].append(evento)
        grupo['total'] += evento['valor']
    return grupos


def _resumo(receber, pagar):
    hoje = timezone.localdate()
    receber = list(receber)
    pagar = list(pagar)
    total_receber_aberto = sum((c.valor_liquido for c in receber if c.status == ContaReceber.STATUS_ABERTO), Decimal('0'))
    total_recebido = sum((c.valor_liquido for c in receber if c.status == ContaReceber.STATUS_RECEBIDO), Decimal('0'))
    total_pagar_aberto = sum((c.valor for c in pagar if c.status == ContaPagar.STATUS_ABERTO), Decimal('0'))
    total_pago = sum((c.valor_pago_efetivo for c in pagar if c.status == ContaPagar.STATUS_PAGO), Decimal('0'))
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
    semanas = defaultdict(lambda: {'receber': Decimal('0'), 'pagar': Decimal('0')})
    for evento in eventos:
        inicio_semana = evento['data'] - timedelta(days=evento['data'].weekday())
        fim_semana = inicio_semana + timedelta(days=6)
        chave = (inicio_semana, fim_semana)
        if evento['tipo'] == 'Receber':
            semanas[chave]['receber'] += evento['valor']
        else:
            semanas[chave]['pagar'] += abs(evento['valor'])
    labels = sorted(semanas.keys())
    return {
        'labels': [f'{inicio.strftime("%d/%m")} a {fim.strftime("%d/%m")}' for inicio, fim in labels],
        'receber': [float(semanas[label]['receber']) for label in labels],
        'pagar': [float(semanas[label]['pagar']) for label in labels],
    }


def _format_currency_br(value):
    value = value or Decimal('0')
    formatted = f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {formatted}'


def _pdf_font(size, bold=False):
    font_dir = Path('C:/Windows/Fonts')
    candidates = ['arialbd.ttf' if bold else 'arial.ttf', 'calibrib.ttf' if bold else 'calibri.ttf']
    for name in candidates:
        path = font_dir / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _clean_pdf_text(value):
    return str(value or '-')


def _fit_text(draw, text, font, max_width):
    text = _clean_pdf_text(text)
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = '...'
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


def _draw_table_cell(draw, text, box, font, fill, align='left'):
    x1, y1, x2, y2 = box
    text = _fit_text(draw, text, font, x2 - x1 - 18)
    text_width = draw.textlength(text, font=font)
    x = x1 + 9
    if align == 'right':
        x = x2 - text_width - 9
    elif align == 'center':
        x = x1 + ((x2 - x1) - text_width) / 2
    draw.text((x, y1 + 10), text, font=font, fill=fill)


def _financial_report_pdf(grupos, resumo, filtros, ordenacao, agrupamento):
    dpi = 200
    page_w, page_h = 2339, 1654
    margin_x = 58
    top_y = 44
    row_h = 44
    first_table_y = 305
    rows_per_page = 28
    pages = []
    printable_rows = []
    for grupo in grupos:
        printable_rows.append({'kind': 'group', 'titulo': grupo['titulo'], 'total': grupo['total']})
        printable_rows.extend({'kind': 'item', 'evento': evento} for evento in grupo['eventos'])
    chunks = [printable_rows[i : i + rows_per_page] for i in range(0, len(printable_rows), rows_per_page)] or [[]]

    title_font = _pdf_font(42, True)
    small_font = _pdf_font(22)
    label_font = _pdf_font(25, True)
    head_font = _pdf_font(20, True)
    cell_font = _pdf_font(19)
    dark = (23, 28, 31)
    muted = (75, 84, 88)
    line = (150, 160, 166)
    header_fill = (225, 231, 234)
    group_fill = (211, 220, 225)
    positive = (25, 101, 74)
    negative = (157, 43, 39)
    table_w = page_w - (margin_x * 2)

    for page_index, chunk in enumerate(chunks, start=1):
        image = Image.new('RGB', (page_w, page_h), 'white')
        draw = ImageDraw.Draw(image)

        draw.text((margin_x, top_y), 'Relatorio financeiro', font=title_font, fill=dark)
        draw.text((margin_x, top_y + 56), f'Emitido em {date.today().strftime("%d/%m/%Y")}', font=small_font, fill=muted)
        draw.text((margin_x, top_y + 88), f'Filtros: {filtros or "sem filtros"}', font=small_font, fill=muted)
        draw.text(
            (margin_x, top_y + 120),
            f'Ordenacao: {ordenacao or "data_asc"} | Agrupamento: {agrupamento or "sem agrupamento"}',
            font=small_font,
            fill=muted,
        )

        summary_y = top_y + 165
        cards = [
            ('A receber aberto', resumo['total_receber_aberto'], positive),
            ('A pagar aberto', resumo['total_pagar_aberto'], negative),
            ('Saldo previsto', resumo['saldo_previsto'], positive if resumo['saldo_previsto'] >= 0 else negative),
            ('Saldo realizado', resumo['saldo_realizado'], positive if resumo['saldo_realizado'] >= 0 else negative),
        ]
        card_gap = 18
        card_w = int((table_w - (card_gap * 3)) / 4)
        for idx, (label, value, color) in enumerate(cards):
            x = margin_x + idx * (card_w + card_gap)
            draw.rectangle((x, summary_y, x + card_w, summary_y + 92), fill=(247, 249, 250), outline=line, width=2)
            draw.text((x + 18, summary_y + 16), label, font=small_font, fill=muted)
            draw.text((x + 18, summary_y + 52), _format_currency_br(value), font=label_font, fill=color)

        table_y = first_table_y
        columns = [
            ('Data', 130, 'left'),
            ('Tipo', 100, 'center'),
            ('Descricao', 480, 'left'),
            ('Fornecedor/Cliente', 345, 'left'),
            ('Obra', 315, 'left'),
            ('Centro de custo', 315, 'left'),
            ('Status', 175, 'center'),
            ('Valor', 363, 'right'),
        ]
        x = margin_x
        draw.rectangle((margin_x, table_y, margin_x + table_w, table_y + row_h), fill=header_fill, outline=line, width=2)
        for label, width, align in columns:
            _draw_table_cell(draw, label, (x, table_y, x + width, table_y + row_h), head_font, dark, align)
            x += width

        y = table_y + row_h
        item_index = 0
        for row in chunk:
            if row['kind'] == 'group':
                draw.rectangle((margin_x, y, margin_x + table_w, y + row_h), fill=group_fill, outline=line, width=2)
                group_text = f"{row['titulo']} | Total: {_format_currency_br(row['total'])}"
                _draw_table_cell(draw, group_text, (margin_x, y, margin_x + table_w, y + row_h), label_font, dark, 'left')
                y += row_h
                continue
            evento = row['evento']
            row_fill = (255, 255, 255) if item_index % 2 == 0 else (248, 250, 250)
            item_index += 1
            draw.rectangle((margin_x, y, margin_x + table_w, y + row_h), fill=row_fill, outline=line, width=1)
            values = [
                evento['data'].strftime('%d/%m/%Y'),
                evento['tipo'],
                evento['descricao'],
                evento['pessoa'],
                evento['obra'] or '-',
                evento['centro_custo'] or '-',
                evento['status'],
                _format_currency_br(evento['valor']),
            ]
            x = margin_x
            for (label, width, align), value in zip(columns, values):
                color = positive if label == 'Valor' and evento['valor'] >= 0 else negative if label == 'Valor' else dark
                _draw_table_cell(draw, value, (x, y, x + width, y + row_h), cell_font, color, align)
                x += width
            y += row_h

        draw.line((margin_x, page_h - 70, margin_x + table_w, page_h - 70), fill=(190, 198, 202), width=1)
        draw.text((margin_x, page_h - 52), f'Pagina {page_index} de {len(chunks)}', font=small_font, fill=muted)
        pages.append(image)

    buffer = BytesIO()
    pages[0].save(buffer, 'PDF', resolution=dpi, save_all=True, append_images=pages[1:])
    return buffer.getvalue()


@financeiro_required
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


@financeiro_required
def lista_contas_receber(request):
    contas = _base_receber()
    page_obj = _paginar(request, contas)
    return render(request, 'financeiro/lista_contas_receber.html', {'contas': page_obj, 'page_obj': page_obj})


@financeiro_required
def lista_contas_pagar(request):
    contas = _base_pagar().filter(status=ContaPagar.STATUS_ABERTO)
    page_obj = _paginar(request, contas)
    return render(
        request,
        'financeiro/lista_contas_pagar.html',
        {
            'contas': page_obj,
            'page_obj': page_obj,
            'titulo': 'Contas a Pagar',
            'descricao': 'Despesas em aberto para baixa ou cancelamento em massa.',
            'mostrar_acoes_massa': True,
        },
    )


@financeiro_required
def importar_contas_pagar_sienge(request):
    resultado = None
    if request.method == 'POST':
        form = ImportarCredoresSiengeForm(request.POST, request.FILES)
        if form.is_valid():
            conteudo = decodificar_csv_upload(form.cleaned_data['arquivo'])
            try:
                if form.cleaned_data['tipo_relatorio'] == 'pago':
                    resultado = importar_contas_pagas_credores_csv(conteudo)
                else:
                    resultado = importar_contas_pagar_credores_csv(conteudo)
                messages.success(
                    request,
                    f'Importacao concluida: {resultado.criadas} criada(s), '
                    f'{resultado.atualizadas} atualizada(s), {resultado.ignoradas} ignorada(s).',
                )
            except DatabaseError as exc:
                messages.error(request, f'Nao foi possivel importar agora. Tente novamente em instantes. Detalhe: {exc}')
    else:
        form = ImportarCredoresSiengeForm()

    return render(
        request,
        'financeiro/importar_credores_sienge.html',
        {'form': form, 'resultado': resultado},
    )


@financeiro_required
def lista_contas_pagas(request):
    contas = _base_pagar().filter(status=ContaPagar.STATUS_PAGO).order_by('-data_pagamento', '-id')
    page_obj = _paginar(request, contas)
    return render(
        request,
        'financeiro/lista_contas_pagar.html',
        {
            'contas': page_obj,
            'page_obj': page_obj,
            'titulo': 'Contas Pagas',
            'descricao': 'Historico das despesas ja baixadas.',
            'mostrar_acoes_massa': False,
        },
    )


@financeiro_required
def lista_contas_pagar_canceladas(request):
    contas = _base_pagar().filter(status=ContaPagar.STATUS_CANCELADO).order_by('-updated_at', '-id')
    page_obj = _paginar(request, contas)
    return render(
        request,
        'financeiro/lista_contas_pagar.html',
        {
            'contas': page_obj,
            'page_obj': page_obj,
            'titulo': 'Contas Canceladas',
            'descricao': 'Despesas canceladas e retiradas da lista principal.',
            'mostrar_acoes_massa': False,
        },
    )


@financeiro_required
@require_POST
def acao_massa_contas_pagar(request):
    ids = request.POST.getlist('contas')
    acao = request.POST.get('acao')
    data_baixa = request.POST.get('data_baixa') or timezone.localdate()
    contas = ContaPagar.objects.filter(id__in=ids, status=ContaPagar.STATUS_ABERTO)

    if not ids:
        messages.warning(request, 'Selecione ao menos uma conta.')
        return redirect('lista_contas_pagar')

    if acao not in {'pagar', 'cancelar'}:
        messages.warning(request, 'Escolha uma acao valida.')
        return redirect('lista_contas_pagar')

    total = 0
    for conta in contas:
        if acao == 'pagar':
            conta.status = ContaPagar.STATUS_PAGO
            conta.data_pagamento = data_baixa
        else:
            conta.status = ContaPagar.STATUS_CANCELADO
        conta.save()
        total += 1

    if acao == 'pagar':
        messages.success(request, f'{total} conta(s) marcada(s) como pagas.')
        return redirect('lista_contas_pagas')

    messages.success(request, f'{total} conta(s) cancelada(s).')
    return redirect('lista_contas_pagar_canceladas')


@financeiro_required
def nova_conta_receber(request):
    if request.method == 'POST':
        form = ContaReceberForm(request.POST)
        if form.is_valid():
            conta = form.save()
            messages.success(request, 'Conta a receber cadastrada com sucesso.')
            return redirect('lista_contas_receber')
    else:
        initial = {}
        obra_id = request.GET.get('obra')
        if obra_id:
            initial['obra'] = obra_id
        form = ContaReceberForm(initial=initial)
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Nova Conta a Receber'})


@financeiro_required
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


@financeiro_required
def baixar_conta_receber(request, conta_id):
    conta = get_object_or_404(ContaReceber, id=conta_id)
    if conta.status != ContaReceber.STATUS_ABERTO:
        messages.error(request, 'Somente contas a receber em aberto podem ser recebidas.')
        return redirect('lista_contas_receber')

    if request.method == 'POST':
        form = ContaReceberBaixaForm(request.POST)
        if form.is_valid():
            try:
                baixar_conta_receber_service(conta, data_recebimento=form.cleaned_data['data_recebimento'])
                if form.cleaned_data.get('observacoes'):
                    conta.observacoes = '\n'.join(
                        value for value in [conta.observacoes, form.cleaned_data['observacoes']] if value
                    )
                    conta.save(update_fields=['observacoes', 'updated_at'])
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if exc.messages else 'Nao foi possivel receber esta conta.')
                return redirect('lista_contas_receber')
            messages.success(request, 'Recebimento registrado com sucesso.')
            return redirect('lista_contas_receber')
    else:
        form = ContaReceberBaixaForm(initial={'data_recebimento': timezone.localdate()})

    return render(request, 'financeiro/form_recebimento.html', {'form': form, 'conta': conta})


@financeiro_required
@require_POST
def cancelar_conta_receber(request, conta_id):
    conta = get_object_or_404(ContaReceber, id=conta_id)
    if conta.status != ContaReceber.STATUS_ABERTO:
        messages.error(request, 'Somente contas a receber em aberto podem ser canceladas.')
        return redirect('lista_contas_receber')
    conta.status = ContaReceber.STATUS_CANCELADO
    conta.save()
    messages.success(request, 'Conta a receber cancelada com sucesso.')
    return redirect('lista_contas_receber')


@financeiro_required
def nova_conta_pagar(request):
    if request.method == 'POST':
        form = ContaPagarForm(request.POST)
        ordem = form.data.get('ordem_compra') or None
        formset = ItemContaPagarOrdemCompraFormSet(request.POST, ordem=ordem, prefix='itens_oc')
        if form.is_valid() and formset.is_valid():
            if form.cleaned_data.get('ordem_compra') and not _formset_tem_itens_oc(formset):
                form.add_error('ordem_compra', 'Informe ao menos um item da OC.')
            else:
                conta = form.save()
                formset.instance = conta
                formset.save()
                conta.recalcular_valor_por_itens_oc()
                conta.save()
                messages.success(request, 'Conta a pagar cadastrada com sucesso.')
                return redirect('lista_contas_pagar')
    else:
        initial = {}
        obra_id = request.GET.get('obra')
        if obra_id:
            initial['obra'] = obra_id
        ordem_id = request.GET.get('ordem_compra')
        if ordem_id:
            initial['ordem_compra'] = ordem_id
        form = ContaPagarForm(initial=initial)
        formset = ItemContaPagarOrdemCompraFormSet(ordem=ordem_id, prefix='itens_oc')
    return render(
        request,
        'financeiro/form_conta.html',
        {'form': form, 'item_formset': formset, 'titulo': 'Nova Conta a Pagar'},
    )


@financeiro_required
def editar_conta_pagar(request, conta_id):
    conta = get_object_or_404(ContaPagar, id=conta_id)
    if request.method == 'POST':
        form = ContaPagarForm(request.POST, instance=conta)
        ordem = form.data.get('ordem_compra') or None
        formset = ItemContaPagarOrdemCompraFormSet(request.POST, instance=conta, ordem=ordem, prefix='itens_oc')
        if form.is_valid() and formset.is_valid():
            if form.cleaned_data.get('ordem_compra') and not _formset_tem_itens_oc(formset):
                form.add_error('ordem_compra', 'Informe ao menos um item da OC.')
            else:
                conta = form.save()
                formset.save()
                conta.recalcular_valor_por_itens_oc()
                conta.save()
                messages.success(request, 'Conta a pagar atualizada com sucesso.')
                return redirect('lista_contas_pagar')
    else:
        form = ContaPagarForm(instance=conta)
        formset = ItemContaPagarOrdemCompraFormSet(instance=conta, ordem=conta.ordem_compra, prefix='itens_oc')
    return render(
        request,
        'financeiro/form_conta.html',
        {'form': form, 'item_formset': formset, 'titulo': 'Editar Conta a Pagar'},
    )


@financeiro_required
def baixar_conta_pagar(request, conta_id):
    conta = get_object_or_404(ContaPagar, id=conta_id)
    if conta.status != ContaPagar.STATUS_ABERTO:
        messages.error(request, 'Somente contas a pagar em aberto podem ser pagas.')
        return redirect('lista_contas_pagar')

    if request.method == 'POST':
        form = ContaPagarBaixaForm(request.POST)
        if form.is_valid():
            baixar_conta_pagar_service(
                conta,
                data_pagamento=form.cleaned_data['data_pagamento'],
                valor_pago=form.cleaned_data['valor_pago'],
            )
            if form.cleaned_data.get('observacoes'):
                conta.observacoes = '\n'.join(
                    value for value in [conta.observacoes, form.cleaned_data['observacoes']] if value
                )
                conta.save(update_fields=['observacoes', 'updated_at'])
            messages.success(request, 'Pagamento registrado com sucesso.')
            return redirect('lista_contas_pagas')
    else:
        form = ContaPagarBaixaForm(
            initial={
                'data_pagamento': timezone.localdate(),
                'valor_pago': conta.valor,
            }
        )

    return render(request, 'financeiro/form_pagamento.html', {'form': form, 'conta': conta})


@financeiro_required
def lista_centros_custo(request):
    centros = CentroCusto.objects.all()
    return render(request, 'financeiro/lista_centros_custo.html', {'centros': centros})


@financeiro_required
def lista_fornecedores(request):
    fornecedores = Fornecedor.objects.all()
    busca = request.GET.get('busca', '').strip()
    if busca:
        fornecedores = fornecedores.filter(
            Q(nome__icontains=busca)
            | Q(cpf_cnpj__icontains=busca)
            | Q(municipio__icontains=busca)
        )
    return render(request, 'financeiro/lista_fornecedores.html', {'fornecedores': fornecedores, 'busca': busca})


@financeiro_required
def novo_fornecedor(request):
    if request.method == 'POST':
        form = FornecedorForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fornecedor cadastrado com sucesso.')
            return redirect('lista_fornecedores')
    else:
        form = FornecedorForm()
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Novo Fornecedor'})


@financeiro_required
def editar_fornecedor(request, fornecedor_id):
    fornecedor = get_object_or_404(Fornecedor, id=fornecedor_id)
    if request.method == 'POST':
        form = FornecedorForm(request.POST, instance=fornecedor)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fornecedor atualizado com sucesso.')
            return redirect('lista_fornecedores')
    else:
        form = FornecedorForm(instance=fornecedor)
    return render(request, 'financeiro/form_conta.html', {'form': form, 'titulo': 'Editar Fornecedor'})


@financeiro_required
def excluir_fornecedor(request, fornecedor_id):
    fornecedor = get_object_or_404(Fornecedor, id=fornecedor_id)
    detalhe = (
        'Os lancamentos e ordens ja criados nao serao apagados. '
        'Eles manterao os dados copiados do fornecedor, mas perderao o vinculo com este cadastro central.'
    )
    if request.method == 'POST':
        nome = fornecedor.nome
        fornecedor.delete()
        messages.success(request, f'Fornecedor "{nome}" excluido com sucesso.')
        return redirect('lista_fornecedores')
    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir fornecedor',
            'mensagem': f'Deseja excluir o fornecedor "{fornecedor}"?',
            'detalhe': detalhe,
            'confirmar_label': 'Excluir fornecedor',
            'cancelar_href': reverse('lista_fornecedores'),
        },
    )


@financeiro_required
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


@financeiro_required
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


@financeiro_required
def relatorio_financeiro(request):
    form, receber, pagar = _filtrar_contas(request)
    ordenacao = form.cleaned_data.get('ordenacao') if form.is_valid() else 'data_asc'
    agrupamento = form.cleaned_data.get('agrupamento') if form.is_valid() else ''
    eventos = _ordenar_eventos(_eventos_fluxo(receber, pagar), ordenacao)
    grupos = _agrupar_eventos(eventos, agrupamento)
    contexto = {
        'filtro_form': form,
        'eventos': eventos,
        'grupos_eventos': grupos,
        'total_eventos': len(eventos),
        'ordenacao_atual': ordenacao,
        'agrupamento_atual': agrupamento,
        **_resumo(receber, pagar),
    }
    return render(request, 'financeiro/relatorio.html', contexto)


@financeiro_required
def relatorio_financeiro_pdf(request):
    form, receber, pagar = _filtrar_contas(request)
    ordenacao = form.cleaned_data.get('ordenacao') if form.is_valid() else 'data_asc'
    agrupamento = form.cleaned_data.get('agrupamento') if form.is_valid() else ''
    eventos = _ordenar_eventos(_eventos_fluxo(receber, pagar), ordenacao)
    grupos = _agrupar_eventos(eventos, agrupamento)
    resumo = _resumo(receber, pagar)
    filtros = request.GET.urlencode()
    response = HttpResponse(
        _financial_report_pdf(grupos, resumo, filtros, ordenacao, agrupamento),
        content_type='application/pdf',
    )
    response['Content-Disposition'] = 'inline; filename="relatorio_financeiro.pdf"'
    return response
