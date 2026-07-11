import csv
import textwrap
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageFont

from controles.models import FaturamentoDireto
from controles.views import _build_simple_pdf
from obras.models import Obra

from .forms import (
    EmpreiteiroForm,
    ImportarOrcamentoForm,
    ItemMedicaoConstrutoraFormSet,
    ItemMedicaoEmpreiteiroFormSet,
    ItemOrcamentoMedicaoFormSet,
    MedicaoConstrutoraCabecalhoForm,
    MedicaoConstrutoraForm,
    MedicaoEmpreiteiroCabecalhoForm,
    MedicaoEmpreiteiroForm,
    OrcamentoMedicaoManualForm,
)
from .models import (
    Empreiteiro,
    FaturamentoDiretoMedicao,
    ItemMedicaoConstrutora,
    ItemMedicaoEmpreiteiro,
    ItemOrcamentoMedicao,
    MedicaoConstrutora,
    MedicaoEmpreiteiro,
    OrcamentoMedicao,
)


def _money(value):
    value = value or Decimal('0')
    return f'R$ {value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _clean_text(value):
    return unicodedata.normalize('NFKD', str(value or '-')).encode('ascii', 'ignore').decode('ascii')


def _font(size, bold=False):
    candidates = [
        settings.BASE_DIR / 'static' / 'fonts' / ('Arial Bold.ttf' if bold else 'Arial.ttf'),
        settings.BASE_DIR / 'static' / 'fonts' / ('arialbd.ttf' if bold else 'arial.ttf'),
        settings.BASE_DIR / 'static' / 'fonts' / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),
        settings.BASE_DIR / 'static' / 'propostas' / 'fonts' / ('Arial Bold.ttf' if bold else 'Arial.ttf'),
        Path('C:/Windows/Fonts') / ('arialbd.ttf' if bold else 'arial.ttf'),
        Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _draw_wrapped_cell(draw, value, x, y, w, h, font, fill=(31, 41, 55), align='left'):
    text = _clean_text(value)
    avg_char_width = max(font.getlength('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz') / 52, 1)
    max_chars = max(int((w - 18) / avg_char_width), 8)
    lines = textwrap.wrap(text, width=max_chars) or ['']
    line_height = font.getbbox('Ag')[3] - font.getbbox('Ag')[1] + 7
    visible_lines = lines[: max(int((h - 12) / line_height), 1)]
    y_text = y + max((h - (line_height * len(visible_lines))) // 2, 6)
    for line in visible_lines:
        if align == 'right':
            x_text = x + w - font.getlength(line) - 10
        elif align == 'center':
            x_text = x + (w - font.getlength(line)) / 2
        else:
            x_text = x + 10
        draw.text((x_text, y_text), line, font=font, fill=fill)
        y_text += line_height


def _draw_pdf_table(draw, headers, rows, x, y, widths, row_h=54):
    border = (203, 213, 225)
    header_fill = (229, 236, 240)
    zebra = (248, 250, 252)
    header_font = _font(20, True)
    cell_font = _font(19)
    x_cursor = x
    for header, width in zip(headers, widths):
        draw.rectangle((x_cursor, y, x_cursor + width, y + row_h), fill=header_fill, outline=border, width=2)
        _draw_wrapped_cell(draw, header, x_cursor, y, width, row_h, header_font, fill=(15, 23, 42), align='center')
        x_cursor += width
    y += row_h
    for index, row in enumerate(rows):
        x_cursor = x
        fill = zebra if index % 2 else (255, 255, 255)
        for cell_index, (value, width) in enumerate(zip(row, widths)):
            draw.rectangle((x_cursor, y, x_cursor + width, y + row_h), fill=fill, outline=border, width=1)
            align = 'right' if cell_index >= len(row) - 3 else 'left'
            if cell_index in (0, 2):
                align = 'center'
            _draw_wrapped_cell(draw, value, x_cursor, y, width, row_h, cell_font, align=align)
            x_cursor += width
        y += row_h
    return y


def _draw_report_cell(
    draw,
    value,
    x,
    y,
    w,
    h,
    font,
    fill=(17, 24, 39),
    bg=None,
    border=(156, 163, 175),
    align='left',
    bold=False,
    width=1,
):
    if bg:
        draw.rectangle((x, y, x + w, y + h), fill=bg, outline=border, width=width)
    else:
        draw.rectangle((x, y, x + w, y + h), outline=border, width=width)
    text = _clean_text(value)
    avg_char_width = max(font.getlength('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz') / 52, 1)
    max_chars = max(int((w - 8) / avg_char_width), 4)
    lines = textwrap.wrap(text, width=max_chars) or ['']
    line_height = font.getbbox('Ag')[3] - font.getbbox('Ag')[1] + 4
    visible_lines = lines[: max(int((h - 6) / line_height), 1)]
    text_h = line_height * len(visible_lines)
    y_text = y + max((h - text_h) // 2, 3)
    for line in visible_lines:
        if align == 'right':
            x_text = x + w - font.getlength(line) - 5
        elif align == 'center':
            x_text = x + (w - font.getlength(line)) / 2
        else:
            x_text = x + 5
        draw.text((x_text, y_text), line, font=font, fill=fill)
        y_text += line_height


def _draw_report_row(draw, row, x, y, widths, height, font, bg=None, bold=False, cell_bgs=None):
    cursor = x
    for index, (value, width) in enumerate(zip(row, widths)):
        align = 'left' if index == 1 else 'center'
        cell_bg = cell_bgs[index] if cell_bgs and index < len(cell_bgs) and cell_bgs[index] else bg
        _draw_report_cell(draw, value, cursor, y, width, height, font, bg=cell_bg, align=align, width=1)
        cursor += width
    return y + height


def _fmt_qty(value):
    value = value or Decimal('0')
    quantized = value.quantize(Decimal('0.0001'))
    text = f'{quantized:,.4f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return text.rstrip('0').rstrip(',')


def _percent_from_item(item):
    contrato = item.item_orcamento.quantidade or Decimal('0')
    if not contrato:
        return Decimal('0')
    percent = item.quantidade_acumulada_atual * Decimal('100') / contrato
    return percent.quantize(Decimal('0.01'))


def _pdf_medicao_construtora(medicao):
    itens = list(medicao.itens.select_related('item_orcamento'))
    page_w, page_h = 2339, 1654
    margin = 60
    table_w = page_w - (margin * 2)
    widths = [65, 559, 55, 95, 130, 130, 125, 130, 130, 95, 95, 75, 135, 135, 130, 135]
    row_h = 40
    header_h = 42
    footer_y = page_h - 44
    content_bottom = page_h - 98
    rows_per_page = 18
    chunks = [itens[i : i + rows_per_page] for i in range(0, len(itens), rows_per_page)] or [[]]
    pages = []

    title_font = _font(28, True)
    label_font = _font(17, True)
    small_font = _font(17)
    table_font = _font(13)
    table_bold = _font(13, True)
    header_bg = (229, 231, 235)
    contract_bg = (232, 238, 247)
    measured_bg = (220, 245, 229)
    receivable_bg = (254, 226, 226)
    section_bg = (243, 244, 246)
    dark = (17, 24, 39)
    muted = (75, 85, 99)
    border = (156, 163, 175)

    def new_page():
        page = Image.new('RGB', (page_w, page_h), 'white')
        page_draw = ImageDraw.Draw(page)
        y_start = 34
        page_draw.text(
            ((page_w - title_font.getlength('Boletim de Medicoes')) / 2, y_start),
            'Boletim de Medicoes',
            font=title_font,
            fill=dark,
        )
        return page, page_draw, y_start + 82

    def ensure_space(image, draw, y, needed):
        if y + needed <= content_bottom:
            return image, draw, y, False
        pages.append(image)
        new_image, new_draw, new_y = new_page()
        return new_image, new_draw, new_y, True

    def draw_faturamento_header(draw, y):
        _draw_report_cell(
            draw,
            'Faturamentos diretos descontados',
            margin,
            y,
            table_w,
            block_h,
            label_font,
            bg=header_bg,
            align='left',
        )
        return y + block_h

    for page_index, chunk in enumerate(chunks):
        image = Image.new('RGB', (page_w, page_h), 'white')
        draw = ImageDraw.Draw(image)

        y = 34
        draw.text(((page_w - title_font.getlength('Boletim de Medicoes')) / 2, y), 'Boletim de Medicoes', font=title_font, fill=dark)
        y += 62

        left_x = margin
        right_x = page_w - margin - 690
        info_h = 34
        left_info = [
            ('Contrato', getattr(medicao.orcamento, 'nome', '-')),
            ('Obra', medicao.orcamento.obra.nome_obra),
            ('Unidade construtiva', medicao.orcamento.nome),
            ('Numero da medicao', medicao.numero),
            ('Periodo', f'{medicao.periodo_inicio:%d/%m/%Y} a {medicao.periodo_fim:%d/%m/%Y}'),
        ]
        right_info = [
            ('Total do contrato', _money(medicao.orcamento.total_orcamento)),
            ('Total da obra', _money(medicao.orcamento.obra.contrato_atualizado)),
            ('Cliente', medicao.orcamento.obra.cliente or '-'),
            ('Data da medicao', f'{medicao.data_medicao:%d/%m/%Y}'),
            ('Base INSS', _money(medicao.base_inss)),
        ]
        for index, (label, value) in enumerate(left_info):
            row_y = y + index * info_h
            _draw_report_cell(draw, label, left_x, row_y, 210, info_h, label_font, bg=header_bg, align='left')
            _draw_report_cell(draw, value, left_x + 210, row_y, 720, info_h, small_font, align='left')
        for index, (label, value) in enumerate(right_info):
            row_y = y + index * info_h
            _draw_report_cell(draw, label, right_x, row_y, 230, info_h, label_font, bg=header_bg, align='left')
            _draw_report_cell(draw, value, right_x + 230, row_y, 460, info_h, small_font, align='left')

        y += (len(left_info) * info_h) + 28
        headers = [
            'Ref.',
            'Descricao',
            'Un.',
            'Contratada',
            'Unit. material',
            'Unit. mao obra',
            'Unit. equip.',
            'Preco unit.',
            'Valor anterior',
            'Acum. anterior',
            'Medida',
            '%Exe.',
            'Material',
            'Mao de obra',
            'Equip.',
            'Valor medicao',
        ]
        group_headers = [
            ('Itens contratuais', 0, 8, contract_bg),
            ('Itens medidos', 8, 12, measured_bg),
            ('Valor a receber', 12, 16, receivable_bg),
        ]
        cursor = margin
        for label, start, end, bg in group_headers:
            group_w = sum(widths[start:end])
            _draw_report_cell(draw, label, cursor, y, group_w, header_h, table_bold, bg=bg, align='center', width=2)
            cursor += group_w
        y += header_h
        cursor = margin
        for index, (header, width) in enumerate(zip(headers, widths)):
            if index < 8:
                bg = contract_bg
            elif index < 12:
                bg = measured_bg
            else:
                bg = receivable_bg
            _draw_report_cell(draw, header, cursor, y, width, header_h, table_bold, bg=bg, align='center', width=2)
            cursor += width
        y += header_h

        measured_cell_bgs = [None] * len(widths)
        for measured_index in range(8, 12):
            measured_cell_bgs[measured_index] = measured_bg

        for item in chunk:
            base = item.item_orcamento
            is_section = not base.unidade and not base.preco_unitario_total and not base.quantidade
            font = table_bold if is_section else table_font
            bg = section_bg if is_section else None
            valor_anterior = item.quantidade_acumulada_anterior * base.preco_unitario_total
            row = [
                base.item,
                base.descricao,
                base.unidade or '',
                _fmt_qty(base.quantidade),
                _money(base.preco_unitario_material),
                _money(base.preco_unitario_mao_obra),
                _money(base.preco_unitario_equipamentos),
                _money(base.preco_unitario_total),
                _money(valor_anterior),
                _fmt_qty(item.quantidade_acumulada_anterior),
                _fmt_qty(item.quantidade_periodo),
                f'{_fmt_qty(_percent_from_item(item))}%',
                _money(item.valor_material_periodo),
                _money(item.valor_mao_obra_periodo),
                _money(item.valor_equipamentos_periodo),
                _money(item.valor_periodo),
            ]
            y = _draw_report_row(draw, row, margin, y, widths, row_h, font, bg=bg, cell_bgs=measured_cell_bgs)

        if page_index == len(chunks) - 1:
            totalizer_rows = [
                ('Total material', medicao.total_material_periodo, 12),
                ('Total mao de obra', medicao.total_mao_obra_periodo, 13),
                ('Total equipamentos', medicao.total_equipamentos_periodo, 14),
            ]
            for label, value, component_index in totalizer_rows:
                row = [''] * len(widths)
                row[1] = label
                row[component_index] = _money(value)
                row[-1] = _money(value)
                y = _draw_report_row(draw, row, margin, y, widths, row_h, table_bold, bg=section_bg)

            y += 28
            summary_left = margin
            summary_mid = margin + 650
            summary_right = page_w - margin - 660
            block_h = 34

            _draw_report_cell(draw, 'Total da medicao', summary_left, y, 560, block_h, label_font, bg=header_bg, align='center')
            y_left = y + block_h
            desconto_adicional_nf = (
                medicao.desconto_adicional_calculado
                if medicao.desconto_adicional_reduz_base_nf
                else Decimal('0')
            )
            totals = [
                ('Total medicao', medicao.subtotal_periodo),
                ('Desconto faturamento direto', -medicao.total_faturamento_direto),
                ('Desconto adicional NF', -desconto_adicional_nf),
                ('Total a faturar', medicao.base_impostos),
            ]
            for label, value in totals:
                _draw_report_cell(draw, label, summary_left, y_left, 330, block_h, small_font, align='left')
                amount = _money(abs(value))
                if value < 0:
                    amount = f'- {amount}'
                _draw_report_cell(draw, amount, summary_left + 330, y_left, 230, block_h, small_font, align='right')
                y_left += block_h

            _draw_report_cell(draw, 'Retencoes e impostos', summary_mid, y, 560, block_h, label_font, bg=header_bg, align='center')
            y_mid = y + block_h
            taxes = [
                ('Retencao tecnica', medicao.retencao_tecnica_calculada),
                ('INSS', medicao.inss_calculado),
                ('ISSQN', medicao.issqn_calculado),
                ('Total retido', medicao.retencao_tecnica_calculada + medicao.inss_calculado + medicao.issqn_calculado),
            ]
            for label, value in taxes:
                _draw_report_cell(draw, label, summary_mid, y_mid, 330, block_h, small_font, align='left')
                _draw_report_cell(draw, _money(value), summary_mid + 330, y_mid, 230, block_h, small_font, align='right')
                y_mid += block_h

            _draw_report_cell(draw, 'Fechamento', summary_right, y, 660, block_h, label_font, bg=header_bg, align='center')
            y_right = y + block_h
            closing = [
                ('Subtotal', medicao.subtotal_periodo),
                ('Base da NF', medicao.base_impostos),
                ('Material NF', medicao.valor_material_nf),
                ('Mao de obra NF', medicao.valor_mao_obra_nf),
                ('Equipamentos NF', medicao.valor_equipamentos_nf),
                ('Base INSS', medicao.base_inss),
                ('Descontos', medicao.total_descontos),
                ('Total liquido', medicao.total_liquido),
            ]
            for label, value in closing:
                is_total = label == 'Total liquido'
                _draw_report_cell(draw, label, summary_right, y_right, 390, block_h, label_font if is_total else small_font, align='left')
                _draw_report_cell(draw, _money(value), summary_right + 390, y_right, 270, block_h, label_font if is_total else small_font, align='right')
                y_right += block_h

            if medicao.faturamentos_diretos.exists():
                notes_y = max(y_left, y_mid, y_right) + 24
                image, draw, notes_y, _new_page = ensure_space(image, draw, notes_y, block_h * 2)
                notes_y = draw_faturamento_header(draw, notes_y)
                for vinculo in medicao.faturamentos_diretos.select_related('faturamento_direto'):
                    image, draw, notes_y, new_page_started = ensure_space(image, draw, notes_y, block_h)
                    if new_page_started:
                        notes_y = draw_faturamento_header(draw, notes_y)
                    fd = vinculo.faturamento_direto
                    texto = f'{fd.numero_nf or fd.numero_ordem_compra or "-"} - {fd.empresa_comprou} - {fd.descricao} ({vinculo.percentual_descontado:.2f}%)'
                    _draw_report_cell(draw, texto, margin, notes_y, table_w - 220, block_h, small_font, align='left')
                    _draw_report_cell(draw, _money(vinculo.valor_descontado), margin + table_w - 220, notes_y, 220, block_h, small_font, align='right')
                    notes_y += block_h

        pages.append(image)

    total_pages = len(pages)
    for index, image in enumerate(pages, start=1):
        draw = ImageDraw.Draw(image)
        footer = f'Pagina {index} de {total_pages}'
        draw.text((margin, footer_y), date.today().strftime('%d/%m/%Y'), font=_font(15), fill=muted)
        draw.text(((page_w - _font(15).getlength('AMBAR ENGENHARIA')) / 2, footer_y), 'AMBAR ENGENHARIA', font=_font(15, True), fill=muted)
        draw.text((page_w - margin - _font(15).getlength(footer), footer_y), footer, font=_font(15), fill=muted)

    buffer = BytesIO()
    pages[0].save(buffer, 'PDF', save_all=True, append_images=pages[1:], resolution=150)
    return buffer.getvalue()


def _decimal(value):
    if value in (None, ''):
        return Decimal('0')
    cleaned = str(value).strip().replace('R$', '').replace(' ', '')
    if ',' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal('0')


def _normalize_header(value):
    normalized = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    return ''.join(char for char in normalized.lower() if char.isalnum())


HEADER_ALIASES = {
    'item': ['item', 'codigo', 'cod'],
    'descricao': ['descricao', 'descricaodoservico', 'servico'],
    'unidade': ['unidade', 'un', 'und'],
    'quantidade': ['quantidade', 'qtd', 'quant'],
    'preco_unitario_material': [
        'precounitariomaterial',
        'unitariomaterial',
        'material',
        'precounitario',
        'valorunitario',
        'unitario',
        'preco',
    ],
    'preco_unitario_mao_obra': ['precounitariomaodeobra', 'unitariomaodeobra', 'maodeobra'],
    'preco_unitario_equipamentos': ['precounitarioequipamentos', 'unitarioequipamentos', 'equipamentos', 'equipamento'],
}


def _value(row, field):
    normalized = {_normalize_header(key): value for key, value in row.items()}
    for alias in HEADER_ALIASES[field]:
        if alias in normalized:
            return normalized[alias]
    return ''


def _next_numero(model, **filters):
    last = model.objects.filter(**filters).order_by('-numero').first()
    return (last.numero + 1) if last else 1


def _percent_value(base, percent):
    if not percent:
        return None
    return (base * percent / Decimal('100')).quantize(Decimal('0.01'))


def _aplicar_percentuais_construtora(medicao):
    campos = {
        'retencao_tecnica': (medicao.subtotal_periodo, medicao.retencao_tecnica_percentual),
        'desconto_adicional': (medicao.subtotal_periodo, medicao.desconto_adicional_percentual),
        'issqn': (medicao.base_impostos, medicao.issqn_percentual),
        'inss': (medicao.base_inss, medicao.inss_percentual),
    }
    updates = []
    for field, (base, percent) in campos.items():
        value = _percent_value(base, percent)
        if value is not None:
            setattr(medicao, field, value)
            updates.append(field)
    if updates:
        medicao.save(update_fields=updates + ['updated_at'])


def _atualizar_resumo_faturamento_direto(faturamento):
    vinculos = faturamento.vinculos_medicao.select_related('medicao').order_by('medicao__numero', 'id')
    partes = [f'{vinculo.medicao.label_medicao} ({vinculo.percentual_descontado:.2f}%)' for vinculo in vinculos]
    faturamento.medicao_desconto = ' / '.join(partes)[:120]
    faturamento.save(update_fields=['medicao_desconto', 'updated_at'])


def _sync_faturamentos_diretos(medicao, post_data):
    atuais = {
        vinculo.faturamento_direto_id: vinculo
        for vinculo in medicao.faturamentos_diretos.select_related('faturamento_direto')
    }
    usados = set()
    for faturamento in FaturamentoDireto.objects.filter(obra=medicao.orcamento.obra):
        raw_percent = (post_data.get(f'faturamento_direto_{faturamento.id}_percentual') or '').strip()
        try:
            percentual = Decimal(raw_percent.replace(',', '.')) if raw_percent else Decimal('0')
        except InvalidOperation:
            percentual = Decimal('0')
        percentual = max(Decimal('0'), min(percentual, Decimal('100')))
        ja_descontado = sum(
            (
                vinculo.percentual_descontado
                for vinculo in faturamento.vinculos_medicao.exclude(medicao=medicao)
            ),
            Decimal('0'),
        )
        saldo_percentual = max(Decimal('100') - ja_descontado, Decimal('0'))
        percentual = min(percentual, saldo_percentual)
        vinculo = atuais.get(faturamento.id)
        if percentual > 0:
            if not vinculo:
                vinculo = FaturamentoDiretoMedicao(medicao=medicao, faturamento_direto=faturamento)
            vinculo.percentual_descontado = percentual
            vinculo.save()
            usados.add(faturamento.id)
        elif vinculo:
            vinculo.delete()
        _atualizar_resumo_faturamento_direto(faturamento)
    for faturamento_id, vinculo in atuais.items():
        if faturamento_id not in usados and not FaturamentoDireto.objects.filter(id=faturamento_id).exists():
            faturamento = vinculo.faturamento_direto
            vinculo.delete()
            _atualizar_resumo_faturamento_direto(faturamento)


def _faturamentos_diretos_context(medicao):
    linhas = []
    for faturamento in FaturamentoDireto.objects.filter(obra=medicao.orcamento.obra).order_by('data_lancamento', 'id'):
        vinculo_atual = medicao.faturamentos_diretos.filter(faturamento_direto=faturamento).first()
        percentual_atual = vinculo_atual.percentual_descontado if vinculo_atual else Decimal('0')
        percentual_outros = sum(
            (
                vinculo.percentual_descontado
                for vinculo in faturamento.vinculos_medicao.exclude(medicao=medicao)
            ),
            Decimal('0'),
        )
        saldo_percentual = max(Decimal('100') - percentual_outros, Decimal('0'))
        if saldo_percentual <= 0 and not vinculo_atual:
            continue
        linhas.append(
            {
                'faturamento': faturamento,
                'percentual_atual': percentual_atual,
                'percentual_outros': percentual_outros,
                'saldo_percentual': saldo_percentual,
                'valor_atual': vinculo_atual.valor_descontado if vinculo_atual else Decimal('0'),
            }
        )
    return linhas


def _aplicar_percentuais_empreiteiro(medicao):
    base = medicao.subtotal_periodo
    campos = {
        'retencao_tecnica': medicao.retencao_tecnica_percentual,
        'desconto_adicional': medicao.desconto_adicional_percentual,
    }
    updates = []
    for field, percent in campos.items():
        value = _percent_value(base, percent)
        if value is not None:
            setattr(medicao, field, value)
            updates.append(field)
    if updates:
        medicao.save(update_fields=updates + ['updated_at'])


def _empreiteiros_json():
    return [
        {
            'id': empreiteiro.id,
            'nome': empreiteiro.nome,
            'cpf_cnpj': empreiteiro.cpf_cnpj,
            'pix': empreiteiro.pix,
        }
        for empreiteiro in Empreiteiro.objects.filter(ativo=True).order_by('nome')
    ]


def _sync_empreiteiro_medicao(medicao):
    if medicao.empreiteiro_cadastro_id:
        cadastro = medicao.empreiteiro_cadastro
        medicao.empreiteiro = cadastro.nome
        medicao.cpf_cnpj = cadastro.cpf_cnpj
        medicao.pix = cadastro.pix
        medicao.save(update_fields=['empreiteiro', 'cpf_cnpj', 'pix', 'updated_at'])
        return cadastro
    return None


def _read_csv(file):
    raw = file.read()
    if not raw:
        return None, 'O arquivo CSV esta vazio.'
    for encoding in ['utf-8-sig', 'latin-1']:
        try:
            content = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        content = raw.decode('utf-8', errors='ignore')
    sample = content[:2048]
    delimiter = ';' if sample.count(';') >= sample.count(',') else ','
    reader = csv.DictReader(StringIO(content), delimiter=delimiter)
    if not reader.fieldnames:
        return None, 'O CSV precisa ter cabecalho na primeira linha.'
    normalized_headers = {_normalize_header(header) for header in reader.fieldnames}
    if not any(alias in normalized_headers for alias in HEADER_ALIASES['descricao']):
        return None, 'Nao encontrei a coluna descricao no CSV.'
    return reader, ''


def medicoes_home(request):
    return redirect('medicoes_construtora_home')


def medicoes_construtora_home(request):
    contexto = {
        'obras': Obra.objects.filter(
            orcamentos_medicao__tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        ).distinct().order_by('nome_obra'),
        'planilhas': OrcamentoMedicao.objects.filter(
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        ).select_related('obra').prefetch_related('medicoes_construtora', 'itens'),
        'medicoes': MedicaoConstrutora.objects.select_related('orcamento', 'orcamento__obra')[:12],
    }
    return render(request, 'medicoes/construtora_home.html', contexto)


def medicoes_empreiteiros_home(request):
    contexto = {
        'simples': MedicaoEmpreiteiro.objects.filter(
            tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
        ).select_related('obra')[:15],
        'cumulativas': MedicaoEmpreiteiro.objects.filter(
            tipo=MedicaoEmpreiteiro.TIPO_CUMULATIVA,
        ).select_related('obra', 'orcamento')[:15],
        'planilhas': OrcamentoMedicao.objects.filter(
            tipo=OrcamentoMedicao.TIPO_EMPREITEIRO,
        ).select_related('obra')[:15],
    }
    return render(request, 'medicoes/empreiteiros_home.html', contexto)


def lista_empreiteiros(request):
    empreiteiros = Empreiteiro.objects.all()
    busca = request.GET.get('busca', '').strip()
    if busca:
        empreiteiros = empreiteiros.filter(
            Q(nome__icontains=busca)
            | Q(cpf_cnpj__icontains=busca)
            | Q(pix__icontains=busca)
        )
    return render(
        request,
        'medicoes/lista_empreiteiros.html',
        {'empreiteiros': empreiteiros, 'busca': busca},
    )


def novo_empreiteiro(request):
    if request.method == 'POST':
        form = EmpreiteiroForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Empreiteiro cadastrado com sucesso.')
            return redirect('lista_empreiteiros_medicao')
    else:
        form = EmpreiteiroForm()
    return render(request, 'medicoes/form_empreiteiro.html', {'form': form, 'titulo': 'Novo empreiteiro'})


def editar_empreiteiro(request, empreiteiro_id):
    empreiteiro = get_object_or_404(Empreiteiro, id=empreiteiro_id)
    if request.method == 'POST':
        form = EmpreiteiroForm(request.POST, instance=empreiteiro)
        if form.is_valid():
            form.save()
            messages.success(request, 'Empreiteiro atualizado com sucesso.')
            return redirect('lista_empreiteiros_medicao')
    else:
        form = EmpreiteiroForm(instance=empreiteiro)
    return render(
        request,
        'medicoes/form_empreiteiro.html',
        {'form': form, 'titulo': 'Editar empreiteiro', 'empreiteiro': empreiteiro},
    )


def medicoes_obra(request, obra_id):
    obra = get_object_or_404(Obra, id=obra_id)
    planilhas = obra.orcamentos_medicao.prefetch_related('itens', 'medicoes_construtora', 'medicoes_empreiteiro')
    medicoes_construtora = MedicaoConstrutora.objects.filter(orcamento__obra=obra).select_related('orcamento')
    medicoes_empreiteiro = MedicaoEmpreiteiro.objects.filter(obra=obra).select_related('orcamento')
    return render(
        request,
        'medicoes/obra.html',
        {
            'obra': obra,
            'planilhas': planilhas,
            'medicoes_construtora': medicoes_construtora,
            'medicoes_empreiteiro': medicoes_empreiteiro,
        },
    )


def lista_orcamentos(request):
    orcamentos = OrcamentoMedicao.objects.select_related('obra')
    return render(request, 'medicoes/lista_orcamentos.html', {'orcamentos': orcamentos})


def importar_orcamento(request):
    if request.method == 'POST':
        form = ImportarOrcamentoForm(request.POST, request.FILES)
        if form.is_valid():
            reader, error = _read_csv(form.cleaned_data['arquivo'])
            if error:
                form.add_error('arquivo', error)
                return render(request, 'medicoes/importar_orcamento.html', {'form': form})
            with transaction.atomic():
                orcamento = OrcamentoMedicao.objects.create(
                    obra=form.cleaned_data['obra'],
                    nome=form.cleaned_data['nome'],
                    tipo=form.cleaned_data['tipo'],
                    observacoes=form.cleaned_data['observacoes'],
                )
                itens = []
                for row in reader:
                    descricao = _value(row, 'descricao').strip()
                    if not descricao:
                        continue
                    itens.append(
                        ItemOrcamentoMedicao(
                            orcamento=orcamento,
                            item=_value(row, 'item').strip() or str(len(itens) + 1),
                            descricao=descricao,
                            unidade=_value(row, 'unidade').strip(),
                            quantidade=_decimal(_value(row, 'quantidade')),
                            preco_unitario_material=_decimal(_value(row, 'preco_unitario_material')),
                            preco_unitario_mao_obra=_decimal(_value(row, 'preco_unitario_mao_obra')),
                            preco_unitario_equipamentos=_decimal(_value(row, 'preco_unitario_equipamentos')),
                        )
                    )
                ItemOrcamentoMedicao.objects.bulk_create(itens)
                if not itens:
                    transaction.set_rollback(True)
                    form.add_error('arquivo', 'Nenhum item valido foi encontrado no CSV.')
                    return render(request, 'medicoes/importar_orcamento.html', {'form': form})
            messages.success(request, f'Planilha de medicao importada com {len(itens)} itens.')
            return redirect('detalhe_orcamento_medicao', orcamento_id=orcamento.id)
    else:
        initial = {}
        if request.GET.get('obra'):
            initial['obra'] = request.GET['obra']
        form = ImportarOrcamentoForm(initial=initial)
    return render(request, 'medicoes/importar_orcamento.html', {'form': form})


def novo_orcamento_manual(request):
    tipo = request.GET.get('tipo')
    if tipo not in {OrcamentoMedicao.TIPO_CONSTRUTORA, OrcamentoMedicao.TIPO_EMPREITEIRO}:
        tipo = OrcamentoMedicao.TIPO_CONSTRUTORA
    initial = {'tipo': tipo}
    if request.GET.get('obra'):
        initial['obra'] = request.GET['obra']
    if request.method == 'POST':
        form = OrcamentoMedicaoManualForm(request.POST)
        if form.is_valid():
            orcamento = form.save()
            messages.success(request, 'Planilha manual criada. Agora adicione os itens para usar nas medicoes.')
            return redirect('editar_itens_orcamento_medicao', orcamento_id=orcamento.id)
    else:
        form = OrcamentoMedicaoManualForm(initial=initial)
    return render(
        request,
        'medicoes/form_orcamento_manual.html',
        {
            'form': form,
            'titulo': 'Nova planilha manual de medicao',
        },
    )


def detalhe_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoMedicao.objects.select_related('obra'), id=orcamento_id)
    itens = orcamento.itens.all()
    medicoes_construtora = orcamento.medicoes_construtora.all()
    medicoes_empreiteiro = orcamento.medicoes_empreiteiro.all()
    return render(
        request,
        'medicoes/detalhe_orcamento.html',
        {
            'orcamento': orcamento,
            'itens': itens,
            'medicoes_construtora': medicoes_construtora,
            'medicoes_empreiteiro': medicoes_empreiteiro,
        },
    )


def editar_itens_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoMedicao.objects.select_related('obra'), id=orcamento_id)
    if request.method == 'POST':
        formset = ItemOrcamentoMedicaoFormSet(request.POST, instance=orcamento)
        if formset.is_valid():
            formset.save()
            messages.success(request, 'Itens da planilha atualizados com sucesso.')
            return redirect('detalhe_orcamento_medicao', orcamento_id=orcamento.id)
    else:
        formset = ItemOrcamentoMedicaoFormSet(instance=orcamento)
    return render(
        request,
        'medicoes/editar_itens_orcamento.html',
        {
            'orcamento': orcamento,
            'formset': formset,
        },
    )


def excluir_orcamento(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoMedicao.objects.select_related('obra'), id=orcamento_id)
    obra_id = orcamento.obra_id
    if request.method == 'POST':
        orcamento.delete()
        messages.success(request, 'Planilha importada excluida com sucesso.')
        return redirect('medicoes_obra', obra_id=obra_id)
    return render(
        request,
        'medicoes/confirmar_exclusao_orcamento.html',
        {
            'orcamento': orcamento,
        },
    )


def nova_medicao_construtora(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoMedicao, id=orcamento_id)
    initial = {
        'numero': _next_numero(MedicaoConstrutora, orcamento=orcamento),
        'data_medicao': timezone.localdate(),
        'periodo_inicio': timezone.localdate(),
        'periodo_fim': timezone.localdate(),
    }
    if request.method == 'POST':
        form = MedicaoConstrutoraCabecalhoForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                medicao = form.save(commit=False)
                medicao.orcamento = orcamento
                medicao.save()
                ItemMedicaoConstrutora.objects.bulk_create(
                    [ItemMedicaoConstrutora(medicao=medicao, item_orcamento=item) for item in orcamento.itens.all()]
                )
            messages.success(request, 'Medicao criada. Agora preencha as quantidades medidas.')
            return redirect('editar_medicao_construtora', medicao_id=medicao.id)
    else:
        form = MedicaoConstrutoraCabecalhoForm(initial=initial)
    return render(request, 'medicoes/form_medicao.html', {'form': form, 'titulo': 'Nova medicao da construtora'})


def editar_medicao_construtora(request, medicao_id):
    medicao = get_object_or_404(MedicaoConstrutora.objects.select_related('orcamento', 'orcamento__obra'), id=medicao_id)
    if not medicao.itens.exists():
        ItemMedicaoConstrutora.objects.bulk_create(
            [ItemMedicaoConstrutora(medicao=medicao, item_orcamento=item) for item in medicao.orcamento.itens.all()]
        )
    if request.method == 'POST':
        form = MedicaoConstrutoraForm(request.POST, instance=medicao)
        formset = ItemMedicaoConstrutoraFormSet(request.POST, instance=medicao)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            _sync_faturamentos_diretos(medicao, request.POST)
            _aplicar_percentuais_construtora(medicao)
            messages.success(request, 'Medicao da construtora atualizada com sucesso.')
            return redirect('editar_medicao_construtora', medicao_id=medicao.id)
    else:
        form = MedicaoConstrutoraForm(instance=medicao)
        formset = ItemMedicaoConstrutoraFormSet(instance=medicao)
    faturamentos_ja_descontados = FaturamentoDireto.objects.filter(
        obra=medicao.orcamento.obra,
        vinculos_medicao__isnull=False,
    ).exclude(
        vinculos_medicao__medicao=medicao,
    ).distinct().order_by('data_lancamento', 'id')
    return render(
        request,
        'medicoes/editar_medicao_construtora.html',
        {
            'medicao': medicao,
            'form': form,
            'formset': formset,
            'faturamentos_diretos_linhas': _faturamentos_diretos_context(medicao),
            'faturamentos_ja_descontados': faturamentos_ja_descontados,
        },
    )


def excluir_medicao_construtora(request, medicao_id):
    medicao = get_object_or_404(MedicaoConstrutora.objects.select_related('orcamento'), id=medicao_id)
    orcamento_id = medicao.orcamento_id
    if request.method == 'POST':
        medicao.delete()
        messages.success(request, 'Medicao da construtora excluida com sucesso.')
        return redirect('detalhe_orcamento_medicao', orcamento_id=orcamento_id)
    return render(
        request,
        'medicoes/confirmar_exclusao_medicao.html',
        {
            'titulo': 'Excluir medicao da construtora',
            'descricao': f'Medicao {medicao.numero} - {medicao.orcamento}',
            'voltar_url': 'editar_medicao_construtora',
            'voltar_arg': medicao.id,
        },
    )


def nova_medicao_empreiteiro_simples(request):
    if request.method == 'POST':
        form = MedicaoEmpreiteiroCabecalhoForm(request.POST)
        formset = ItemMedicaoEmpreiteiroFormSet(request.POST)
        if form.is_valid():
            medicao = form.save(commit=False)
            medicao.tipo = MedicaoEmpreiteiro.TIPO_SIMPLES
            medicao.save()
            _sync_empreiteiro_medicao(medicao)
            formset = ItemMedicaoEmpreiteiroFormSet(request.POST, instance=medicao)
            if formset.is_valid():
                formset.save()
                messages.success(request, 'Medicao simples de empreiteiro criada.')
                return redirect('editar_medicao_empreiteiro', medicao_id=medicao.id)
            medicao.delete()
    else:
        initial = {
            'numero': _next_numero(MedicaoEmpreiteiro, tipo=MedicaoEmpreiteiro.TIPO_SIMPLES),
            'data_medicao': timezone.localdate(),
            'periodo_inicio': timezone.localdate(),
            'periodo_fim': timezone.localdate(),
        }
        if request.GET.get('obra'):
            initial['obra'] = request.GET['obra']
        form = MedicaoEmpreiteiroCabecalhoForm(initial=initial)
        formset = ItemMedicaoEmpreiteiroFormSet()
    return render(
        request,
        'medicoes/editar_medicao_empreiteiro_simples.html',
        {
            'form': form,
            'formset': formset,
            'titulo': 'Nova medicao simples de empreiteiro',
            'empreiteiros_json': _empreiteiros_json(),
        },
    )


def nova_medicao_empreiteiro_cumulativa(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoMedicao, id=orcamento_id)
    initial = {
        'obra': orcamento.obra,
        'numero': _next_numero(MedicaoEmpreiteiro, orcamento=orcamento),
        'data_medicao': timezone.localdate(),
        'periodo_inicio': timezone.localdate(),
        'periodo_fim': timezone.localdate(),
    }
    ultima_medicao = MedicaoEmpreiteiro.objects.filter(
        orcamento=orcamento,
        tipo=MedicaoEmpreiteiro.TIPO_CUMULATIVA,
    ).select_related('empreiteiro_cadastro').order_by('-numero', '-id').first()
    if ultima_medicao:
        initial.update(
            {
                'obra': ultima_medicao.obra_id or orcamento.obra_id,
                'empreiteiro_cadastro': ultima_medicao.empreiteiro_cadastro_id,
                'empreiteiro': ultima_medicao.empreiteiro,
                'cpf_cnpj': ultima_medicao.cpf_cnpj,
                'pix': ultima_medicao.pix,
            }
        )
    if request.method == 'POST':
        form = MedicaoEmpreiteiroCabecalhoForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                medicao = form.save(commit=False)
                medicao.tipo = MedicaoEmpreiteiro.TIPO_CUMULATIVA
                medicao.orcamento = orcamento
                medicao.obra = medicao.obra or orcamento.obra
                medicao.save()
                _sync_empreiteiro_medicao(medicao)
                ItemMedicaoEmpreiteiro.objects.bulk_create(
                    [
                        ItemMedicaoEmpreiteiro(
                            medicao=medicao,
                            item_orcamento=item,
                            item=item.item,
                            descricao=item.descricao,
                            unidade=item.unidade,
                            valor_unitario=item.preco_unitario_total,
                        )
                        for item in orcamento.itens.all()
                    ]
                )
            messages.success(request, 'Medicao cumulativa criada. Agora preencha as quantidades medidas.')
            return redirect('editar_medicao_empreiteiro', medicao_id=medicao.id)
    else:
        form = MedicaoEmpreiteiroCabecalhoForm(initial=initial)
    return render(
        request,
        'medicoes/form_medicao.html',
        {
            'form': form,
            'titulo': 'Nova medicao cumulativa de empreiteiro',
            'empreiteiros_json': _empreiteiros_json(),
        },
    )


def editar_medicao_empreiteiro(request, medicao_id):
    medicao = get_object_or_404(MedicaoEmpreiteiro.objects.select_related('obra', 'orcamento'), id=medicao_id)
    if request.method == 'POST':
        form = MedicaoEmpreiteiroForm(request.POST, instance=medicao)
        formset = ItemMedicaoEmpreiteiroFormSet(request.POST, instance=medicao, orcamento=medicao.orcamento)
        if form.is_valid() and formset.is_valid():
            form.save()
            _sync_empreiteiro_medicao(medicao)
            formset.save()
            _aplicar_percentuais_empreiteiro(medicao)
            messages.success(request, 'Medicao de empreiteiro atualizada com sucesso.')
            return redirect('editar_medicao_empreiteiro', medicao_id=medicao.id)
    else:
        form = MedicaoEmpreiteiroForm(instance=medicao)
        formset = ItemMedicaoEmpreiteiroFormSet(instance=medicao, orcamento=medicao.orcamento)
    template = (
        'medicoes/editar_medicao_empreiteiro_simples.html'
        if medicao.tipo == MedicaoEmpreiteiro.TIPO_SIMPLES
        else 'medicoes/editar_medicao_empreiteiro.html'
    )
    return render(
        request,
        template,
        {
            'medicao': medicao,
            'form': form,
            'formset': formset,
            'titulo': 'Medicao de empreiteiro',
            'empreiteiros_json': _empreiteiros_json(),
        },
    )


def excluir_medicao_empreiteiro(request, medicao_id):
    medicao = get_object_or_404(MedicaoEmpreiteiro.objects.select_related('orcamento'), id=medicao_id)
    orcamento_id = medicao.orcamento_id
    if request.method == 'POST':
        medicao.delete()
        messages.success(request, 'Medicao de empreiteiro excluida com sucesso.')
        if orcamento_id:
            return redirect('detalhe_orcamento_medicao', orcamento_id=orcamento_id)
        return redirect('medicoes_empreiteiros_home')
    return render(
        request,
        'medicoes/confirmar_exclusao_medicao.html',
        {
            'titulo': 'Excluir medicao de empreiteiro',
            'descricao': f'Medicao {medicao.numero} - {medicao.empreiteiro}',
            'voltar_url': 'editar_medicao_empreiteiro',
            'voltar_arg': medicao.id,
        },
    )


def _linhas_pdf_medicao(medicao, itens, titulo):
    lines = [
        titulo.upper(),
        f'Emitido em {date.today().strftime("%d/%m/%Y")}',
        f'Obra: {getattr(getattr(medicao, "orcamento", None), "obra", None) or medicao.obra or "-"}',
        f'Medicao: {medicao.numero} | Periodo: {medicao.periodo_inicio:%d/%m/%Y} a {medicao.periodo_fim:%d/%m/%Y}',
        '',
        'ITEM | DESCRICAO | UND | CONTRATO | ANT. | PERIODO | ATUAL | SALDO | VALOR',
    ]
    for item in itens:
        contrato = getattr(getattr(item, 'item_orcamento', None), 'quantidade', Decimal('0'))
        lines.append(
            ' | '.join(
                [
                    (getattr(getattr(item, 'item_orcamento', None), 'item', '') or item.item)[:8],
                    item.descricao[:24] if hasattr(item, 'descricao') else item.item_orcamento.descricao[:24],
                    (item.unidade if hasattr(item, 'unidade') else item.item_orcamento.unidade)[:5],
                    f'{contrato:.4f}',
                    f'{item.quantidade_acumulada_anterior:.4f}',
                    f'{item.quantidade_periodo:.4f}',
                    f'{item.quantidade_acumulada_atual:.4f}',
                    f'{item.saldo_quantidade:.4f}',
                    _money(item.valor_periodo),
                ]
            )
        )
    lines.extend(
        [
            '',
            f'Subtotal do periodo: {_money(medicao.subtotal_periodo)}',
            f'Retencao tecnica: {_money(medicao.retencao_tecnica_calculada if isinstance(medicao, MedicaoConstrutora) else medicao.retencao_tecnica)}',
        ]
    )
    if isinstance(medicao, MedicaoConstrutora):
        lines.extend(
            [
                f'ISSQN: {_money(medicao.issqn_calculado)}',
                f'INSS: {_money(medicao.inss_calculado)}',
                f'Faturamento direto descontado: {_money(medicao.total_faturamento_direto)}',
                f'Base de impostos: {_money(medicao.base_impostos)}',
                f'Base INSS: {_money(medicao.base_inss)}',
            ]
        )
    desconto = medicao.desconto_adicional_calculado if isinstance(medicao, MedicaoConstrutora) else medicao.desconto_adicional
    lines.extend([f'Desconto adicional: {_money(desconto)}', f'Total liquido: {_money(medicao.total_liquido)}'])
    pages = [lines[i : i + 30] for i in range(0, len(lines), 30)] or [[]]
    return _build_simple_pdf(pages)


def medicao_construtora_pdf(request, medicao_id):
    medicao = get_object_or_404(MedicaoConstrutora.objects.select_related('orcamento', 'orcamento__obra'), id=medicao_id)
    response = HttpResponse(
        _pdf_medicao_construtora(medicao),
        content_type='application/pdf',
    )
    response['Content-Disposition'] = f'inline; filename="medicao_construtora_{medicao.numero}.pdf"'
    return response


def medicao_empreiteiro_pdf(request, medicao_id):
    medicao = get_object_or_404(MedicaoEmpreiteiro.objects.select_related('obra', 'orcamento'), id=medicao_id)
    response = HttpResponse(_pdf_medicao_empreiteiro(medicao), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="medicao_empreiteiro_{medicao.numero}.pdf"'
    return response


def _pdf_medicao_empreiteiro(medicao):
    itens = list(medicao.itens.select_related('item_orcamento'))
    page_w, page_h = 1654, 2339
    margin = 92
    table_w = page_w - (margin * 2)
    rows_per_page = 25 if medicao.tipo == MedicaoEmpreiteiro.TIPO_SIMPLES else 22
    chunks = [itens[i : i + rows_per_page] for i in range(0, len(itens), rows_per_page)] or [[]]
    pages = []

    for page_index, chunk in enumerate(chunks):
        image = Image.new('RGB', (page_w, page_h), 'white')
        draw = ImageDraw.Draw(image)
        navy = (15, 23, 42)
        muted = (100, 116, 139)
        border = (203, 213, 225)
        soft = (248, 250, 252)

        draw.rectangle((0, 0, page_w, 130), fill=navy)
        draw.text((margin, 42), 'BOLETIM DE MEDICAO DE EMPREITEIRO', font=_font(34, True), fill='white')
        draw.text(
            (page_w - margin - 330, 50),
            f'Medicao no {medicao.numero}',
            font=_font(24, True),
            fill=(226, 232, 240),
        )

        y = 170
        draw.rounded_rectangle((margin, y, page_w - margin, y + 235), radius=10, fill=soft, outline=border, width=2)
        info = [
            ('Empreiteiro', medicao.empreiteiro),
            ('CPF/CNPJ', medicao.cpf_cnpj or '-'),
            ('PIX', medicao.pix or '-'),
            ('Obra', medicao.obra or getattr(medicao.orcamento, 'obra', '-') or '-'),
            ('Periodo', f'{medicao.periodo_inicio:%d/%m/%Y} a {medicao.periodo_fim:%d/%m/%Y}'),
            ('Data da medicao', f'{medicao.data_medicao:%d/%m/%Y}'),
        ]
        col_w = table_w / 3
        row_h = 105
        for index, (label, value) in enumerate(info):
            col = index % 3
            row = index // 3
            x0 = int(margin + col * col_w)
            y0 = y + 18 + row * row_h
            draw.text((x0 + 18, y0), label.upper(), font=_font(17, True), fill=muted)
            _draw_wrapped_cell(draw, value, x0 + 8, y0 + 26, int(col_w - 16), 60, _font(21), fill=navy)

        y += 285
        if medicao.tipo == MedicaoEmpreiteiro.TIPO_SIMPLES:
            headers = ['Item', 'Descricao', 'Und', 'Qtd', 'Valor unit.', 'Total']
            widths = [110, 610, 105, 150, 245, 250]
            rows = [
                [
                    item.item or '-',
                    item.descricao,
                    item.unidade or '-',
                    f'{item.quantidade_periodo:.4f}',
                    _money(item.valor_unitario),
                    _money(item.valor_periodo),
                ]
                for item in chunk
            ]
        else:
            headers = ['Item', 'Descricao', 'Und', 'Anterior', 'Periodo', 'Atual', 'Saldo', 'Total']
            widths = [95, 500, 85, 135, 135, 135, 135, 250]
            rows = [
                [
                    item.item or '-',
                    item.descricao,
                    item.unidade or '-',
                    f'{item.quantidade_acumulada_anterior:.4f}',
                    f'{item.quantidade_periodo:.4f}',
                    f'{item.quantidade_acumulada_atual:.4f}',
                    f'{item.saldo_quantidade:.4f}',
                    _money(item.valor_periodo),
                ]
                for item in chunk
            ]

        y = _draw_pdf_table(draw, headers, rows, margin, y, widths)

        if page_index == len(chunks) - 1:
            y += 35
            summary_x = page_w - margin - 540
            summary_w = 540
            summary_rows = [
                ('Subtotal medido', medicao.subtotal_periodo),
                ('Retencao tecnica', -medicao.retencao_tecnica),
                ('Desconto adicional', -medicao.desconto_adicional),
                ('Total liquido', medicao.total_liquido),
            ]
            draw.rounded_rectangle((summary_x, y, summary_x + summary_w, y + 240), radius=8, fill=soft, outline=border, width=2)
            row_y = y + 18
            for label, value in summary_rows:
                is_total = label == 'Total liquido'
                draw.text((summary_x + 24, row_y), label, font=_font(21, is_total), fill=navy)
                amount = _money(abs(value))
                if value < 0:
                    amount = f'- {amount}'
                draw.text(
                    (summary_x + summary_w - 28 - _font(21, is_total).getlength(amount), row_y),
                    amount,
                    font=_font(21, is_total),
                    fill=navy,
                )
                row_y += 52

            if medicao.observacoes:
                notes_y = min(y, page_h - 300)
                draw.text((margin, notes_y), 'Observacoes', font=_font(20, True), fill=navy)
                _draw_wrapped_cell(
                    draw,
                    medicao.observacoes,
                    margin - 8,
                    notes_y + 34,
                    table_w - summary_w - 40,
                    160,
                    _font(19),
                    fill=(51, 65, 85),
                )

        footer = f'Pagina {page_index + 1} de {len(chunks)}'
        draw.text((page_w - margin - _font(17).getlength(footer), page_h - 60), footer, font=_font(17), fill=muted)
        pages.append(image)

    buffer = BytesIO()
    pages[0].save(buffer, 'PDF', save_all=True, append_images=pages[1:], resolution=150)
    return buffer.getvalue()


def _xlsx_medicao(medicao, itens):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Medicao'
    ws.append(['Medicao', medicao.numero])
    ws.append(['Periodo', f'{medicao.periodo_inicio:%d/%m/%Y} a {medicao.periodo_fim:%d/%m/%Y}'])
    ws.append([])
    contract_fill = PatternFill('solid', fgColor='E8EEF7')
    measured_fill = PatternFill('solid', fgColor='DCF5E5')
    receivable_fill = PatternFill('solid', fgColor='FEE2E2')
    header_font = Font(bold=True)
    if isinstance(medicao, MedicaoConstrutora):
        column_widths = [9, 58, 8, 12, 16, 16, 16, 16, 16, 14, 12, 10, 16, 16, 16, 17]
        for col_index, width in enumerate(column_widths, start=1):
            ws.column_dimensions[get_column_letter(col_index)].width = width
        ws.append(
            [
                'Itens contratuais',
                '',
                '',
                '',
                '',
                '',
                '',
                '',
                'Itens medidos',
                '',
                '',
                '',
                'Valor a receber',
                '',
                '',
                '',
            ]
        )
        ws.append(
            [
                'Item',
                'Descricao',
                'Unidade',
                'Contrato',
                'Unitario material',
                'Unitario mao de obra',
                'Unitario equipamentos',
                'Unitario total',
                'Valor anterior',
                'Acumulado anterior',
                'Periodo',
                '% executado',
                'Valor material',
                'Valor mao de obra',
                'Valor equipamentos',
                'Valor total',
            ]
        )
        ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=8)
        ws.merge_cells(start_row=4, start_column=9, end_row=4, end_column=12)
        ws.merge_cells(start_row=4, start_column=13, end_row=4, end_column=16)
        for row in (4, 5):
            for col in range(1, 17):
                if col <= 8:
                    fill = contract_fill
                elif col <= 12:
                    fill = measured_fill
                else:
                    fill = receivable_fill
                cell = ws.cell(row=row, column=col)
                cell.fill = fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    else:
        ws.append(['Item', 'Descricao', 'Unidade', 'Contrato', 'Acumulado anterior', 'Periodo', 'Acumulado atual', 'Saldo', 'Valor'])
    for item in itens:
        contrato = getattr(getattr(item, 'item_orcamento', None), 'quantidade', Decimal('0'))
        base = getattr(item, 'item_orcamento', None)
        row = [
            getattr(base, 'item', '') or getattr(item, 'item', ''),
            item.descricao if hasattr(item, 'descricao') else base.descricao,
            item.unidade if hasattr(item, 'unidade') else base.unidade,
            float(contrato),
        ]
        if isinstance(medicao, MedicaoConstrutora):
            valor_anterior = item.quantidade_acumulada_anterior * base.preco_unitario_total
            row.extend(
                [
                    float(base.preco_unitario_material),
                    float(base.preco_unitario_mao_obra),
                    float(base.preco_unitario_equipamentos),
                    float(base.preco_unitario_total),
                    float(valor_anterior),
                    float(item.quantidade_acumulada_anterior),
                    float(item.quantidade_periodo),
                    float(_percent_from_item(item)),
                    float(item.valor_material_periodo),
                    float(item.valor_mao_obra_periodo),
                    float(item.valor_equipamentos_periodo),
                    float(item.valor_periodo),
                ]
            )
        else:
            row.extend(
                [
                    float(item.quantidade_acumulada_anterior),
                    float(item.quantidade_periodo),
                    float(item.quantidade_acumulada_atual),
                    float(item.saldo_quantidade),
                ]
            )
            row.append(float(item.valor_periodo))
        ws.append(row)
        if isinstance(medicao, MedicaoConstrutora):
            for col in range(1, 17):
                horizontal = 'left' if col == 2 else 'center'
                ws.cell(row=ws.max_row, column=col).alignment = Alignment(
                    horizontal=horizontal,
                    vertical='center',
                    wrap_text=True,
                )
            for col in range(9, 13):
                ws.cell(row=ws.max_row, column=col).fill = measured_fill
    ws.append([])
    ws.append(['Valor bruto', float(medicao.total_bruto if isinstance(medicao, MedicaoConstrutora) else medicao.subtotal_periodo)])
    if isinstance(medicao, MedicaoConstrutora):
        ws.append(['Total material medido', float(medicao.total_material_periodo)])
        ws.append(['Total mao de obra medida', float(medicao.total_mao_obra_periodo)])
        ws.append(['Total equipamentos medido', float(medicao.total_equipamentos_periodo)])
    ws.append(['Retencao tecnica', float(medicao.retencao_tecnica_calculada if isinstance(medicao, MedicaoConstrutora) else medicao.retencao_tecnica)])
    if isinstance(medicao, MedicaoConstrutora):
        ws.append(['ISSQN', float(medicao.issqn_calculado)])
        ws.append(['INSS', float(medicao.inss_calculado)])
        ws.append(['Faturamento direto descontado', float(medicao.total_faturamento_direto)])
        ws.append(['Base de impostos', float(medicao.base_impostos)])
        ws.append(['Material para NF', float(medicao.valor_material_nf)])
        ws.append(['Mao de obra para NF', float(medicao.valor_mao_obra_nf)])
        ws.append(['Equipamentos para NF', float(medicao.valor_equipamentos_nf)])
        ws.append(['Base INSS', float(medicao.base_inss)])
    ws.append(['Desconto adicional', float(medicao.desconto_adicional_calculado if isinstance(medicao, MedicaoConstrutora) else medicao.desconto_adicional)])
    ws.append(['Total liquido', float(medicao.total_liquido)])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def medicao_construtora_excel(request, medicao_id):
    medicao = get_object_or_404(MedicaoConstrutora, id=medicao_id)
    response = HttpResponse(
        _xlsx_medicao(medicao, medicao.itens.select_related('item_orcamento')),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="medicao_construtora_{medicao.numero}.xlsx"'
    return response


def medicao_empreiteiro_excel(request, medicao_id):
    medicao = get_object_or_404(MedicaoEmpreiteiro, id=medicao_id)
    response = HttpResponse(
        _xlsx_medicao(medicao, medicao.itens.select_related('item_orcamento')),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="medicao_empreiteiro_{medicao.numero}.xlsx"'
    return response
