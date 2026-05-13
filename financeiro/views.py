from collections import defaultdict
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db import DatabaseError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from .forms import (
    CentroCustoForm,
    ContaPagarForm,
    ContaReceberForm,
    FinanceiroFiltroForm,
    FornecedorForm,
    ImportarCredoresSiengeForm,
    ItemContaPagarOrdemCompraFormSet,
)
from .importadores import decodificar_csv_upload, importar_contas_pagar_credores_csv, importar_contas_pagas_credores_csv
from .models import CentroCusto, ContaPagar, ContaReceber, Fornecedor


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
                'valor': -conta.valor_pago_efetivo if conta.status == ContaPagar.STATUS_PAGO else -conta.valor,
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


def _financial_report_background():
    bg_path = Path(settings.BASE_DIR) / 'static' / 'propostas' / 'reference' / 'page_frame.png'
    if bg_path.exists():
        return Image.open(bg_path).convert('RGB')
    return Image.new('RGB', (1653, 2338), 'white')


def _financial_report_pdf(eventos, resumo, filtros):
    page_h = 2338
    margin_x = 150
    top_y = 360
    row_h = 44
    first_table_y = 760
    rows_per_page = 28
    pages = []
    chunks = [eventos[i : i + rows_per_page] for i in range(0, len(eventos), rows_per_page)] or [[]]

    title_font = _pdf_font(34, True)
    small_font = _pdf_font(18)
    label_font = _pdf_font(18, True)
    head_font = _pdf_font(16, True)
    cell_font = _pdf_font(15)
    dark = (39, 45, 48)
    muted = (94, 103, 107)
    line = (204, 212, 216)
    header_fill = (239, 243, 244)
    positive = (42, 111, 84)
    negative = (176, 55, 49)

    for page_index, chunk in enumerate(chunks, start=1):
        image = _financial_report_background()
        draw = ImageDraw.Draw(image)

        draw.text((margin_x, top_y), 'RELATÓRIO FINANCEIRO', font=title_font, fill=dark)
        draw.text((margin_x, top_y + 46), f'Emitido em {date.today().strftime("%d/%m/%Y")}', font=small_font, fill=muted)
        draw.text((margin_x, top_y + 76), f'Filtros: {filtros or "sem filtros"}', font=small_font, fill=muted)

        summary_y = top_y + 130
        cards = [
            ('A receber aberto', resumo['total_receber_aberto'], positive),
            ('A pagar aberto', resumo['total_pagar_aberto'], negative),
            ('Saldo previsto', resumo['saldo_previsto'], positive if resumo['saldo_previsto'] >= 0 else negative),
            ('Saldo realizado', resumo['saldo_realizado'], positive if resumo['saldo_realizado'] >= 0 else negative),
        ]
        card_w = 315
        for idx, (label, value, color) in enumerate(cards):
            x = margin_x + idx * (card_w + 22)
            draw.rounded_rectangle((x, summary_y, x + card_w, summary_y + 100), radius=8, fill=(250, 251, 251), outline=line, width=2)
            draw.text((x + 18, summary_y + 18), label, font=small_font, fill=muted)
            draw.text((x + 18, summary_y + 52), _format_currency_br(value), font=label_font, fill=color)

        table_y = first_table_y
        columns = [
            ('Data', 110, 'left'),
            ('Tipo', 90, 'center'),
            ('Descrição', 330, 'left'),
            ('Cliente/Fornecedor', 260, 'left'),
            ('Obra/Centro', 270, 'left'),
            ('Status', 130, 'center'),
            ('Valor', 160, 'right'),
        ]
        x = margin_x
        draw.rounded_rectangle((margin_x, table_y, margin_x + sum(col[1] for col in columns), table_y + row_h), radius=6, fill=header_fill, outline=line, width=1)
        for label, width, align in columns:
            _draw_table_cell(draw, label, (x, table_y, x + width, table_y + row_h), head_font, dark, align)
            x += width

        y = table_y + row_h
        for idx, evento in enumerate(chunk):
            row_fill = (255, 255, 255) if idx % 2 == 0 else (248, 250, 250)
            draw.rectangle((margin_x, y, margin_x + sum(col[1] for col in columns), y + row_h), fill=row_fill, outline=line, width=1)
            destino = evento['obra'] or evento['centro_custo'] or '-'
            values = [
                evento['data'].strftime('%d/%m/%Y'),
                evento['tipo'],
                evento['descricao'],
                evento['pessoa'],
                destino,
                evento['status'],
                _format_currency_br(evento['valor']),
            ]
            x = margin_x
            for (label, width, align), value in zip(columns, values):
                color = positive if label == 'Valor' and evento['valor'] >= 0 else negative if label == 'Valor' else dark
                _draw_table_cell(draw, value, (x, y, x + width, y + row_h), cell_font, color, align)
                x += width
            y += row_h

        draw.text((margin_x, page_h - 170), f'Página {page_index} de {len(chunks)}', font=small_font, fill=muted)
        pages.append(image)

    buffer = BytesIO()
    pages[0].save(buffer, 'PDF', resolution=150, save_all=True, append_images=pages[1:])
    return buffer.getvalue()


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
    contas = _base_pagar().filter(status=ContaPagar.STATUS_ABERTO)
    return render(
        request,
        'financeiro/lista_contas_pagar.html',
        {
            'contas': contas,
            'titulo': 'Contas a Pagar',
            'descricao': 'Despesas em aberto para baixa ou cancelamento em massa.',
            'mostrar_acoes_massa': True,
        },
    )


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


def lista_contas_pagas(request):
    contas = _base_pagar().filter(status=ContaPagar.STATUS_PAGO).order_by('-data_pagamento', '-id')
    return render(
        request,
        'financeiro/lista_contas_pagar.html',
        {
            'contas': contas,
            'titulo': 'Contas Pagas',
            'descricao': 'Historico das despesas ja baixadas.',
            'mostrar_acoes_massa': False,
        },
    )


def lista_contas_pagar_canceladas(request):
    contas = _base_pagar().filter(status=ContaPagar.STATUS_CANCELADO).order_by('-updated_at', '-id')
    return render(
        request,
        'financeiro/lista_contas_pagar.html',
        {
            'contas': contas,
            'titulo': 'Contas Canceladas',
            'descricao': 'Despesas canceladas e retiradas da lista principal.',
            'mostrar_acoes_massa': False,
        },
    )


def acao_massa_contas_pagar(request):
    if request.method != 'POST':
        return redirect('lista_contas_pagar')

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
        'total_eventos': len(eventos),
        **_resumo(receber, pagar),
    }
    return render(request, 'financeiro/relatorio.html', contexto)


def relatorio_financeiro_pdf(request):
    form, receber, pagar = _filtrar_contas(request)
    eventos = _eventos_fluxo(receber, pagar)
    resumo = _resumo(receber, pagar)
    filtros = request.GET.urlencode()
    response = HttpResponse(_financial_report_pdf(eventos, resumo, filtros), content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="relatorio_financeiro.pdf"'
    return response
