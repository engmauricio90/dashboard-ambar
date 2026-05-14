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
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont

from controles.views import _build_simple_pdf
from obras.models import Obra

from .forms import (
    ImportarOrcamentoForm,
    ItemMedicaoConstrutoraFormSet,
    ItemMedicaoEmpreiteiroFormSet,
    MedicaoConstrutoraCabecalhoForm,
    MedicaoConstrutoraForm,
    MedicaoEmpreiteiroCabecalhoForm,
    MedicaoEmpreiteiroForm,
)
from .models import (
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
    'preco_unitario_material': ['precounitariomaterial', 'unitariomaterial', 'material'],
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
        'inss': (medicao.base_impostos, medicao.inss_percentual),
    }
    updates = []
    for field, (base, percent) in campos.items():
        value = _percent_value(base, percent)
        if value is not None:
            setattr(medicao, field, value)
            updates.append(field)
    if updates:
        medicao.save(update_fields=updates + ['updated_at'])


def _sync_faturamentos_diretos(medicao, faturamentos):
    selecionados = set(faturamentos.values_list('id', flat=True)) if hasattr(faturamentos, 'values_list') else {f.id for f in faturamentos}
    atuais = set(medicao.faturamentos_diretos.values_list('faturamento_direto_id', flat=True))
    remover = atuais - selecionados
    adicionar = selecionados - atuais
    if remover:
        removidos = FaturamentoDiretoMedicao.objects.filter(medicao=medicao, faturamento_direto_id__in=remover)
        for vinculo in removidos.select_related('faturamento_direto'):
            faturamento = vinculo.faturamento_direto
            if faturamento.medicao_desconto == medicao.label_medicao:
                faturamento.medicao_desconto = ''
                faturamento.save(update_fields=['medicao_desconto', 'updated_at'])
        removidos.delete()
    for faturamento_id in adicionar:
        vinculo, _ = FaturamentoDiretoMedicao.objects.get_or_create(
            medicao=medicao,
            faturamento_direto_id=faturamento_id,
        )
        faturamento = vinculo.faturamento_direto
        faturamento.medicao_desconto = medicao.label_medicao
        faturamento.save(update_fields=['medicao_desconto', 'updated_at'])
    if selecionados:
        for vinculo in FaturamentoDiretoMedicao.objects.filter(
            medicao=medicao,
            faturamento_direto_id__in=selecionados,
        ).select_related('faturamento_direto'):
            faturamento = vinculo.faturamento_direto
            if faturamento.medicao_desconto != medicao.label_medicao:
                faturamento.medicao_desconto = medicao.label_medicao
                faturamento.save(update_fields=['medicao_desconto', 'updated_at'])


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
    contexto = {
        'obras': Obra.objects.filter(orcamentos_medicao__isnull=False).distinct().order_by('nome_obra')[:12],
        'orcamentos': OrcamentoMedicao.objects.select_related('obra')[:8],
        'medicoes_construtora': MedicaoConstrutora.objects.select_related('orcamento', 'orcamento__obra')[:8],
        'medicoes_empreiteiro': MedicaoEmpreiteiro.objects.select_related('obra', 'orcamento')[:8],
    }
    return render(request, 'medicoes/home.html', contexto)


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
            _sync_faturamentos_diretos(medicao, form.cleaned_data['faturamentos_diretos'])
            _aplicar_percentuais_construtora(medicao)
            messages.success(request, 'Medicao da construtora atualizada com sucesso.')
            return redirect('editar_medicao_construtora', medicao_id=medicao.id)
    else:
        form = MedicaoConstrutoraForm(instance=medicao)
        formset = ItemMedicaoConstrutoraFormSet(instance=medicao)
    return render(
        request,
        'medicoes/editar_medicao_construtora.html',
        {'medicao': medicao, 'form': form, 'formset': formset},
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
        if form.is_valid():
            medicao = form.save(commit=False)
            medicao.tipo = MedicaoEmpreiteiro.TIPO_SIMPLES
            medicao.save()
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
        'medicoes/editar_medicao_empreiteiro.html',
        {'form': form, 'formset': formset, 'titulo': 'Nova medicao simples de empreiteiro'},
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
    if request.method == 'POST':
        form = MedicaoEmpreiteiroCabecalhoForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                medicao = form.save(commit=False)
                medicao.tipo = MedicaoEmpreiteiro.TIPO_CUMULATIVA
                medicao.orcamento = orcamento
                medicao.obra = medicao.obra or orcamento.obra
                medicao.save()
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
    return render(request, 'medicoes/form_medicao.html', {'form': form, 'titulo': 'Nova medicao cumulativa de empreiteiro'})


def editar_medicao_empreiteiro(request, medicao_id):
    medicao = get_object_or_404(MedicaoEmpreiteiro.objects.select_related('obra', 'orcamento'), id=medicao_id)
    if request.method == 'POST':
        form = MedicaoEmpreiteiroForm(request.POST, instance=medicao)
        formset = ItemMedicaoEmpreiteiroFormSet(request.POST, instance=medicao, orcamento=medicao.orcamento)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            _aplicar_percentuais_empreiteiro(medicao)
            messages.success(request, 'Medicao de empreiteiro atualizada com sucesso.')
            return redirect('editar_medicao_empreiteiro', medicao_id=medicao.id)
    else:
        form = MedicaoEmpreiteiroForm(instance=medicao)
        formset = ItemMedicaoEmpreiteiroFormSet(instance=medicao, orcamento=medicao.orcamento)
    return render(
        request,
        'medicoes/editar_medicao_empreiteiro.html',
        {'medicao': medicao, 'form': form, 'formset': formset, 'titulo': 'Medicao de empreiteiro'},
    )


def excluir_medicao_empreiteiro(request, medicao_id):
    medicao = get_object_or_404(MedicaoEmpreiteiro.objects.select_related('orcamento'), id=medicao_id)
    orcamento_id = medicao.orcamento_id
    if request.method == 'POST':
        medicao.delete()
        messages.success(request, 'Medicao de empreiteiro excluida com sucesso.')
        if orcamento_id:
            return redirect('detalhe_orcamento_medicao', orcamento_id=orcamento_id)
        return redirect('medicoes_home')
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
            f'Retencao tecnica: {_money(medicao.retencao_tecnica)}',
        ]
    )
    if isinstance(medicao, MedicaoConstrutora):
        lines.extend(
            [
                f'ISSQN: {_money(medicao.issqn)}',
                f'INSS: {_money(medicao.inss)}',
                f'Faturamento direto descontado: {_money(medicao.total_faturamento_direto)}',
                f'Base de impostos: {_money(medicao.base_impostos)}',
            ]
        )
    lines.extend([f'Desconto adicional: {_money(medicao.desconto_adicional)}', f'Total liquido: {_money(medicao.total_liquido)}'])
    pages = [lines[i : i + 30] for i in range(0, len(lines), 30)] or [[]]
    return _build_simple_pdf(pages)


def medicao_construtora_pdf(request, medicao_id):
    medicao = get_object_or_404(MedicaoConstrutora.objects.select_related('orcamento', 'orcamento__obra'), id=medicao_id)
    response = HttpResponse(
        _linhas_pdf_medicao(medicao, medicao.itens.select_related('item_orcamento'), 'Boletim de medicao da construtora'),
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
    ws.append(['Item', 'Descricao', 'Unidade', 'Contrato', 'Acumulado anterior', 'Periodo', 'Acumulado atual', 'Saldo', 'Valor'])
    for item in itens:
        contrato = getattr(getattr(item, 'item_orcamento', None), 'quantidade', Decimal('0'))
        ws.append(
            [
                getattr(getattr(item, 'item_orcamento', None), 'item', '') or item.item,
                item.descricao if hasattr(item, 'descricao') else item.item_orcamento.descricao,
                item.unidade if hasattr(item, 'unidade') else item.item_orcamento.unidade,
                float(contrato),
                float(item.quantidade_acumulada_anterior),
                float(item.quantidade_periodo),
                float(item.quantidade_acumulada_atual),
                float(item.saldo_quantidade),
                float(item.valor_periodo),
            ]
        )
    ws.append([])
    ws.append(['Valor bruto', float(medicao.total_bruto if isinstance(medicao, MedicaoConstrutora) else medicao.subtotal_periodo)])
    ws.append(['Retencao tecnica', float(medicao.retencao_tecnica)])
    if isinstance(medicao, MedicaoConstrutora):
        ws.append(['ISSQN', float(medicao.issqn)])
        ws.append(['INSS', float(medicao.inss)])
        ws.append(['Faturamento direto descontado', float(medicao.total_faturamento_direto)])
        ws.append(['Base de impostos', float(medicao.base_impostos)])
    ws.append(['Desconto adicional', float(medicao.desconto_adicional)])
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
