from decimal import Decimal
from datetime import timedelta
import calendar
from io import BytesIO
from pathlib import Path
import textwrap
import unicodedata

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from PIL import Image, ImageDraw, ImageFont

from financeiro.models import ContaPagar, Fornecedor
from obras.models import Obra

from .forms import (
    ApontamentoMaquinaLocacaoForm,
    BaixarLocacaoEquipamentoForm,
    BombonaCombustivelForm,
    ContratoConcretagemForm,
    CronogramaObraForm,
    EquipamentoLocadoCatalogoForm,
    FornecedorMaquinaLocacaoForm,
    FaturamentoConcretagemForm,
    FaturamentoDiretoForm,
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
    CronogramaObra,
    EquipamentoLocadoCatalogo,
    FornecedorMaquinaLocacao,
    FaturamentoConcretagem,
    FaturamentoDireto,
    LinhaCronogramaObra,
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


def _report_pdf_response_pages(images, filename):
    buffer = BytesIO()
    images[0].save(buffer, 'PDF', save_all=True, append_images=images[1:], resolution=150)
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


def _add_month(value):
    year = value.year + (value.month // 12)
    month = (value.month % 12) + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _periodos_cronograma(cronograma):
    periodos = []
    atual = cronograma.data_inicio
    index = 0
    while atual <= cronograma.data_fim:
        if cronograma.formato == CronogramaObra.FORMATO_DIA:
            fim = atual
            label = atual.strftime('%d')
            grupo = atual.strftime('%m/%y')
            proximo = atual + timedelta(days=1)
        elif cronograma.formato == CronogramaObra.FORMATO_MES:
            fim_mes = atual.replace(day=calendar.monthrange(atual.year, atual.month)[1])
            fim = min(fim_mes, cronograma.data_fim)
            label = atual.strftime('%m/%y')
            grupo = atual.strftime('%Y')
            proximo = _add_month(atual.replace(day=1))
        else:
            fim = min(atual + timedelta(days=6), cronograma.data_fim)
            label = f'{atual:%d/%m} a {fim:%d/%m}'
            grupo = atual.strftime('%Y')
            proximo = fim + timedelta(days=1)
        periodos.append(
            {
                'key': str(index),
                'inicio': atual,
                'fim': fim,
                'label': label,
                'grupo': grupo,
            }
        )
        atual = proximo
        index += 1
    return periodos


def _grupos_periodos(periodos):
    grupos = []
    for periodo in periodos:
        if not grupos or grupos[-1]['label'] != periodo['grupo']:
            grupos.append({'label': periodo['grupo'], 'colspan': 0})
        grupos[-1]['colspan'] += 1
    return grupos


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
        'faturamentos_diretos': FaturamentoDireto.objects.count(),
        'cronogramas_obras': CronogramaObra.objects.count(),
        'total_abastecido': sum(
            RegistroAbastecimento.objects.values_list('valor_total', flat=True),
            Decimal('0'),
        ),
    }
    return render(request, 'controles/home.html', totais)


def lista_cronogramas_obras(request):
    cronogramas = CronogramaObra.objects.select_related('obra').prefetch_related('linhas')
    busca = request.GET.get('busca', '').strip()
    if busca:
        cronogramas = cronogramas.filter(
            Q(nome__icontains=busca)
            | Q(obra__nome_obra__icontains=busca)
            | Q(observacoes__icontains=busca)
        )
    return render(
        request,
        'controles/lista_cronogramas_obras.html',
        {'cronogramas': cronogramas, 'busca': busca},
    )


def novo_cronograma_obra(request):
    if request.method == 'POST':
        form = CronogramaObraForm(request.POST)
        if form.is_valid():
            cronograma = form.save()
            messages.success(request, 'Cronograma criado. Agora adicione os servicos na grade.')
            return redirect('editar_cronograma_obra', cronograma_id=cronograma.id)
    else:
        form = CronogramaObraForm()
    return render(
        request,
        'controles/form_cronograma_obra.html',
        {'form': form, 'titulo': 'Novo cronograma de obra'},
    )


def editar_cronograma_obra(request, cronograma_id):
    cronograma = get_object_or_404(CronogramaObra.objects.select_related('obra'), id=cronograma_id)
    if request.method == 'POST':
        form = CronogramaObraForm(request.POST, instance=cronograma)
        if form.is_valid():
            with transaction.atomic():
                cronograma = form.save()
                total_linhas = int(request.POST.get('linhas-TOTAL_FORMS') or 0)
                for index in range(total_linhas):
                    linha_id = request.POST.get(f'linhas-{index}-id')
                    tipo = request.POST.get(f'linhas-{index}-tipo') or LinhaCronogramaObra.TIPO_SERVICO
                    servico = (request.POST.get(f'linhas-{index}-servico') or '').strip()
                    excluir = request.POST.get(f'linhas-{index}-DELETE')
                    periodos = request.POST.getlist(f'linhas-{index}-periodos')
                    linha = LinhaCronogramaObra.objects.filter(cronograma=cronograma, id=linha_id).first() if linha_id else None
                    if excluir and linha:
                        linha.delete()
                        continue
                    if not servico:
                        continue
                    if not linha:
                        linha = LinhaCronogramaObra(cronograma=cronograma)
                    linha.ordem = index + 1
                    linha.tipo = tipo if tipo in {LinhaCronogramaObra.TIPO_SERVICO, LinhaCronogramaObra.TIPO_GERAL} else LinhaCronogramaObra.TIPO_SERVICO
                    linha.servico = servico
                    linha.periodos = periodos
                    linha.save()
            messages.success(request, 'Cronograma salvo com sucesso.')
            return redirect('editar_cronograma_obra', cronograma_id=cronograma.id)
    else:
        form = CronogramaObraForm(instance=cronograma)
    periodos = _periodos_cronograma(cronograma)
    return render(
        request,
        'controles/editar_cronograma_obra.html',
        {
            'cronograma': cronograma,
            'form': form,
            'linhas': cronograma.linhas.all(),
            'periodos': periodos,
            'grupos_periodos': _grupos_periodos(periodos),
        },
    )


def cronograma_obra_pdf(request, cronograma_id):
    cronograma = get_object_or_404(CronogramaObra.objects.select_related('obra').prefetch_related('linhas'), id=cronograma_id)
    periodos = _periodos_cronograma(cronograma)
    linhas = list(cronograma.linhas.all())
    page_w, page_h = 1754, 1240
    margin = 62
    header_h = 176
    footer_h = 34
    available_w = page_w - (margin * 2)
    available_h = page_h - header_h - footer_h - margin
    border = (0, 0, 0)
    fill_active = (166, 166, 166)
    fill_header = (247, 247, 247)
    title_font = _font(23, True)
    header_font = _font(17, True)
    cell_font = _font(16)
    small_font = _font(12)
    small_bold_font = _font(12, True)
    footer_font = _font(12)

    def chunks(values, size):
        return [values[index : index + size] for index in range(0, len(values), size)] or [[]]

    def draw_logo(image):
        logo_source = Path(settings.BASE_DIR) / 'static' / 'propostas' / 'reference' / 'page_frame.png'
        if logo_source.exists():
            logo = Image.open(logo_source).convert('RGB').crop((500, 85, 1160, 250))
            logo.thumbnail((430, 105))
            image.paste(logo, ((page_w - logo.width) // 2, 8))
            return
        draw = ImageDraw.Draw(image)
        fallback_font = _font(42, True)
        draw.text(((page_w - fallback_font.getlength('AMBAR')) / 2, 28), 'AMBAR', font=fallback_font, fill=border)

    def draw_header(image, page_number, total_pages):
        draw = ImageDraw.Draw(image)
        draw_logo(image)
        title = f'Cronograma de atividades - {cronograma.nome}'
        if cronograma.obra:
            title = f'{title} - {cronograma.obra.nome_obra}'
        clean_title = _clean_pdf_text(title)
        fitted_title_font = title_font
        for size in range(23, 13, -1):
            candidate = _font(size, True)
            if candidate.getlength(clean_title) <= available_w - 24:
                fitted_title_font = candidate
                break
        title_y = 124
        draw.rectangle((margin, title_y, page_w - margin, title_y + 34), outline=border, width=2)
        draw.text(((page_w - fitted_title_font.getlength(clean_title)) / 2, title_y + 7), clean_title, font=fitted_title_font, fill=border)
        footer = f'Pagina {page_number} de {total_pages}'
        draw.text((page_w - margin - footer_font.getlength(footer), page_h - 34), footer, font=footer_font, fill=(80, 80, 80))

    def split_grupos(period_chunk):
        grupos = []
        for periodo in period_chunk:
            if not grupos or grupos[-1]['label'] != periodo['grupo']:
                grupos.append({'label': periodo['grupo'], 'colspan': 0})
            grupos[-1]['colspan'] += 1
        return grupos

    def draw_centered_wrapped(draw, value, x, y, w, h, font):
        text = _clean_pdf_text(value)
        avg_char_width = max(font.getlength('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz') / 52, 1)
        max_chars = max(int((w - 8) / avg_char_width), 4)
        lines = textwrap.wrap(text, width=max_chars) or ['']
        line_height = font.getbbox('Ag')[3] - font.getbbox('Ag')[1] + 2
        visible_lines = lines[: max(int((h - 6) / line_height), 1)]
        text_h = line_height * len(visible_lines)
        y_text = y + max((h - text_h) // 2, 3)
        for line in visible_lines:
            draw.text((x + (w - font.getlength(line)) / 2, y_text), line, font=font, fill=border)
            y_text += line_height

    def draw_wrapped_in_cell(draw, value, x, y, w, h, font, bold=False):
        text = _clean_pdf_text(value)
        avg_char_width = max(font.getlength('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz') / 52, 1)
        max_chars = max(int((w - 16) / avg_char_width), 8)
        lines = textwrap.wrap(text, width=max_chars) or ['']
        line_height = font.getbbox('Ag')[3] - font.getbbox('Ag')[1] + 3
        max_lines = max(int((h - 8) / line_height), 1)
        visible_lines = lines[:max_lines]
        if len(lines) > max_lines and visible_lines:
            visible_lines[-1] = f'{visible_lines[-1][: max(len(visible_lines[-1]) - 3, 1)]}...'
        text_h = line_height * len(visible_lines)
        y_text = y + max((h - text_h) // 2, 4)
        for line in visible_lines:
            draw.text((x + 8, y_text), line, font=font, fill=border)
            y_text += line_height

    def draw_activity_bar(draw, x, y, w, h):
        pad_x = max(int(w * 0.14), 6)
        bar_h = max(int(h * 0.36), 10)
        y0 = y + int((h - bar_h) / 2)
        draw.rounded_rectangle(
            (x + pad_x, y0, x + w - pad_x, y0 + bar_h),
            radius=3,
            fill=(105, 132, 128),
            outline=(70, 96, 92),
            width=1,
        )

    total_periodos = max(len(periodos), 1)
    service_w = 480 if total_periodos <= 12 else 430
    min_period_w = 45 if cronograma.formato == CronogramaObra.FORMATO_DIA else 62
    ideal_period_w = 88 if cronograma.formato == CronogramaObra.FORMATO_SEMANA else 72
    period_w = min(ideal_period_w, max(min_period_w, int((available_w - service_w) / total_periodos)))
    max_periodos_por_bloco = max(int((available_w - service_w) / period_w), 1)
    col_chunks = chunks(periodos, max_periodos_por_bloco)

    row_h = 50
    table_header_h = 72
    block_gap = 28
    max_rows_first_try = max(int((available_h - table_header_h) / row_h), 1)
    row_chunks = chunks(linhas, max_rows_first_try)

    blocks = []
    for row_chunk in row_chunks:
        for col_chunk in col_chunks:
            blocks.append((row_chunk, col_chunk))

    pages_blocks = []
    current_page = []
    used_h = 0
    for row_chunk, col_chunk in blocks:
        block_h = table_header_h + (max(len(row_chunk), 1) * row_h)
        if current_page and used_h + block_gap + block_h > available_h:
            pages_blocks.append(current_page)
            current_page = []
            used_h = 0
        current_page.append((row_chunk, col_chunk, block_h))
        used_h += block_h + (block_gap if used_h else 0)
    if current_page:
        pages_blocks.append(current_page)

    pages = []
    for page_index, page_blocks in enumerate(pages_blocks or [[(linhas, periodos, table_header_h + (max(len(linhas), 1) * row_h))]]):
        image = Image.new('RGB', (page_w, page_h), 'white')
        draw_header(image, page_index + 1, len(pages_blocks) or 1)
        draw = ImageDraw.Draw(image)
        y = header_h

        for row_chunk, col_chunk, block_h in page_blocks:
            x = margin
            dynamic_period_w = int((available_w - service_w) / max(len(col_chunk), 1))
            remainder = available_w - service_w - (dynamic_period_w * max(len(col_chunk), 1))
            period_widths = [
                dynamic_period_w + (1 if index < remainder else 0)
                for index in range(max(len(col_chunk), 1))
            ]
            draw.rectangle((x, y, x + service_w, y + table_header_h), fill=fill_header, outline=border, width=2)
            draw.text((x + (service_w - header_font.getlength('SERVICO')) / 2, y + 28), 'SERVICO', font=header_font, fill=border)
            cursor = x + service_w
            for grupo in split_grupos(col_chunk):
                width = sum(period_widths[: grupo['colspan']])
                draw.rectangle((cursor, y, cursor + width, y + 34), fill=fill_header, outline=border, width=2)
                draw.text((cursor + (width - header_font.getlength(grupo['label'])) / 2, y + 8), grupo['label'], font=header_font, fill=border)
                cursor += width
                period_widths = period_widths[grupo['colspan'] :]
            period_widths = [
                dynamic_period_w + (1 if index < remainder else 0)
                for index in range(max(len(col_chunk), 1))
            ]
            cursor = x + service_w
            for periodo, width in zip(col_chunk, period_widths):
                draw.rectangle((cursor, y + 34, cursor + width, y + table_header_h), outline=border, width=1)
                label_font = small_bold_font if cronograma.formato == CronogramaObra.FORMATO_SEMANA else header_font
                draw_centered_wrapped(draw, periodo['label'], cursor, y + 34, width, table_header_h - 34, label_font)
                cursor += width

            row_y = y + table_header_h
            for linha in row_chunk:
                is_geral = linha.tipo == LinhaCronogramaObra.TIPO_GERAL
                row_fill = fill_header if is_geral else 'white'
                font = header_font if is_geral else cell_font
                draw.rectangle((x, row_y, x + service_w, row_y + row_h), fill=row_fill, outline=border, width=1)
                draw_wrapped_in_cell(draw, linha.servico, x, row_y, service_w, row_h, font)
                cursor = x + service_w
                periodos_marcados = set(str(periodo) for periodo in linha.periodos)
                for periodo, width in zip(col_chunk, period_widths):
                    active = periodo['key'] in periodos_marcados
                    draw.rectangle(
                        (cursor, row_y, cursor + width, row_y + row_h),
                        fill=fill_header if is_geral else 'white',
                        outline=border,
                        width=1,
                    )
                    if active and not is_geral:
                        draw_activity_bar(draw, cursor, row_y, width, row_h)
                    cursor += width
                row_y += row_h
            table_right = x + service_w + sum(period_widths)
            draw.rectangle((x, y, table_right, row_y), outline=border, width=4)
            draw.line((x + service_w, y, x + service_w, row_y), fill=border, width=4)
            draw.line((x + service_w, y + 34, table_right, y + 34), fill=border, width=3)
            draw.line((x, y + table_header_h, table_right, y + table_header_h), fill=border, width=3)
            y = row_y + block_gap
        pages.append(image)

    buffer = BytesIO()
    pages[0].save(buffer, 'PDF', save_all=True, append_images=pages[1:], resolution=150)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="cronograma-{cronograma.id}.pdf"'
    return response


def lista_faturamentos_diretos(request):
    faturamentos = FaturamentoDireto.objects.select_related('obra').all()
    busca = request.GET.get('busca', '').strip()
    if busca:
        faturamentos = faturamentos.filter(
            Q(numero_nf__icontains=busca)
            | Q(numero_ordem_compra__icontains=busca)
            | Q(empresa_comprou__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(obra__nome_obra__icontains=busca)
            | Q(medicao_desconto__icontains=busca)
        )
    total = sum((faturamento.valor_nota for faturamento in faturamentos), Decimal('0'))
    return render(
        request,
        'controles/lista_faturamentos_diretos.html',
        {'faturamentos': faturamentos, 'busca': busca, 'total': total},
    )


def novo_faturamento_direto(request):
    if request.method == 'POST':
        form = FaturamentoDiretoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faturamento direto cadastrado com sucesso.')
            return redirect('lista_faturamentos_diretos')
    else:
        initial = {}
        obra_id = request.GET.get('obra')
        if obra_id:
            initial['obra'] = obra_id
        form = FaturamentoDiretoForm(initial=initial)

    return render(
        request,
        'controles/form_faturamento_direto.html',
        {'form': form, 'titulo': 'Novo Faturamento Direto'},
    )


def editar_faturamento_direto(request, faturamento_id):
    faturamento = get_object_or_404(FaturamentoDireto, id=faturamento_id)
    if request.method == 'POST':
        form = FaturamentoDiretoForm(request.POST, instance=faturamento)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faturamento direto atualizado com sucesso.')
            return redirect('lista_faturamentos_diretos')
    else:
        form = FaturamentoDiretoForm(instance=faturamento)

    return render(
        request,
        'controles/form_faturamento_direto.html',
        {'form': form, 'titulo': 'Editar Faturamento Direto', 'faturamento': faturamento},
    )


def excluir_faturamento_direto(request, faturamento_id):
    faturamento = get_object_or_404(FaturamentoDireto.objects.select_related('obra'), id=faturamento_id)

    if request.method == 'POST':
        documento = faturamento.numero_nf or faturamento.numero_ordem_compra or faturamento.descricao
        obra_id = faturamento.obra_id
        faturamento.delete()
        messages.success(request, f'Faturamento direto "{documento}" excluido com sucesso.')
        origem = request.GET.get('origem')
        if origem == 'obra':
            return redirect('detalhe_obra', obra_id=obra_id)
        return redirect('lista_faturamentos_diretos')

    origem = request.GET.get('origem')
    cancelar_href = reverse('detalhe_obra', args=[faturamento.obra_id]) if origem == 'obra' else reverse('lista_faturamentos_diretos')
    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir faturamento direto',
            'mensagem': f'Voce esta prestes a excluir o faturamento direto "{faturamento}".',
            'detalhe': 'O saldo contratual da obra sera recalculado automaticamente.',
            'confirmar_label': 'Excluir faturamento direto',
            'cancelar_href': cancelar_href,
        },
    )


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
    ordens = OrdemCompraGeral.objects.select_related('obra').prefetch_related('itens')
    status = request.GET.get('status', '').strip()
    obra_id = request.GET.get('obra', '').strip()
    busca = request.GET.get('busca', '').strip()

    if status in {choice[0] for choice in OrdemCompraGeral.STATUS_CHOICES}:
        ordens = ordens.filter(status=status)
    if obra_id.isdigit():
        ordens = ordens.filter(obra_id=obra_id)
    if busca:
        ordens = ordens.filter(
            Q(numero__icontains=busca)
            | Q(fornecedor__icontains=busca)
            | Q(comprador__icontains=busca)
            | Q(fornecedor_cpf_cnpj__icontains=busca)
            | Q(obra__nome_obra__icontains=busca)
        )
    ordens = list(ordens)
    total_filtrado = sum((ordem.total for ordem in ordens), Decimal('0'))
    total_por_obra = {}
    for ordem in ordens:
        obra_nome = ordem.obra.nome_obra if ordem.obra_id else 'Sem obra'
        if obra_nome not in total_por_obra:
            total_por_obra[obra_nome] = {'obra': obra_nome, 'quantidade': 0, 'total': Decimal('0')}
        total_por_obra[obra_nome]['quantidade'] += 1
        total_por_obra[obra_nome]['total'] += ordem.total

    return render(
        request,
        'controles/lista_ordens_compra_gerais.html',
        {
            'ordens': ordens,
            'obras': Obra.objects.order_by('nome_obra'),
            'status_choices': OrdemCompraGeral.STATUS_CHOICES,
            'filtros': {'status': status, 'obra': obra_id, 'busca': busca},
            'total_filtrado': total_filtrado,
            'total_por_obra': sorted(total_por_obra.values(), key=lambda item: item['obra']),
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
    headers = ['Item', 'Descricao', 'Qtd', 'Un', 'Vlr.', 'Total', 'Entrega']
    widths = [70, 420, 100, 70, 145, 160, 160]
    filename = f'OC {ordem.numero}'.replace('/', '-')

    def draw_first_page_base():
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
        return image, draw, x, y + 72, w

    def draw_summary_page():
        image = _report_background()
        draw = ImageDraw.Draw(image)
        x, y, w = _draw_report_heading(draw, 'Ordem de compra', ordem.numero, _format_date(ordem.data_emissao))
        y = _draw_section_title(draw, 'Fechamento', x, y, w)
        draw.rounded_rectangle((x + w - 390, y, x + w, y + 58), radius=6, fill=(4, 95, 101))
        draw.text((x + w - 360, y + 16), f'TOTAL: {_format_money(ordem.total)}', font=_font(22, True), fill=(255, 255, 255))
        y += 86
        y = _draw_notes_box(draw, 'Condicoes de pagamento', ordem.condicoes_pagamento or '-', x, y, w)
        y = _draw_notes_box(draw, 'Observacoes', ordem.observacoes or '-', x, y, w)
        draw.text((x, y + 20), _clean_pdf_text(f'Comprador: {ordem.comprador or "-"}'), font=_font(17), fill=(43, 48, 51))
        draw.text((x, y + 66), '________________________________________', font=_font(17), fill=(43, 48, 51))
        draw.text((x, y + 92), _clean_pdf_text(ordem.comprador or 'Assinatura'), font=_font(15), fill=(43, 48, 51))
        return image

    if len(rows) <= 4:
        image, draw, x, y, w = draw_first_page_base()
        y = _draw_section_title(draw, 'Itens', x, y, w)
        y = _draw_table(draw, headers, rows, x, y, widths)
        draw.rounded_rectangle((x + w - 360, y, x + w, y + 58), radius=6, fill=(4, 95, 101))
        draw.text((x + w - 332, y + 16), f'TOTAL: {_format_money(ordem.total)}', font=_font(22, True), fill=(255, 255, 255))
        y += 86
        y = _draw_notes_box(draw, 'Condicoes de pagamento', ordem.condicoes_pagamento or '-', x, y, w)
        y = _draw_notes_box(draw, 'Observacoes', ordem.observacoes or '-', x, y, w)
        draw.text((x, y + 20), _clean_pdf_text(f'Comprador: {ordem.comprador or "-"}'), font=_font(17), fill=(43, 48, 51))
        draw.text((x, y + 66), '________________________________________', font=_font(17), fill=(43, 48, 51))
        draw.text((x, y + 92), _clean_pdf_text(ordem.comprador or 'Assinatura'), font=_font(15), fill=(43, 48, 51))
        return _report_pdf_response(image, filename)

    pages = []
    first_capacity = 10
    next_capacity = 28
    chunks = [rows[:first_capacity]]
    remaining = rows[first_capacity:]
    while remaining:
        chunks.append(remaining[:next_capacity])
        remaining = remaining[next_capacity:]

    for index, chunk in enumerate(chunks):
        if index == 0:
            image, draw, x, y, w = draw_first_page_base()
        else:
            image = _report_background()
            draw = ImageDraw.Draw(image)
            x, y, w = _draw_report_heading(draw, 'Ordem de compra', ordem.numero, _format_date(ordem.data_emissao))
        y = _draw_section_title(draw, 'Itens' if index == 0 else 'Itens - continuacao', x, y, w)
        _draw_table(draw, headers, chunk, x, y, widths)
        footer = f'Pagina {index + 1}'
        draw.text((x + w - _font(14).getlength(footer), image.height - 130), footer, font=_font(14), fill=(92, 101, 105))
        pages.append(image)

    pages.append(draw_summary_page())
    return _report_pdf_response_pages(pages, filename)


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
