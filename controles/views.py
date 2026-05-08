from decimal import Decimal
from io import BytesIO
from pathlib import Path
import textwrap
import unicodedata

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from PIL import Image, ImageDraw, ImageFont

from financeiro.models import ContaPagar, Fornecedor

from .forms import (
    ApontamentoMaquinaLocacaoForm,
    BaixarLocacaoEquipamentoForm,
    BombonaCombustivelForm,
    ContratoConcretagemForm,
    EquipamentoLocadoCatalogoForm,
    FornecedorMaquinaLocacaoForm,
    FaturamentoConcretagemForm,
    LocacaoEquipamentoForm,
    LocadoraEquipamentoForm,
    MaquinaLocacaoCatalogoForm,
    NotaFiscalCombustivelForm,
    NotaFiscalLocacaoMaquinaForm,
    NotaFiscalOrdemCompraGeralForm,
    OrcamentoRadarObraForm,
    OrdemCompraCombustivelForm,
    OrdemCompraGeralForm,
    ItemOrdemCompraGeralFormSet,
    OrdemServicoLocacaoMaquinaForm,
    RegistroAbastecimentoForm,
    SolicitarRetiradaEquipamentoForm,
    SolicitanteConcretagemForm,
    VeiculoMaquinaForm,
)
from .models import (
    ApontamentoMaquinaLocacao,
    BombonaCombustivel,
    ContratoConcretagem,
    EquipamentoLocadoCatalogo,
    FornecedorMaquinaLocacao,
    FaturamentoConcretagem,
    LocacaoEquipamento,
    LocadoraEquipamento,
    MaquinaLocacaoCatalogo,
    NotaFiscalCombustivel,
    NotaFiscalLocacaoMaquina,
    NotaFiscalOrdemCompraGeral,
    OrcamentoRadarObra,
    OrdemCompraCombustivel,
    OrdemCompraGeral,
    OrdemServicoLocacaoMaquina,
    RegistroAbastecimento,
    SolicitanteConcretagem,
    VeiculoMaquina,
)
def _pdf_escape(value):
    text = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii')
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _build_simple_pdf(lines_by_page):
    objects = []

    def add_object(content):
        objects.append(content)
        return len(objects)

    font_id = add_object('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')

    page_ids = []
    content_ids = []
    pages_id_placeholder = None

    for lines in lines_by_page:
        content_stream = ['BT', '/F1 10 Tf', '40 555 Td', '14 TL']
        for index, line in enumerate(lines):
            if index == 0:
                content_stream.append(f'({_pdf_escape(line)}) Tj')
            else:
                content_stream.append(f'T* ({_pdf_escape(line)}) Tj')
        content_stream.append('ET')
        stream = '\n'.join(content_stream)
        content_id = add_object(f'<< /Length {len(stream.encode("latin-1"))} >>\nstream\n{stream}\nendstream')
        content_ids.append(content_id)
        page_ids.append(
            add_object(
                '<< /Type /Page /Parent {pages} 0 R /MediaBox [0 0 842 595] '
                f'/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>'
            )
        )

    kids = ' '.join(f'{page_id} 0 R' for page_id in page_ids)
    pages_id = add_object(f'<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>')

    for page_id in page_ids:
        objects[page_id - 1] = objects[page_id - 1].replace('{pages}', str(pages_id))

    catalog_id = add_object(f'<< /Type /Catalog /Pages {pages_id} 0 R >>')

    buffer = BytesIO()
    buffer.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]
    for index, content in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f'{index} 0 obj\n{content}\nendobj\n'.encode('latin-1'))
    xref_position = buffer.tell()
    buffer.write(f'xref\n0 {len(objects) + 1}\n'.encode('latin-1'))
    buffer.write(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        buffer.write(f'{offset:010d} 00000 n \n'.encode('latin-1'))
    buffer.write(
        (
            f'trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n'
            f'startxref\n{xref_position}\n%%EOF'
        ).encode('latin-1')
    )
    return buffer.getvalue()


def _format_date(value):
    if not value:
        return '-'
    return value.strftime('%d/%m/%Y')


def _format_money(value):
    return f'R$ {value:.2f}'


def _font(size, bold=False):
    candidates = [
        Path(settings.BASE_DIR) / 'static' / 'fonts' / ('Arial Bold.ttf' if bold else 'Arial.ttf'),
        Path('C:/Windows/Fonts') / ('arialbd.ttf' if bold else 'arial.ttf'),
        Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _clean_pdf_text(value):
    return unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii')


def _draw_wrapped(draw, text, xy, font, fill, width, line_spacing=8):
    x, y = xy
    text = _clean_pdf_text(text or '-')
    avg_char_width = max(font.getlength('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz') / 52, 1)
    max_chars = max(int(width / avg_char_width), 12)
    lines = []
    for paragraph in text.splitlines() or ['-']:
        lines.extend(textwrap.wrap(paragraph, width=max_chars) or [''])
    line_height = font.getbbox('Ag')[3] - font.getbbox('Ag')[1] + line_spacing
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _draw_section_title(draw, title, x, y, w):
    teal = (4, 95, 101)
    draw.rounded_rectangle((x, y, x + w, y + 38), radius=6, fill=teal)
    draw.text((x + 16, y + 9), _clean_pdf_text(title).upper(), font=_font(18, True), fill=(255, 255, 255))
    return y + 52


def _draw_key_value_grid(draw, rows, x, y, w, columns=2):
    label_font = _font(14, True)
    value_font = _font(15)
    border = (211, 218, 221)
    label = (88, 99, 105)
    text = (44, 49, 52)
    col_w = w / columns
    row_h = 70
    for index, (key, value) in enumerate(rows):
        col = index % columns
        row = index // columns
        x0 = int(x + col * col_w)
        y0 = int(y + row * row_h)
        x1 = int(x0 + col_w)
        y1 = y0 + row_h
        draw.rectangle((x0, y0, x1, y1), outline=border, width=1)
        draw.text((x0 + 14, y0 + 10), _clean_pdf_text(key).upper(), font=label_font, fill=label)
        _draw_wrapped(draw, value, (x0 + 14, y0 + 34), value_font, text, int(col_w - 28), line_spacing=4)
    return y + (((len(rows) + columns - 1) // columns) * row_h) + 26


def _draw_table(draw, headers, rows, x, y, widths):
    header_font = _font(14, True)
    value_font = _font(14)
    header_fill = (236, 241, 242)
    border = (194, 202, 206)
    text = (43, 48, 51)
    row_h = 46
    x_cursor = x
    for header, width in zip(headers, widths):
        draw.rectangle((x_cursor, y, x_cursor + width, y + row_h), fill=header_fill, outline=border, width=1)
        draw.text((x_cursor + 10, y + 14), _clean_pdf_text(header).upper(), font=header_font, fill=text)
        x_cursor += width
    y += row_h
    for row in rows:
        x_cursor = x
        for value, width in zip(row, widths):
            draw.rectangle((x_cursor, y, x_cursor + width, y + row_h), outline=border, width=1)
            _draw_wrapped(draw, value, (x_cursor + 10, y + 12), value_font, text, width - 20, line_spacing=3)
            x_cursor += width
        y += row_h
    return y + 28


def _draw_notes_box(draw, title, value, x, y, w):
    y = _draw_section_title(draw, title, x, y, w)
    border = (211, 218, 221)
    draw.rectangle((x, y, x + w, y + 150), outline=border, width=1)
    _draw_wrapped(draw, value or '-', (x + 16, y + 16), _font(15), (44, 49, 52), w - 32, line_spacing=6)
    return y + 176


def _report_background():
    bg_path = Path(settings.BASE_DIR) / 'static' / 'propostas' / 'reference' / 'page_frame.png'
    if bg_path.exists():
        return Image.open(bg_path).convert('RGB')
    return Image.new('RGB', (1653, 2338), 'white')


def _report_pdf_response(image, filename):
    buffer = BytesIO()
    image.save(buffer, 'PDF', resolution=150)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}.pdf"'
    return response


def _draw_report_heading(draw, title, number, date_text):
    x = 220
    w = 1213
    y = 405
    draw.rounded_rectangle((x, y, x + w, y + 92), radius=10, fill=(250, 251, 251), outline=(207, 216, 220), width=2)
    draw.text((x + 24, y + 18), _clean_pdf_text(title).upper(), font=_font(28, True), fill=(41, 46, 48))
    draw.text((x + 24, y + 56), f'Numero: {_clean_pdf_text(number)}', font=_font(17), fill=(92, 101, 105))
    draw.text((x + w - 260, y + 56), f'Data: {_clean_pdf_text(date_text)}', font=_font(17), fill=(92, 101, 105))
    return x, y + 132, w


def _queryset_locacoes_filtradas(request):
    locacoes = LocacaoEquipamento.objects.select_related('equipamento', 'locadora', 'obra').all()

    obra_id = request.GET.get('obra', '').strip()
    locadora_id = request.GET.get('locadora', '').strip()
    status = request.GET.get('status', '').strip()
    busca = request.GET.get('busca', '').strip()

    if obra_id.isdigit():
        locacoes = locacoes.filter(obra_id=obra_id)
    if locadora_id.isdigit():
        locacoes = locacoes.filter(locadora_id=locadora_id)
    if status in {choice[0] for choice in LocacaoEquipamento.STATUS_CHOICES}:
        locacoes = locacoes.filter(status=status)
    if busca:
        locacoes = locacoes.filter(
            Q(equipamento__nome__icontains=busca)
            | Q(observacoes__icontains=busca)
            | Q(obra__nome_obra__icontains=busca)
            | Q(locadora__nome__icontains=busca)
        )

    filtros = {
        'obra': obra_id,
        'locadora': locadora_id,
        'status': status,
        'busca': busca,
    }
    return locacoes.order_by('-data_locacao', '-id'), filtros


def _resumo_obras(locacoes):
    contadores = {}
    for locacao in locacoes:
        obra_id = locacao.obra_id
        if obra_id not in contadores:
            contadores[obra_id] = {
                'obra': locacao.obra,
                'total': 0,
                'abertas': 0,
            }
        contadores[obra_id]['total'] += 1
        if locacao.em_aberto:
            contadores[obra_id]['abertas'] += 1
    return sorted(contadores.values(), key=lambda item: (item['obra'].nome_obra.lower(),))


def _registrar_historico_ordem(ordem, evento, descricao, status_anterior='', status_novo=''):
    ordem.historico.create(
        evento=evento,
        descricao=descricao,
        status_anterior=status_anterior or '',
        status_novo=status_novo or '',
    )


def _registrar_historico_maquina(ordem, evento, descricao, status_anterior='', status_novo=''):
    ordem.historico.create(
        evento=evento,
        descricao=descricao,
        status_anterior=status_anterior or '',
        status_novo=status_novo or '',
    )


def _fornecedores_json():
    return [
        {
            'id': fornecedor.id,
            'nome': fornecedor.nome,
            'cpf_cnpj': fornecedor.cpf_cnpj,
            'ie_identidade': fornecedor.ie_identidade,
            'endereco': fornecedor.endereco,
            'municipio': fornecedor.municipio,
            'cep': fornecedor.cep,
            'telefone': fornecedor.telefone,
        }
        for fornecedor in Fornecedor.objects.filter(ativo=True).order_by('nome')
    ]


def home(request):
    totais = {
        'veiculos': VeiculoMaquina.objects.count(),
        'abastecimentos': RegistroAbastecimento.objects.count(),
        'ordens_compra_gerais': OrdemCompraGeral.objects.count(),
        'ordens_compra_gerais_abertas': OrdemCompraGeral.objects.exclude(
            status__in=['encerrada', 'cancelada'],
        ).count(),
        'ordens_combustivel': OrdemCompraCombustivel.objects.count(),
        'ordens_combustivel_abertas': OrdemCompraCombustivel.objects.exclude(
            status__in=['encerrada', 'cancelada'],
        ).count(),
        'bombonas_combustivel': BombonaCombustivel.objects.count(),
        'locacoes_abertas': LocacaoEquipamento.objects.filter(
            status__in=['locado', 'retirada_solicitada'],
        ).count(),
        'ordens_maquinas': OrdemServicoLocacaoMaquina.objects.count(),
        'ordens_maquinas_abertas': OrdemServicoLocacaoMaquina.objects.exclude(
            status__in=['encerrada', 'cancelada'],
        ).count(),
        'orcamentos_aguardando': OrcamentoRadarObra.objects.filter(situacao='aguardando_resposta').count(),
        'contratos_concretagem': ContratoConcretagem.objects.filter(status='ativo').count(),
        'total_abastecido': sum(
            RegistroAbastecimento.objects.values_list('valor_total', flat=True),
            Decimal('0'),
        ),
    }
    return render(request, 'controles/home.html', totais)


def lista_abastecimentos(request):
    abastecimentos = RegistroAbastecimento.objects.select_related('veiculo').all()
    total_abastecido = sum((registro.valor_total for registro in abastecimentos), Decimal('0'))
    return render(
        request,
        'controles/lista_abastecimentos.html',
        {
            'abastecimentos': abastecimentos,
            'total_abastecido': total_abastecido,
        },
    )


def novo_abastecimento(request):
    if request.method == 'POST':
        form = RegistroAbastecimentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Abastecimento registrado com sucesso.')
            return redirect('lista_abastecimentos')
    else:
        form = RegistroAbastecimentoForm()

    return render(
        request,
        'controles/form_abastecimento.html',
        {'form': form, 'titulo': 'Novo Abastecimento'},
    )


def lista_ordens_compra_gerais(request):
    ordens = OrdemCompraGeral.objects.prefetch_related('itens')
    status = request.GET.get('status', '').strip()
    busca = request.GET.get('busca', '').strip()

    if status in {choice[0] for choice in OrdemCompraGeral.STATUS_CHOICES}:
        ordens = ordens.filter(status=status)
    if busca:
        ordens = ordens.filter(
            Q(numero__icontains=busca)
            | Q(fornecedor__icontains=busca)
            | Q(comprador__icontains=busca)
            | Q(fornecedor_cpf_cnpj__icontains=busca)
        )

    return render(
        request,
        'controles/lista_ordens_compra_gerais.html',
        {
            'ordens': ordens,
            'status_choices': OrdemCompraGeral.STATUS_CHOICES,
            'filtros': {'status': status, 'busca': busca},
        },
    )


def _salvar_ordem_compra_geral(request, ordem=None):
    if request.method == 'POST':
        form = OrdemCompraGeralForm(request.POST, instance=ordem)
        if form.is_valid():
            ordem_salva = form.save()
            formset = ItemOrdemCompraGeralFormSet(request.POST, instance=ordem_salva)
            if formset.is_valid():
                formset.save()
                messages.success(request, 'Ordem de compra salva com sucesso.')
                return form, formset, redirect('detalhe_ordem_compra_geral', ordem_id=ordem_salva.id)
        else:
            formset = ItemOrdemCompraGeralFormSet(request.POST, instance=ordem)
    else:
        form = OrdemCompraGeralForm(instance=ordem)
        formset = ItemOrdemCompraGeralFormSet(instance=ordem)
    return form, formset, None


def nova_ordem_compra_geral(request):
    form, formset, response = _salvar_ordem_compra_geral(request)
    if response:
        return response
    return render(
        request,
        'controles/form_ordem_compra_geral.html',
        {
            'form': form,
            'formset': formset,
            'titulo': 'Nova Ordem de Compra',
            'fornecedores_json': _fornecedores_json(),
        },
    )


def detalhe_ordem_compra_geral(request, ordem_id):
    ordem = get_object_or_404(
        OrdemCompraGeral.objects.select_related('obra', 'centro_custo').prefetch_related(
            'itens__notas_fiscais',
            'notas_fiscais__item',
            'notas_fiscais__conta_pagar',
        ),
        id=ordem_id,
    )
    return render(request, 'controles/detalhe_ordem_compra_geral.html', {'ordem': ordem})


def editar_ordem_compra_geral(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraGeral, id=ordem_id)
    form, formset, response = _salvar_ordem_compra_geral(request, ordem)
    if response:
        return response
    return render(
        request,
        'controles/form_ordem_compra_geral.html',
        {
            'form': form,
            'formset': formset,
            'titulo': 'Editar Ordem de Compra',
            'ordem': ordem,
            'fornecedores_json': _fornecedores_json(),
        },
    )


def nova_nf_ordem_compra_geral(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraGeral, id=ordem_id)
    messages.info(request, 'Lance a conta a pagar no financeiro e selecione a OC para vincular a NF automaticamente.')
    return redirect(f'{reverse("nova_conta_pagar")}?ordem_compra={ordem.id}')


def editar_nf_ordem_compra_geral(request, nota_id):
    nota = get_object_or_404(NotaFiscalOrdemCompraGeral.objects.select_related('ordem'), id=nota_id)
    if request.method == 'POST':
        form = NotaFiscalOrdemCompraGeralForm(request.POST, instance=nota, ordem=nota.ordem)
        if form.is_valid():
            form.save()
            messages.success(request, 'Nota da OC atualizada com sucesso.')
            return redirect('detalhe_ordem_compra_geral', ordem_id=nota.ordem_id)
    else:
        form = NotaFiscalOrdemCompraGeralForm(instance=nota, ordem=nota.ordem)
    return render(
        request,
        'controles/form_nf_ordem_compra_geral.html',
        {'form': form, 'ordem': nota.ordem, 'nota': nota, 'titulo': 'Editar NF da OC'},
    )


def gerar_conta_pagar_nf_ordem_compra(request, nota_id):
    nota = get_object_or_404(
        NotaFiscalOrdemCompraGeral.objects.select_related('ordem', 'item', 'conta_pagar'),
        id=nota_id,
    )
    if nota.conta_pagar_id:
        messages.info(request, 'Esta NF ja possui conta a pagar vinculada.')
        return redirect('detalhe_ordem_compra_geral', ordem_id=nota.ordem_id)

    from financeiro.models import ItemContaPagarOrdemCompra

    conta = ContaPagar.objects.create(
        fornecedor=nota.ordem.fornecedor,
        fornecedor_cadastro=nota.ordem.fornecedor_cadastro,
        obra=nota.ordem.obra,
        centro_custo=nota.ordem.centro_custo,
        categoria=nota.ordem.categoria_despesa or 'material',
        descricao=f'NF {nota.numero} - OC {nota.ordem.numero} - {nota.item.descricao}',
        data_emissao=nota.data_emissao,
        data_vencimento=nota.data_vencimento or nota.data_emissao,
        valor=nota.valor_total,
        observacoes=f'Gerada a partir da OC {nota.ordem.numero}. {nota.observacoes}'.strip(),
    )
    ItemContaPagarOrdemCompra.objects.create(
        conta=conta,
        item_ordem_compra=nota.item,
        quantidade=nota.quantidade,
    )
    nota.conta_pagar = conta
    nota.status = NotaFiscalOrdemCompraGeral.STATUS_LANCADA_FINANCEIRO
    nota.save(update_fields=['conta_pagar', 'status', 'updated_at'])
    messages.success(request, 'Conta a pagar gerada a partir da NF da OC.')
    return redirect('detalhe_ordem_compra_geral', ordem_id=nota.ordem_id)


def ordem_compra_geral_pdf(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraGeral.objects.prefetch_related('itens'), id=ordem_id)
    image = _report_background()
    draw = ImageDraw.Draw(image)
    x, y, w = _draw_report_heading(draw, 'Ordem de compra', ordem.numero, _format_date(ordem.data_emissao))

    y = _draw_section_title(draw, 'Empresa compradora', x, y, w)
    y = _draw_key_value_grid(
        draw,
        [
            ('Razao social', ordem.empresa_razao_social),
            ('CNPJ', ordem.empresa_cnpj or '-'),
            ('Endereco', ordem.empresa_endereco or '-'),
            ('Comprador', ordem.comprador or '-'),
        ],
        x,
        y,
        w,
        columns=2,
    )

    y = _draw_section_title(draw, 'Fornecedor', x, y, w)
    y = _draw_key_value_grid(
        draw,
        [
            ('Fornecedor', ordem.fornecedor),
            ('CPF/CNPJ', ordem.fornecedor_cpf_cnpj or '-'),
            ('Endereco', ordem.fornecedor_endereco or '-'),
            ('Bairro', ordem.fornecedor_bairro or '-'),
            ('Cidade/UF', f'{ordem.fornecedor_cidade or "-"} / {ordem.fornecedor_uf or "-"}'),
            ('CEP', ordem.fornecedor_cep or '-'),
            ('Fone', ordem.fornecedor_fone or '-'),
            ('IE', ordem.fornecedor_ie or '-'),
        ],
        x,
        y,
        w,
        columns=2,
    )

    aviso = 'Nas notas fiscais e faturas e obrigatorio aparecer o numero desta ordem de compra.'
    draw.rounded_rectangle((x, y, x + w, y + 48), radius=6, fill=(255, 248, 230), outline=(228, 191, 92), width=1)
    _draw_wrapped(draw, aviso, (x + 16, y + 14), _font(16, True), (73, 60, 32), w - 32, line_spacing=4)
    y += 72

    rows = [
        [
            f'{item.item:02d}',
            item.descricao,
            f'{item.quantidade:.2f}',
            item.unidade,
            _format_money(item.valor_unitario),
            _format_money(item.valor_total),
            _format_date(item.data_entrega),
        ]
        for item in ordem.itens.all()
    ]
    y = _draw_section_title(draw, 'Itens', x, y, w)
    y = _draw_table(draw, ['Item', 'Descricao', 'Qtd', 'Un', 'Vlr.', 'Total', 'Entrega'], rows, x, y, [70, 420, 100, 70, 145, 160, 160])

    total_y = y
    draw.rounded_rectangle((x + w - 360, total_y, x + w, total_y + 58), radius=6, fill=(4, 95, 101))
    draw.text((x + w - 332, total_y + 16), f'TOTAL: {_format_money(ordem.total)}', font=_font(22, True), fill=(255, 255, 255))
    y = total_y + 86

    y = _draw_notes_box(draw, 'Condicoes de pagamento', ordem.condicoes_pagamento or '-', x, y, w)
    y = _draw_notes_box(draw, 'Observacoes', ordem.observacoes or '-', x, y, w)
    draw.text((x, y + 20), _clean_pdf_text(f'Comprador: {ordem.comprador or "-"}'), font=_font(17), fill=(43, 48, 51))
    draw.text((x, y + 66), '________________________________________', font=_font(17), fill=(43, 48, 51))
    draw.text((x, y + 92), _clean_pdf_text(ordem.comprador or 'Assinatura'), font=_font(15), fill=(43, 48, 51))

    return _report_pdf_response(image, f'OC {ordem.numero}'.replace('/', '-'))


def lista_ordens_combustivel(request):
    ordens = OrdemCompraCombustivel.objects.select_related('veiculo', 'bombona').prefetch_related('notas_fiscais')

    status = request.GET.get('status', '').strip()
    tipo_destino = request.GET.get('tipo_destino', '').strip()
    busca = request.GET.get('busca', '').strip()

    if status in {choice[0] for choice in OrdemCompraCombustivel.STATUS_CHOICES}:
        ordens = ordens.filter(status=status)
    if tipo_destino in {choice[0] for choice in OrdemCompraCombustivel.TIPO_DESTINO_CHOICES}:
        ordens = ordens.filter(tipo_destino=tipo_destino)
    if busca:
        ordens = ordens.filter(
            Q(numero__icontains=busca)
            | Q(fornecedor__icontains=busca)
            | Q(solicitante__icontains=busca)
            | Q(veiculo__placa__icontains=busca)
            | Q(veiculo__descricao__icontains=busca)
            | Q(bombona__identificacao__icontains=busca)
        )

    return render(
        request,
        'controles/lista_ordens_combustivel.html',
        {
            'ordens': ordens,
            'status_choices': OrdemCompraCombustivel.STATUS_CHOICES,
            'tipo_destino_choices': OrdemCompraCombustivel.TIPO_DESTINO_CHOICES,
            'filtros': {
                'status': status,
                'tipo_destino': tipo_destino,
                'busca': busca,
            },
        },
    )


def nova_ordem_combustivel(request):
    if request.method == 'POST':
        form = OrdemCompraCombustivelForm(request.POST)
        if form.is_valid():
            ordem = form.save()
            _registrar_historico_ordem(
                ordem,
                'Ordem criada',
                f'Ordem {ordem.numero} criada para {ordem.get_tipo_destino_display().lower()} {ordem.destino_display}.',
                '',
                ordem.status,
            )
            messages.success(request, 'Ordem de compra de combustivel criada com sucesso.')
            return redirect('detalhe_ordem_combustivel', ordem_id=ordem.id)
    else:
        form = OrdemCompraCombustivelForm()

    return render(
        request,
        'controles/form_ordem_combustivel.html',
        {'form': form, 'titulo': 'Nova Ordem de Combustivel'},
    )


def detalhe_ordem_combustivel(request, ordem_id):
    ordem = get_object_or_404(
        OrdemCompraCombustivel.objects.select_related('veiculo', 'bombona').prefetch_related(
            'notas_fiscais',
            'historico',
        ),
        id=ordem_id,
    )
    return render(request, 'controles/detalhe_ordem_combustivel.html', {'ordem': ordem})


def ordem_combustivel_pdf(request, ordem_id):
    ordem = get_object_or_404(
        OrdemCompraCombustivel.objects.select_related('veiculo', 'bombona'),
        id=ordem_id,
    )
    image = _report_background()
    draw = ImageDraw.Draw(image)
    x, y, w = _draw_report_heading(
        draw,
        'Ordem de compra de combustivel',
        ordem.numero,
        _format_date(ordem.data_ordem),
    )
    y = _draw_section_title(draw, 'Dados da ordem', x, y, w)
    y = _draw_key_value_grid(
        draw,
        [
            ('Fornecedor/Posto', ordem.fornecedor),
            ('Solicitante', ordem.solicitante or '-'),
            ('Status', ordem.get_status_display()),
            ('Destino', f'{ordem.get_tipo_destino_display()} - {ordem.destino_display}'),
        ],
        x,
        y,
        w,
    )
    y = _draw_section_title(draw, 'Item autorizado', x, y, w)
    y = _draw_table(
        draw,
        ['Descricao', 'Quantidade', 'Valor unitario', 'Total previsto'],
        [
            [
                f'Combustivel - {ordem.get_tipo_combustivel_display()}',
                f'{ordem.quantidade_litros:.2f} L',
                _format_money(ordem.valor_litro_previsto),
                _format_money(ordem.valor_total_previsto),
            ]
        ],
        x,
        y,
        [540, 210, 230, 233],
    )
    _draw_notes_box(draw, 'Observacoes', ordem.observacoes or '-', x, y, w)
    return _report_pdf_response(image, ordem.numero)


def editar_ordem_combustivel(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraCombustivel, id=ordem_id)
    status_anterior = ordem.status

    if request.method == 'POST':
        form = OrdemCompraCombustivelForm(request.POST, instance=ordem)
        if form.is_valid():
            ordem = form.save()
            if status_anterior != ordem.status:
                _registrar_historico_ordem(
                    ordem,
                    'Status alterado',
                    f'Status alterado de {status_anterior} para {ordem.status}.',
                    status_anterior,
                    ordem.status,
                )
            else:
                _registrar_historico_ordem(ordem, 'Ordem atualizada', 'Dados da ordem foram atualizados.')
            messages.success(request, 'Ordem de compra de combustivel atualizada com sucesso.')
            return redirect('detalhe_ordem_combustivel', ordem_id=ordem.id)
    else:
        form = OrdemCompraCombustivelForm(instance=ordem)

    return render(
        request,
        'controles/form_ordem_combustivel.html',
        {'form': form, 'titulo': 'Editar Ordem de Combustivel', 'ordem': ordem},
    )


def nova_nf_combustivel(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraCombustivel, id=ordem_id)

    if request.method == 'POST':
        form = NotaFiscalCombustivelForm(request.POST)
        if form.is_valid():
            nota = form.save(commit=False)
            nota.ordem = ordem
            nota.save()
            _registrar_historico_ordem(
                ordem,
                'NF adicionada',
                f'NF {nota.numero} adicionada com {nota.litros} litros e valor total R$ {nota.valor_total}.',
            )
            messages.success(request, 'Nota fiscal adicionada a ordem com sucesso.')
            return redirect('detalhe_ordem_combustivel', ordem_id=ordem.id)
    else:
        form = NotaFiscalCombustivelForm()

    return render(
        request,
        'controles/form_nf_combustivel.html',
        {'form': form, 'titulo': 'Nova NF de Combustivel', 'ordem': ordem},
    )


def editar_nf_combustivel(request, nota_id):
    nota = get_object_or_404(NotaFiscalCombustivel.objects.select_related('ordem'), id=nota_id)
    ordem = nota.ordem
    status_anterior = nota.status

    if request.method == 'POST':
        form = NotaFiscalCombustivelForm(request.POST, instance=nota)
        if form.is_valid():
            nota = form.save()
            descricao = f'NF {nota.numero} atualizada.'
            if status_anterior != nota.status:
                descricao = f'NF {nota.numero} teve status alterado de {status_anterior} para {nota.status}.'
            _registrar_historico_ordem(ordem, 'NF atualizada', descricao)
            messages.success(request, 'Nota fiscal de combustivel atualizada com sucesso.')
            return redirect('detalhe_ordem_combustivel', ordem_id=ordem.id)
    else:
        form = NotaFiscalCombustivelForm(instance=nota)

    return render(
        request,
        'controles/form_nf_combustivel.html',
        {'form': form, 'titulo': 'Editar NF de Combustivel', 'ordem': ordem, 'nota': nota},
    )


def lista_bombonas_combustivel(request):
    bombonas = BombonaCombustivel.objects.all()
    return render(request, 'controles/lista_bombonas_combustivel.html', {'bombonas': bombonas})


def nova_bombona_combustivel(request):
    if request.method == 'POST':
        form = BombonaCombustivelForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bombona cadastrada com sucesso.')
            return redirect('lista_bombonas_combustivel')
    else:
        form = BombonaCombustivelForm()

    return render(
        request,
        'controles/form_bombona_combustivel.html',
        {'form': form, 'titulo': 'Nova Bombona'},
    )


def editar_bombona_combustivel(request, bombona_id):
    bombona = get_object_or_404(BombonaCombustivel, id=bombona_id)

    if request.method == 'POST':
        form = BombonaCombustivelForm(request.POST, instance=bombona)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bombona atualizada com sucesso.')
            return redirect('lista_bombonas_combustivel')
    else:
        form = BombonaCombustivelForm(instance=bombona)

    return render(
        request,
        'controles/form_bombona_combustivel.html',
        {'form': form, 'titulo': 'Editar Bombona', 'bombona': bombona},
    )


def lista_veiculos(request):
    veiculos = VeiculoMaquina.objects.all()
    return render(request, 'controles/lista_veiculos.html', {'veiculos': veiculos})


def novo_veiculo(request):
    if request.method == 'POST':
        form = VeiculoMaquinaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Veiculo/maquina cadastrado com sucesso.')
            return redirect('lista_veiculos')
    else:
        form = VeiculoMaquinaForm()

    return render(
        request,
        'controles/form_veiculo.html',
        {'form': form, 'titulo': 'Novo Veiculo/Maquina'},
    )


def editar_veiculo(request, veiculo_id):
    veiculo = get_object_or_404(VeiculoMaquina, id=veiculo_id)

    if request.method == 'POST':
        form = VeiculoMaquinaForm(request.POST, instance=veiculo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Veiculo/maquina atualizado com sucesso.')
            return redirect('lista_veiculos')
    else:
        form = VeiculoMaquinaForm(instance=veiculo)

    return render(
        request,
        'controles/form_veiculo.html',
        {'form': form, 'titulo': 'Editar Veiculo/Maquina', 'veiculo': veiculo},
    )


def lista_ordens_locacao_maquinas(request):
    ordens = OrdemServicoLocacaoMaquina.objects.select_related(
        'obra',
        'fornecedor',
        'maquina',
    ).prefetch_related('apontamentos', 'notas_fiscais')

    obra_id = request.GET.get('obra', '').strip()
    fornecedor_id = request.GET.get('fornecedor', '').strip()
    status = request.GET.get('status', '').strip()
    busca = request.GET.get('busca', '').strip()

    if obra_id.isdigit():
        ordens = ordens.filter(obra_id=obra_id)
    if fornecedor_id.isdigit():
        ordens = ordens.filter(fornecedor_id=fornecedor_id)
    if status in {choice[0] for choice in OrdemServicoLocacaoMaquina.STATUS_CHOICES}:
        ordens = ordens.filter(status=status)
    if busca:
        ordens = ordens.filter(
            Q(numero__icontains=busca)
            | Q(obra__nome_obra__icontains=busca)
            | Q(fornecedor__nome__icontains=busca)
            | Q(maquina__nome__icontains=busca)
            | Q(solicitante__icontains=busca)
            | Q(responsavel__icontains=busca)
        )

    return render(
        request,
        'controles/lista_ordens_locacao_maquinas.html',
        {
            'ordens': ordens,
            'status_choices': OrdemServicoLocacaoMaquina.STATUS_CHOICES,
            'filtros': {
                'obra': obra_id,
                'fornecedor': fornecedor_id,
                'status': status,
                'busca': busca,
            },
            'obras_filtro': OrdemServicoLocacaoMaquina.objects.select_related('obra').values_list(
                'obra_id',
                'obra__nome_obra',
            ).distinct().order_by('obra__nome_obra'),
            'fornecedores_filtro': FornecedorMaquinaLocacao.objects.filter(ordens__isnull=False).distinct().order_by('nome'),
        },
    )


def nova_ordem_locacao_maquina(request):
    if request.method == 'POST':
        form = OrdemServicoLocacaoMaquinaForm(request.POST)
        if form.is_valid():
            ordem = form.save()
            _registrar_historico_maquina(
                ordem,
                'OS criada',
                f'OS {ordem.numero} criada para {ordem.maquina} na obra {ordem.obra}.',
                '',
                ordem.status,
            )
            messages.success(request, 'OS de locacao de maquina criada com sucesso.')
            return redirect('detalhe_ordem_locacao_maquina', ordem_id=ordem.id)
    else:
        form = OrdemServicoLocacaoMaquinaForm()

    return render(
        request,
        'controles/form_ordem_locacao_maquina.html',
        {'form': form, 'titulo': 'Nova OS de Locacao de Maquina'},
    )


def detalhe_ordem_locacao_maquina(request, ordem_id):
    ordem = get_object_or_404(
        OrdemServicoLocacaoMaquina.objects.select_related('obra', 'fornecedor', 'maquina').prefetch_related(
            'apontamentos',
            'notas_fiscais',
            'historico',
        ),
        id=ordem_id,
    )
    return render(request, 'controles/detalhe_ordem_locacao_maquina.html', {'ordem': ordem})


def ordem_locacao_maquina_pdf(request, ordem_id):
    ordem = get_object_or_404(
        OrdemServicoLocacaoMaquina.objects.select_related('obra', 'fornecedor', 'maquina'),
        id=ordem_id,
    )
    image = _report_background()
    draw = ImageDraw.Draw(image)
    x, y, w = _draw_report_heading(
        draw,
        'Ordem de servico de locacao de maquina',
        ordem.numero,
        _format_date(ordem.data_solicitacao),
    )
    y = _draw_section_title(draw, 'Dados da OS', x, y, w)
    y = _draw_key_value_grid(
        draw,
        [
            ('Obra', ordem.obra),
            ('Fornecedor', ordem.fornecedor),
            ('Maquina', ordem.maquina),
            ('Status', ordem.get_status_display()),
            ('Solicitante', ordem.solicitante or '-'),
            ('Responsavel', ordem.responsavel or '-'),
            ('Tipo de cobranca', ordem.get_tipo_cobranca_display()),
            ('Condicoes', f'Operador: {"Sim" if ordem.operador_incluso else "Nao"} | Combustivel: {"Sim" if ordem.combustivel_incluso else "Nao"}'),
        ],
        x,
        y,
        w,
    )
    y = _draw_section_title(draw, 'Prazos e operacao', x, y, w)
    y = _draw_table(
        draw,
        ['Periodo previsto', 'Mobilizacao', 'Inicio operacao', 'Desmobilizacao'],
        [
            [
                f'{_format_date(ordem.data_prevista_inicio)} a {_format_date(ordem.data_prevista_fim)}',
                _format_date(ordem.data_mobilizacao),
                _format_date(ordem.data_inicio_operacao),
                _format_date(ordem.data_desmobilizacao),
            ]
        ],
        x,
        y,
        [330, 290, 290, 303],
    )
    y = _draw_section_title(draw, 'Valores contratados', x, y, w)
    y = _draw_table(
        draw,
        ['Item', 'Valor/Info', 'Item', 'Valor/Info'],
        [
            ['Valor hora', _format_money(ordem.valor_hora), 'Valor diaria', _format_money(ordem.valor_diaria)],
            ['Valor mensal', _format_money(ordem.valor_mensal), 'Franquia horas', f'{ordem.franquia_horas:.2f}'],
            ['Mobilizacao', _format_money(ordem.valor_mobilizacao), 'Desmobilizacao', _format_money(ordem.valor_desmobilizacao)],
            [
                'Valor previsto manual',
                _format_money(ordem.valor_previsto_manual) if ordem.valor_previsto_manual is not None else '-',
                'Tipo cobranca',
                ordem.get_tipo_cobranca_display(),
            ],
        ],
        x,
        y,
        [310, 290, 310, 303],
    )
    _draw_notes_box(draw, 'Observacoes', ordem.observacoes or '-', x, y, w)
    return _report_pdf_response(image, ordem.numero)


def editar_ordem_locacao_maquina(request, ordem_id):
    ordem = get_object_or_404(OrdemServicoLocacaoMaquina, id=ordem_id)
    status_anterior = ordem.status

    if request.method == 'POST':
        form = OrdemServicoLocacaoMaquinaForm(request.POST, instance=ordem)
        if form.is_valid():
            ordem = form.save()
            if status_anterior != ordem.status:
                _registrar_historico_maquina(
                    ordem,
                    'Status alterado',
                    f'Status alterado de {status_anterior} para {ordem.status}.',
                    status_anterior,
                    ordem.status,
                )
            else:
                _registrar_historico_maquina(ordem, 'OS atualizada', 'Dados da OS foram atualizados.')
            messages.success(request, 'OS de locacao de maquina atualizada com sucesso.')
            return redirect('detalhe_ordem_locacao_maquina', ordem_id=ordem.id)
    else:
        form = OrdemServicoLocacaoMaquinaForm(instance=ordem)

    return render(
        request,
        'controles/form_ordem_locacao_maquina.html',
        {'form': form, 'titulo': 'Editar OS de Locacao de Maquina', 'ordem': ordem},
    )


def novo_apontamento_maquina(request, ordem_id):
    ordem = get_object_or_404(OrdemServicoLocacaoMaquina, id=ordem_id)

    if request.method == 'POST':
        form = ApontamentoMaquinaLocacaoForm(request.POST)
        if form.is_valid():
            apontamento = form.save(commit=False)
            apontamento.ordem = ordem
            apontamento.save()
            _registrar_historico_maquina(
                ordem,
                'Apontamento adicionado',
                f'Apontamento de {apontamento.data} com {apontamento.horas_trabalhadas} horas trabalhadas.',
            )
            messages.success(request, 'Apontamento da maquina registrado com sucesso.')
            return redirect('detalhe_ordem_locacao_maquina', ordem_id=ordem.id)
    else:
        form = ApontamentoMaquinaLocacaoForm()

    return render(
        request,
        'controles/form_apontamento_maquina.html',
        {'form': form, 'titulo': 'Novo Apontamento', 'ordem': ordem},
    )


def editar_apontamento_maquina(request, apontamento_id):
    apontamento = get_object_or_404(
        ApontamentoMaquinaLocacao.objects.select_related('ordem'),
        id=apontamento_id,
    )
    ordem = apontamento.ordem

    if request.method == 'POST':
        form = ApontamentoMaquinaLocacaoForm(request.POST, instance=apontamento)
        if form.is_valid():
            apontamento = form.save()
            _registrar_historico_maquina(ordem, 'Apontamento atualizado', f'Apontamento de {apontamento.data} atualizado.')
            messages.success(request, 'Apontamento da maquina atualizado com sucesso.')
            return redirect('detalhe_ordem_locacao_maquina', ordem_id=ordem.id)
    else:
        form = ApontamentoMaquinaLocacaoForm(instance=apontamento)

    return render(
        request,
        'controles/form_apontamento_maquina.html',
        {'form': form, 'titulo': 'Editar Apontamento', 'ordem': ordem, 'apontamento': apontamento},
    )


def nova_nf_locacao_maquina(request, ordem_id):
    ordem = get_object_or_404(OrdemServicoLocacaoMaquina, id=ordem_id)

    if request.method == 'POST':
        form = NotaFiscalLocacaoMaquinaForm(request.POST)
        if form.is_valid():
            nota = form.save(commit=False)
            nota.ordem = ordem
            nota.save()
            _registrar_historico_maquina(
                ordem,
                'NF adicionada',
                f'NF {nota.numero} adicionada com {nota.horas_faturadas} horas e valor total R$ {nota.valor_total}.',
            )
            messages.success(request, 'NF adicionada a OS com sucesso.')
            return redirect('detalhe_ordem_locacao_maquina', ordem_id=ordem.id)
    else:
        form = NotaFiscalLocacaoMaquinaForm()

    return render(
        request,
        'controles/form_nf_locacao_maquina.html',
        {'form': form, 'titulo': 'Nova NF de Locacao de Maquina', 'ordem': ordem},
    )


def editar_nf_locacao_maquina(request, nota_id):
    nota = get_object_or_404(NotaFiscalLocacaoMaquina.objects.select_related('ordem'), id=nota_id)
    ordem = nota.ordem
    status_anterior = nota.status

    if request.method == 'POST':
        form = NotaFiscalLocacaoMaquinaForm(request.POST, instance=nota)
        if form.is_valid():
            nota = form.save()
            descricao = f'NF {nota.numero} atualizada.'
            if status_anterior != nota.status:
                descricao = f'NF {nota.numero} teve status alterado de {status_anterior} para {nota.status}.'
            _registrar_historico_maquina(ordem, 'NF atualizada', descricao)
            messages.success(request, 'NF de locacao de maquina atualizada com sucesso.')
            return redirect('detalhe_ordem_locacao_maquina', ordem_id=ordem.id)
    else:
        form = NotaFiscalLocacaoMaquinaForm(instance=nota)

    return render(
        request,
        'controles/form_nf_locacao_maquina.html',
        {'form': form, 'titulo': 'Editar NF de Locacao de Maquina', 'ordem': ordem, 'nota': nota},
    )


def lista_catalogo_maquinas_locacao(request):
    maquinas = MaquinaLocacaoCatalogo.objects.all()
    return render(request, 'controles/lista_catalogo_maquinas_locacao.html', {'maquinas': maquinas})


def nova_maquina_locacao(request):
    if request.method == 'POST':
        form = MaquinaLocacaoCatalogoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Maquina cadastrada com sucesso.')
            return redirect('lista_catalogo_maquinas_locacao')
    else:
        form = MaquinaLocacaoCatalogoForm()

    return render(
        request,
        'controles/form_maquina_locacao.html',
        {'form': form, 'titulo': 'Nova Maquina'},
    )


def editar_maquina_locacao(request, maquina_id):
    maquina = get_object_or_404(MaquinaLocacaoCatalogo, id=maquina_id)

    if request.method == 'POST':
        form = MaquinaLocacaoCatalogoForm(request.POST, instance=maquina)
        if form.is_valid():
            form.save()
            messages.success(request, 'Maquina atualizada com sucesso.')
            return redirect('lista_catalogo_maquinas_locacao')
    else:
        form = MaquinaLocacaoCatalogoForm(instance=maquina)

    return render(
        request,
        'controles/form_maquina_locacao.html',
        {'form': form, 'titulo': 'Editar Maquina', 'maquina': maquina},
    )


def lista_fornecedores_maquinas(request):
    fornecedores = FornecedorMaquinaLocacao.objects.all()
    return render(request, 'controles/lista_fornecedores_maquinas.html', {'fornecedores': fornecedores})


def novo_fornecedor_maquina(request):
    if request.method == 'POST':
        form = FornecedorMaquinaLocacaoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fornecedor de maquina cadastrado com sucesso.')
            return redirect('lista_fornecedores_maquinas')
    else:
        form = FornecedorMaquinaLocacaoForm()

    return render(
        request,
        'controles/form_fornecedor_maquina.html',
        {'form': form, 'titulo': 'Novo Fornecedor de Maquina'},
    )


def editar_fornecedor_maquina(request, fornecedor_id):
    fornecedor = get_object_or_404(FornecedorMaquinaLocacao, id=fornecedor_id)

    if request.method == 'POST':
        form = FornecedorMaquinaLocacaoForm(request.POST, instance=fornecedor)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fornecedor de maquina atualizado com sucesso.')
            return redirect('lista_fornecedores_maquinas')
    else:
        form = FornecedorMaquinaLocacaoForm(instance=fornecedor)

    return render(
        request,
        'controles/form_fornecedor_maquina.html',
        {'form': form, 'titulo': 'Editar Fornecedor de Maquina', 'fornecedor': fornecedor},
    )


def lista_equipamentos_locados(request):
    locacoes, filtros = _queryset_locacoes_filtradas(request)
    locacoes_abertas = [locacao for locacao in locacoes if locacao.em_aberto]
    resumo_obras = _resumo_obras(locacoes)
    return render(
        request,
        'controles/lista_equipamentos_locados.html',
        {
            'locacoes': locacoes,
            'locacoes_abertas': locacoes_abertas,
            'resumo_obras': resumo_obras,
            'filtros': filtros,
            'obras_filtro': LocacaoEquipamento.objects.select_related('obra').values_list(
                'obra_id', 'obra__nome_obra'
            ).distinct().order_by('obra__nome_obra'),
            'locadoras_filtro': LocadoraEquipamento.objects.filter(locacoes__isnull=False).distinct().order_by('nome'),
            'status_choices': LocacaoEquipamento.STATUS_CHOICES,
        },
    )


def relatorio_locacoes_equipamentos_pdf(request):
    locacoes, filtros = _queryset_locacoes_filtradas(request)
    active_filters = []
    if filtros['obra'].isdigit():
        obra = next((obra for obra in LocacaoEquipamento.objects.select_related('obra').values_list('obra_id', 'obra__nome_obra').distinct() if str(obra[0]) == filtros['obra']), None)
        if obra:
            active_filters.append(f'Obra: {obra[1]}')
    if filtros['locadora'].isdigit():
        locadora = LocadoraEquipamento.objects.filter(id=filtros['locadora']).first()
        if locadora:
            active_filters.append(f'Locadora: {locadora.nome}')
    if filtros['status']:
        active_filters.append(
            f"Situacao: {dict(LocacaoEquipamento.STATUS_CHOICES).get(filtros['status'], filtros['status'])}"
        )
    if filtros['busca']:
        active_filters.append(f"Busca: {filtros['busca']}")

    lines = [
        'Relatorio de equipamentos locados',
        'Visao operacional com os filtros aplicados na listagem.',
        '',
    ]
    if active_filters:
        lines.append(' | '.join(active_filters))
        lines.append('')
    lines.append('Data | Obra | Locadora | Situacao | Equipamento | Qntd | Data coleta | Observacao')
    lines.append('-' * 120)

    for locacao in locacoes:
        observacao = (locacao.observacoes or '-').replace('\n', ' ')[:55]
        lines.append(
            ' | '.join(
                [
                    locacao.data_locacao.strftime('%d/%m/%Y'),
                    locacao.obra.nome_obra[:18],
                    str(locacao.locadora)[:12],
                    locacao.get_status_display()[:12],
                    str(locacao.equipamento)[:24],
                    str(locacao.quantidade),
                    locacao.data_retirada.strftime('%d/%m/%Y') if locacao.data_retirada else '-',
                    observacao,
                ]
            )
        )

    max_lines_per_page = 36
    pages = [lines[index:index + max_lines_per_page] for index in range(0, len(lines), max_lines_per_page)]
    response = HttpResponse(_build_simple_pdf(pages), content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="relatorio_locacoes_equipamentos.pdf"'
    return response


def nova_locacao_equipamento(request):
    if request.method == 'POST':
        form = LocacaoEquipamentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Locacao de equipamento registrada com sucesso.')
            return redirect('lista_equipamentos_locados')
    else:
        form = LocacaoEquipamentoForm()

    return render(
        request,
        'controles/form_locacao_equipamento.html',
        {'form': form, 'titulo': 'Nova Locacao de Equipamento'},
    )


def editar_locacao_equipamento(request, locacao_id):
    locacao = get_object_or_404(LocacaoEquipamento, id=locacao_id)

    if request.method == 'POST':
        form = LocacaoEquipamentoForm(request.POST, instance=locacao)
        if form.is_valid():
            form.save()
            messages.success(request, 'Locacao de equipamento atualizada com sucesso.')
            return redirect('lista_equipamentos_locados')
    else:
        form = LocacaoEquipamentoForm(instance=locacao)

    return render(
        request,
        'controles/form_locacao_equipamento.html',
        {'form': form, 'titulo': 'Editar Locacao de Equipamento', 'locacao': locacao},
    )


def solicitar_retirada_equipamento(request, locacao_id):
    locacao = get_object_or_404(LocacaoEquipamento, id=locacao_id)

    if request.method == 'POST':
        form = SolicitarRetiradaEquipamentoForm(request.POST, instance=locacao)
        if form.is_valid():
            locacao = form.save(commit=False)
            locacao.status = 'retirada_solicitada'
            locacao.save()
            messages.success(request, 'Solicitacao de retirada registrada com sucesso.')
            return redirect('lista_equipamentos_locados')
    else:
        form = SolicitarRetiradaEquipamentoForm(instance=locacao)

    return render(
        request,
        'controles/form_acao_locacao.html',
        {'form': form, 'titulo': 'Solicitar Retirada', 'locacao': locacao},
    )


def baixar_locacao_equipamento(request, locacao_id):
    locacao = get_object_or_404(LocacaoEquipamento, id=locacao_id)

    if request.method == 'POST':
        form = BaixarLocacaoEquipamentoForm(request.POST, instance=locacao)
        if form.is_valid():
            locacao = form.save(commit=False)
            locacao.status = 'retirado'
            locacao.save()
            messages.success(request, 'Baixa do equipamento registrada com sucesso.')
            return redirect('lista_equipamentos_locados')
    else:
        form = BaixarLocacaoEquipamentoForm(instance=locacao)

    return render(
        request,
        'controles/form_acao_locacao.html',
        {'form': form, 'titulo': 'Baixar Equipamento', 'locacao': locacao},
    )


def lista_catalogo_equipamentos(request):
    equipamentos = EquipamentoLocadoCatalogo.objects.all()
    return render(
        request,
        'controles/lista_catalogo_equipamentos.html',
        {'equipamentos': equipamentos},
    )


def novo_catalogo_equipamento(request):
    if request.method == 'POST':
        form = EquipamentoLocadoCatalogoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Equipamento cadastrado no catalogo com sucesso.')
            return redirect('lista_catalogo_equipamentos')
    else:
        form = EquipamentoLocadoCatalogoForm()

    return render(
        request,
        'controles/form_catalogo_equipamento.html',
        {'form': form, 'titulo': 'Novo Equipamento'},
    )


def lista_locadoras(request):
    locadoras = LocadoraEquipamento.objects.all()
    return render(request, 'controles/lista_locadoras.html', {'locadoras': locadoras})


def nova_locadora(request):
    if request.method == 'POST':
        form = LocadoraEquipamentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Locadora cadastrada com sucesso.')
            return redirect('lista_locadoras')
    else:
        form = LocadoraEquipamentoForm()

    return render(
        request,
        'controles/form_locadora.html',
        {'form': form, 'titulo': 'Nova Locadora'},
    )


def lista_radar_obras(request):
    orcamentos = OrcamentoRadarObra.objects.all()
    contadores = {
        'aguardando_resposta': orcamentos.filter(situacao='aguardando_resposta').count(),
        'em_revisao': orcamentos.filter(situacao='em_revisao').count(),
        'fechada': orcamentos.filter(situacao='fechada').count(),
        'nao_foi_para_frente': orcamentos.filter(situacao='nao_foi_para_frente').count(),
        'cancelada': orcamentos.filter(situacao='cancelada').count(),
    }
    return render(
        request,
        'controles/lista_radar_obras.html',
        {'orcamentos': orcamentos, 'contadores': contadores},
    )


def novo_radar_obra(request):
    if request.method == 'POST':
        form = OrcamentoRadarObraForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Orcamento cadastrado no radar com sucesso.')
            return redirect('lista_radar_obras')
    else:
        form = OrcamentoRadarObraForm()

    return render(
        request,
        'controles/form_radar_obra.html',
        {'form': form, 'titulo': 'Novo Orcamento'},
    )


def editar_radar_obra(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoRadarObra, id=orcamento_id)

    if request.method == 'POST':
        form = OrcamentoRadarObraForm(request.POST, instance=orcamento)
        if form.is_valid():
            form.save()
            messages.success(request, 'Orcamento atualizado com sucesso.')
            return redirect('lista_radar_obras')
    else:
        form = OrcamentoRadarObraForm(instance=orcamento)

    return render(
        request,
        'controles/form_radar_obra.html',
        {'form': form, 'titulo': 'Editar Orcamento', 'orcamento': orcamento},
    )


def lista_concretagens(request):
    contratos = ContratoConcretagem.objects.select_related('obra').prefetch_related('faturamentos').all()
    return render(request, 'controles/lista_concretagens.html', {'contratos': contratos})


def lista_solicitantes_concretagem(request):
    solicitantes = SolicitanteConcretagem.objects.all()
    return render(
        request,
        'controles/lista_solicitantes_concretagem.html',
        {'solicitantes': solicitantes},
    )


def novo_solicitante_concretagem(request):
    if request.method == 'POST':
        form = SolicitanteConcretagemForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Solicitante cadastrado com sucesso.')
            return redirect('lista_solicitantes_concretagem')
    else:
        form = SolicitanteConcretagemForm()

    return render(
        request,
        'controles/form_solicitante_concretagem.html',
        {'form': form, 'titulo': 'Novo Solicitante'},
    )


def editar_solicitante_concretagem(request, solicitante_id):
    solicitante = get_object_or_404(SolicitanteConcretagem, id=solicitante_id)

    if request.method == 'POST':
        form = SolicitanteConcretagemForm(request.POST, instance=solicitante)
        if form.is_valid():
            form.save()
            messages.success(request, 'Solicitante atualizado com sucesso.')
            return redirect('lista_solicitantes_concretagem')
    else:
        form = SolicitanteConcretagemForm(instance=solicitante)

    return render(
        request,
        'controles/form_solicitante_concretagem.html',
        {'form': form, 'titulo': 'Editar Solicitante', 'solicitante': solicitante},
    )


def novo_contrato_concretagem(request):
    if request.method == 'POST':
        form = ContratoConcretagemForm(request.POST)
        if form.is_valid():
            contrato = form.save()
            messages.success(request, 'Contrato de concretagem cadastrado com sucesso.')
            return redirect('detalhe_contrato_concretagem', contrato_id=contrato.id)
    else:
        form = ContratoConcretagemForm()

    return render(
        request,
        'controles/form_contrato_concretagem.html',
        {'form': form, 'titulo': 'Novo Contrato de Concretagem'},
    )


def detalhe_contrato_concretagem(request, contrato_id):
    contrato = get_object_or_404(
        ContratoConcretagem.objects.select_related('obra').prefetch_related('faturamentos'),
        id=contrato_id,
    )
    return render(request, 'controles/detalhe_contrato_concretagem.html', {'contrato': contrato})


def editar_contrato_concretagem(request, contrato_id):
    contrato = get_object_or_404(ContratoConcretagem, id=contrato_id)

    if request.method == 'POST':
        form = ContratoConcretagemForm(request.POST, instance=contrato)
        if form.is_valid():
            form.save()
            messages.success(request, 'Contrato de concretagem atualizado com sucesso.')
            return redirect('detalhe_contrato_concretagem', contrato_id=contrato.id)
    else:
        form = ContratoConcretagemForm(instance=contrato)

    return render(
        request,
        'controles/form_contrato_concretagem.html',
        {'form': form, 'titulo': 'Editar Contrato de Concretagem', 'contrato': contrato},
    )


def novo_faturamento_concretagem(request, contrato_id):
    contrato = get_object_or_404(ContratoConcretagem, id=contrato_id)

    if request.method == 'POST':
        form = FaturamentoConcretagemForm(request.POST)
        if form.is_valid():
            faturamento = form.save(commit=False)
            faturamento.contrato = contrato
            faturamento.save()
            messages.success(request, 'Faturamento de concretagem cadastrado com sucesso.')
            return redirect('detalhe_contrato_concretagem', contrato_id=contrato.id)
    else:
        form = FaturamentoConcretagemForm()

    return render(
        request,
        'controles/form_faturamento_concretagem.html',
        {'form': form, 'titulo': 'Nova Concretagem', 'contrato': contrato},
    )


def editar_faturamento_concretagem(request, faturamento_id):
    faturamento = get_object_or_404(
        FaturamentoConcretagem.objects.select_related('contrato'),
        id=faturamento_id,
    )
    contrato = faturamento.contrato

    if request.method == 'POST':
        form = FaturamentoConcretagemForm(request.POST, instance=faturamento)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faturamento de concretagem atualizado com sucesso.')
            return redirect('detalhe_contrato_concretagem', contrato_id=contrato.id)
    else:
        form = FaturamentoConcretagemForm(instance=faturamento)

    return render(
        request,
        'controles/form_faturamento_concretagem.html',
        {'form': form, 'titulo': 'Editar Concretagem', 'contrato': contrato},
    )
