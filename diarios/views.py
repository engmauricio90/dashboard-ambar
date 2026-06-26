from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image, ImageDraw

from config.permissions import user_in_groups
from controles.views import (
    _clean_pdf_text,
    _draw_wrapped,
    _font,
    _report_pdf_response_pages,
)
from obras.models import Obra

from .forms import (
    ChecklistDiarioFormSet,
    DiarioObraFiltroForm,
    DiarioObraForm,
    EfetivoDiarioFormSet,
    EquipamentoDiarioFormSet,
    FotoDiarioFormSet,
    OcorrenciaDiarioFormSet,
)
from .models import (
    ChecklistDiario,
    DiarioObra,
    FotoDiario,
    HistoricoDiario,
    OcorrenciaDiario,
)


GRUPOS_OPERACAO = ('Diretoria', 'Engenharia')
GRUPOS_VISUALIZACAO = ('Diretoria', 'Engenharia', 'Administrativo', 'Financeiro')


def _pode_visualizar(user):
    return user_in_groups(user, GRUPOS_VISUALIZACAO)


def _pode_operar(user):
    return user_in_groups(user, GRUPOS_OPERACAO)


def _pode_admin(user):
    return user.is_superuser or user_in_groups(user, ('Diretoria',))


def _exigir_visualizacao(request):
    if not _pode_visualizar(request.user):
        messages.error(request, 'Voce nao tem permissao para acessar os diarios de obra.')
        return False
    return True


def _exigir_operacao(request):
    if not _pode_operar(request.user):
        messages.error(request, 'Voce nao tem permissao para alterar diarios de obra.')
        return False
    return True


def _base_queryset():
    return (
        DiarioObra.objects.select_related('obra', 'created_by', 'updated_by')
        .prefetch_related(
            'efetivos',
            'equipamentos',
            'ocorrencias',
            'checklist',
            'fotos',
            'historico',
        )
        .annotate(
            qtd_efetivo=Count('efetivos', distinct=True),
            qtd_equipamentos=Count('equipamentos', distinct=True),
            qtd_fotos=Count('fotos', distinct=True),
            possui_ocorrencias_flag=Exists(
                OcorrenciaDiario.objects.filter(diario=OuterRef('pk')).exclude(status='cancelada')
            ),
            possui_fotos_flag=Exists(FotoDiario.objects.filter(diario=OuterRef('pk'))),
        )
    )


def _registrar_historico(diario, usuario, acao, descricao=''):
    HistoricoDiario.objects.create(diario=diario, usuario=usuario, acao=acao, descricao=descricao)


def _build_formsets(data=None, files=None, instance=None):
    kwargs = {'instance': instance}
    if data is not None:
        kwargs['data'] = data
        kwargs['files'] = files
    return {
        'efetivos': EfetivoDiarioFormSet(prefix='efetivos', **kwargs),
        'equipamentos': EquipamentoDiarioFormSet(prefix='equipamentos', **kwargs),
        'ocorrencias': OcorrenciaDiarioFormSet(prefix='ocorrencias', **kwargs),
        'checklist': ChecklistDiarioFormSet(prefix='checklist', **kwargs),
        'fotos': FotoDiarioFormSet(prefix='fotos', **kwargs),
    }


def _save_formset(formset, usuario=None, foto=False):
    instances = formset.save(commit=False)
    deleted_photos = []
    for obj in formset.deleted_objects:
        if foto:
            deleted_photos.append(obj)
        obj.delete()
    for instance in instances:
        if foto and not instance.uploaded_by_id:
            instance.uploaded_by = usuario
        instance.save()
    formset.save_m2m()
    return deleted_photos, instances


def _filtros_diarios(request, obra=None):
    form = DiarioObraFiltroForm(request.GET or None)
    diarios = _base_queryset()
    if obra:
        diarios = diarios.filter(obra=obra)
    if form.is_valid():
        dados = form.cleaned_data
        if dados.get('obra'):
            diarios = diarios.filter(obra__nome_obra__icontains=dados['obra'])
        if dados.get('data_inicial'):
            diarios = diarios.filter(data__gte=dados['data_inicial'])
        if dados.get('data_final'):
            diarios = diarios.filter(data__lte=dados['data_final'])
        if dados.get('status'):
            diarios = diarios.filter(status=dados['status'])
        if dados.get('responsavel'):
            diarios = diarios.filter(responsavel_preenchimento__icontains=dados['responsavel'])
        if dados.get('situacao_obra'):
            diarios = diarios.filter(situacao_obra=dados['situacao_obra'])
        if dados.get('possui_ocorrencias'):
            diarios = diarios.filter(possui_ocorrencias_flag=True)
        if dados.get('possui_fotos'):
            diarios = diarios.filter(possui_fotos_flag=True)
    return form, diarios


def lista_diarios(request):
    if not _exigir_visualizacao(request):
        return redirect('home')
    form, diarios = _filtros_diarios(request)
    return render(
        request,
        'diarios/list.html',
        {
            'form': form,
            'diarios': diarios[:200],
            'obra': None,
            'pode_operar': _pode_operar(request.user),
        },
    )


def lista_diarios_obra(request, obra_id):
    if not _exigir_visualizacao(request):
        return redirect('home')
    obra = get_object_or_404(Obra, id=obra_id)
    form, diarios = _filtros_diarios(request, obra=obra)
    return render(
        request,
        'diarios/list.html',
        {
            'form': form,
            'diarios': diarios[:200],
            'obra': obra,
            'pode_operar': _pode_operar(request.user),
        },
    )


def _render_form(request, form, formsets, titulo, diario=None):
    return render(
        request,
        'diarios/form.html',
        {
            'form': form,
            'formsets': formsets,
            'titulo': titulo,
            'diario': diario,
            'checklist_choices': ChecklistDiario.ITEM_CHOICES,
        },
    )


def _salvar_diario(request, diario=None, obra_id=None):
    if not _exigir_operacao(request):
        return redirect('lista_diarios')
    if diario and not diario.pode_editar and not _pode_admin(request.user):
        messages.error(request, 'Diario finalizado/revisado nao permite edicao direta. Reabra antes de editar.')
        return redirect('detalhe_diario', diario_id=diario.id)

    if request.method == 'POST':
        form = DiarioObraForm(request.POST, request.FILES, instance=diario, usuario=request.user, pode_alterar_status=_pode_admin(request.user))
        formsets = _build_formsets(request.POST, request.FILES, instance=diario)
        formsets_validos = all(formset.is_valid() for formset in formsets.values())
        if form.is_valid() and formsets_validos:
            try:
                with transaction.atomic():
                    diario_salvo = form.save(commit=False)
                    if not diario_salvo.pk:
                        diario_salvo.created_by = request.user
                    diario_salvo.updated_by = request.user
                    if not _pode_admin(request.user) and diario:
                        diario_salvo.status = diario.status
                    diario_salvo.save()
                    for nome, formset in formsets.items():
                        formset.instance = diario_salvo
                        fotos_removidas, fotos_adicionadas = _save_formset(
                            formset,
                            usuario=request.user,
                            foto=nome == 'fotos',
                        )
                        for _foto in fotos_adicionadas if nome == 'fotos' else []:
                            _registrar_historico(diario_salvo, request.user, HistoricoDiario.ACAO_FOTO_ADICIONADA)
                        for _foto in fotos_removidas:
                            _registrar_historico(diario_salvo, request.user, HistoricoDiario.ACAO_FOTO_REMOVIDA)
                    _registrar_historico(
                        diario_salvo,
                        request.user,
                        HistoricoDiario.ACAO_EDITADO if diario else HistoricoDiario.ACAO_CRIADO,
                    )
                messages.success(request, 'Diario de obra salvo com sucesso.')
                return redirect('detalhe_diario', diario_id=diario_salvo.id)
            except IntegrityError:
                form.add_error(None, 'Ja existe diario para esta obra nesta data.')
    else:
        initial = {}
        if not diario:
            if obra_id:
                initial['obra'] = obra_id
            if request.user.is_authenticated:
                initial['responsavel_preenchimento'] = request.user.get_full_name() or request.user.username
            initial['data'] = timezone.localdate()
        form = DiarioObraForm(instance=diario, initial=initial, usuario=request.user, pode_alterar_status=_pode_admin(request.user))
        formsets = _build_formsets(instance=diario)

    titulo = 'Editar diario de obra' if diario else 'Novo diario de obra'
    return _render_form(request, form, formsets, titulo, diario=diario)


def novo_diario(request):
    return _salvar_diario(request)


def novo_diario_obra(request, obra_id):
    get_object_or_404(Obra, id=obra_id)
    return _salvar_diario(request, obra_id=obra_id)


def editar_diario(request, diario_id):
    diario = get_object_or_404(_base_queryset(), id=diario_id)
    return _salvar_diario(request, diario=diario)


def detalhe_diario(request, diario_id):
    if not _exigir_visualizacao(request):
        return redirect('home')
    diario = get_object_or_404(_base_queryset(), id=diario_id)
    return render(
        request,
        'diarios/detail.html',
        {
            'diario': diario,
            'pode_operar': _pode_operar(request.user),
            'pode_admin': _pode_admin(request.user),
        },
    )


@require_POST
def finalizar_diario(request, diario_id):
    if not _exigir_operacao(request):
        return redirect('lista_diarios')
    diario = get_object_or_404(DiarioObra, id=diario_id)
    try:
        diario.validar_finalizacao()
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('detalhe_diario', diario_id=diario.id)
    diario.status = DiarioObra.STATUS_FINALIZADO
    diario.updated_by = request.user
    diario.save(update_fields=['status', 'updated_by', 'updated_at'])
    _registrar_historico(diario, request.user, HistoricoDiario.ACAO_FINALIZADO)
    messages.success(request, 'Diario finalizado com sucesso.')
    return redirect('detalhe_diario', diario_id=diario.id)


@require_POST
def reabrir_diario(request, diario_id):
    if not _pode_admin(request.user):
        messages.error(request, 'Apenas usuario autorizado pode reabrir diario.')
        return redirect('detalhe_diario', diario_id=diario_id)
    diario = get_object_or_404(DiarioObra, id=diario_id)
    diario.status = DiarioObra.STATUS_RASCUNHO
    diario.updated_by = request.user
    diario.save(update_fields=['status', 'updated_by', 'updated_at'])
    _registrar_historico(diario, request.user, HistoricoDiario.ACAO_REABERTO)
    messages.success(request, 'Diario reaberto.')
    return redirect('detalhe_diario', diario_id=diario.id)


@require_POST
def cancelar_diario(request, diario_id):
    if not _pode_admin(request.user):
        messages.error(request, 'Apenas usuario autorizado pode cancelar diario.')
        return redirect('detalhe_diario', diario_id=diario_id)
    diario = get_object_or_404(DiarioObra, id=diario_id)
    diario.status = DiarioObra.STATUS_CANCELADO
    diario.updated_by = request.user
    diario.save(update_fields=['status', 'updated_by', 'updated_at'])
    _registrar_historico(diario, request.user, HistoricoDiario.ACAO_CANCELADO)
    messages.success(request, 'Diario cancelado.')
    return redirect('detalhe_diario', diario_id=diario.id)


@require_POST
def excluir_diario(request, diario_id):
    diario = get_object_or_404(DiarioObra, id=diario_id)
    if not (diario.status == DiarioObra.STATUS_RASCUNHO or _pode_admin(request.user)):
        messages.error(request, 'Somente diarios em rascunho podem ser excluidos.')
        return redirect('detalhe_diario', diario_id=diario.id)
    obra_id = diario.obra_id
    diario.delete()
    messages.success(request, 'Diario excluido.')
    return redirect('lista_diarios_obra', obra_id=obra_id)


DIARIO_PAGE_W = 1653
DIARIO_PAGE_H = 2338
DIARIO_MARGIN = 110
DIARIO_CONTENT_W = DIARIO_PAGE_W - (DIARIO_MARGIN * 2)
DIARIO_FOOTER_Y = DIARIO_PAGE_H - 95


def _nova_pagina():
    image = Image.new('RGB', (DIARIO_PAGE_W, DIARIO_PAGE_H), 'white')
    draw = ImageDraw.Draw(image)
    return image, draw


def _garantir_espaco(pages, image, draw, y, needed=220):
    if y + needed < DIARIO_FOOTER_Y - 30:
        return image, draw, y
    pages.append(image)
    return (*_nova_pagina(), DIARIO_MARGIN)


def _diario_footer(draw, page_number, total_pages):
    muted = (78, 84, 88)
    line = (198, 204, 208)
    today = timezone.localtime().strftime('%d/%m/%Y - %H:%M')
    draw.line((DIARIO_MARGIN, DIARIO_FOOTER_Y - 20, DIARIO_PAGE_W - DIARIO_MARGIN, DIARIO_FOOTER_Y - 20), fill=line, width=1)
    draw.text((DIARIO_MARGIN, DIARIO_FOOTER_Y), today, font=_font(15), fill=muted)
    center = 'Ambar Engenharia'
    center_w = draw.textlength(center, font=_font(15, True))
    draw.text(((DIARIO_PAGE_W - center_w) / 2, DIARIO_FOOTER_Y), center, font=_font(15, True), fill=muted)
    page_text = f'{page_number} de {total_pages}'
    page_w = draw.textlength(page_text, font=_font(15))
    draw.text((DIARIO_PAGE_W - DIARIO_MARGIN - page_w, DIARIO_FOOTER_Y), page_text, font=_font(15), fill=muted)


def _diario_section(draw, title, x, y, w):
    dark = (27, 32, 35)
    border = (44, 49, 52)
    draw.rectangle((x, y, x + w, y + 42), outline=border, width=2)
    text_w = draw.textlength(_clean_pdf_text(title), font=_font(18, True))
    draw.text((x + (w - text_w) / 2, y + 10), _clean_pdf_text(title), font=_font(18, True), fill=dark)
    return y + 42


def _diario_info_grid(draw, rows, x, y, w, columns=2):
    border = (67, 72, 76)
    label_font = _font(15, True)
    value_font = _font(16)
    row_h = 64
    col_w = w / columns
    for index, (label, value) in enumerate(rows):
        col = index % columns
        row = index // columns
        x0 = int(x + col * col_w)
        y0 = int(y + row * row_h)
        x1 = int(x0 + col_w)
        y1 = y0 + row_h
        draw.rectangle((x0, y0, x1, y1), outline=border, width=1)
        draw.text((x0 + 12, y0 + 9), _clean_pdf_text(label), font=label_font, fill=(29, 34, 37))
        _draw_wrapped(draw, value or '-', (x0 + 12, y0 + 32), value_font, (45, 50, 53), int(col_w - 24), line_spacing=3)
    return y + (((len(rows) + columns - 1) // columns) * row_h)


def _diario_table(draw, headers, rows, x, y, widths, row_h=52):
    border = (67, 72, 76)
    header_fill = (238, 240, 241)
    header_font = _font(15, True)
    cell_font = _font(15)
    x_cursor = x
    for header, width in zip(headers, widths):
        draw.rectangle((x_cursor, y, x_cursor + width, y + row_h), fill=header_fill, outline=border, width=1)
        _draw_wrapped(draw, header, (x_cursor + 8, y + 14), header_font, (25, 30, 33), width - 16, line_spacing=2)
        x_cursor += width
    y += row_h
    for row in rows:
        x_cursor = x
        for value, width in zip(row, widths):
            draw.rectangle((x_cursor, y, x_cursor + width, y + row_h), outline=border, width=1)
            _draw_wrapped(draw, value, (x_cursor + 8, y + 13), cell_font, (39, 44, 47), width - 16, line_spacing=2)
            x_cursor += width
        y += row_h
    return y


def _diario_text_box(draw, text, x, y, w, min_h=96):
    border = (67, 72, 76)
    y_text_end = _draw_wrapped(draw, text or '-', (x + 12, y + 12), _font(16), (39, 44, 47), w - 24, line_spacing=6)
    box_h = max(min_h, y_text_end - y + 14)
    draw.rectangle((x, y, x + w, y + box_h), outline=border, width=1)
    return y + box_h


def _linhas_tabela(queryset, fields, empty='Sem registros.'):
    rows = []
    for item in queryset:
        rows.append([getter(item) if callable(getter) else getattr(item, getter, '') for getter in fields])
    return rows or [[empty]]


def _pdf_diario(diario):
    pages = []
    image, draw = _nova_pagina()
    x, y, w = DIARIO_MARGIN, DIARIO_MARGIN, DIARIO_CONTENT_W
    title_font = _font(30, True)
    subtitle_font = _font(18)
    dark = (24, 29, 32)
    border = (44, 49, 52)

    draw.rectangle((x, y, x + w, y + 92), outline=border, width=2)
    title = 'Diario de Obra'
    title_w = draw.textlength(title, font=title_font)
    draw.text((x + (w - title_w) / 2, y + 14), title, font=title_font, fill=dark)
    obra_text = _clean_pdf_text(diario.obra.nome_obra)
    obra_w = draw.textlength(obra_text, font=subtitle_font)
    draw.text((x + (w - obra_w) / 2, y + 55), obra_text, font=subtitle_font, fill=(70, 76, 80))
    y += 112

    weekdays = ['segunda-feira', 'terca-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sabado', 'domingo']
    y = _diario_info_grid(
        draw,
        [
            ('Obra', diario.obra.nome_obra),
            ('Cliente', diario.obra.cliente or '-'),
            ('Data', diario.data.strftime('%d/%m/%Y')),
            ('Dia da semana', weekdays[diario.data.weekday()]),
            ('Responsavel', diario.responsavel_preenchimento),
            ('Responsavel tecnico', diario.responsavel_tecnico or '-'),
        ],
        x,
        y,
        w,
        columns=2,
    )
    y += 26

    y = _diario_section(draw, 'Turno / Tempo', x, y, w)
    y = _diario_table(
        draw,
        ['Turno', 'Tempo', 'Situacao da obra', 'Status'],
        [[diario.get_turno_display(), diario.get_condicao_climatica_display() or '-', diario.get_situacao_obra_display() or '-', diario.get_status_display()]],
        x,
        y,
        [280, 360, 470, 323],
        row_h=58,
    )
    y += 24

    y = _diario_section(draw, 'Tarefas realizadas', x, y, w)
    y = _diario_table(
        draw,
        ['Descricao', 'Observacoes'],
        [[diario.descricao_servicos or '-', diario.observacoes or '-']],
        x,
        y,
        [930, 503],
        row_h=118,
    )
    y += 24

    efetivo_rows = _linhas_tabela(diario.efetivos.all(), [lambda i: i.get_funcao_display(), 'quantidade'])
    image, draw, y = _garantir_espaco(pages, image, draw, y, 120 + 52 * len(efetivo_rows))
    y = _diario_section(draw, 'Equipe envolvida', x, y, w)
    y = _diario_table(draw, ['Descricao', 'Qtde. utilizada'], efetivo_rows, x, y, [1080, 353])
    y += 24

    equipamento_rows = _linhas_tabela(
        diario.equipamentos.all(),
        [lambda i: i.get_tipo_display(), 'quantidade', lambda i: i.get_situacao_display()],
    )
    image, draw, y = _garantir_espaco(pages, image, draw, y, 120 + 52 * len(equipamento_rows))
    y = _diario_section(draw, 'Equipamentos', x, y, w)
    y = _diario_table(draw, ['Tipo', 'Qtde.', 'Situacao'], equipamento_rows, x, y, [840, 220, 373])
    y += 24

    ocorrencia_rows = _linhas_tabela(
        diario.ocorrencias.all(),
        [
            lambda i: i.get_tipo_display(),
            'descricao',
            lambda i: i.get_impacto_prazo_display(),
            lambda i: i.get_status_display(),
        ],
    )
    if ocorrencia_rows != [['Sem registros.']] or diario.ocorrencias_interferencias:
        image, draw, y = _garantir_espaco(pages, image, draw, y, 170 + 52 * len(ocorrencia_rows))
        y = _diario_section(draw, 'Ocorrencias', x, y, w)
        if diario.ocorrencias_interferencias:
            y = _diario_text_box(draw, diario.ocorrencias_interferencias, x, y, w, min_h=86)
        y = _diario_table(draw, ['Tipo', 'Descricao', 'Impacto prazo', 'Status'], ocorrencia_rows, x, y, [300, 703, 230, 200])
        y += 24

    for titulo, texto in [
        ('Pendencias', diario.pendencias),
        ('Orientacoes', diario.orientacoes),
    ]:
        if texto:
            image, draw, y = _garantir_espaco(pages, image, draw, y, 150)
            y = _diario_section(draw, titulo, x, y, w)
            y = _diario_text_box(draw, texto, x, y, w)
            y += 24

    checklist_rows = _linhas_tabela(
        diario.checklist.all(),
        [lambda i: i.get_item_display(), lambda i: i.get_resultado_display(), 'observacoes'],
    )
    if checklist_rows != [['Sem registros.']]:
        image, draw, y = _garantir_espaco(pages, image, draw, y, 120 + 52 * len(checklist_rows))
        y = _diario_section(draw, 'Checklist', x, y, w)
        y = _diario_table(draw, ['Item', 'Resultado', 'Observacoes'], checklist_rows, x, y, [720, 250, 463])
        y += 24

    fotos = list(diario.fotos.all())
    if fotos:
        image, draw, y = _garantir_espaco(pages, image, draw, y, 80)
        draw.text((x, y), 'Relatorio fotografico no Anexo I.', font=_font(16, True), fill=(39, 44, 47))
        y += 46

    pages.append(image)

    if fotos:
        image, draw = _nova_pagina()
        y = DIARIO_MARGIN
        title = 'Diario de Obra - Anexo I'
        draw.text((x, y), title, font=_font(28, True), fill=dark)
        draw.text((x, y + 40), _clean_pdf_text(diario.obra.nome_obra), font=_font(18), fill=(70, 76, 80))
        y += 95
        col_w = 690
        photo_h = 430
        gap_x = 50
        gap_y = 80
        for index, foto in enumerate(fotos):
            col = index % 2
            if col == 0 and index > 0:
                y += photo_h + gap_y
            if y + photo_h + 80 > DIARIO_FOOTER_Y:
                pages.append(image)
                image, draw = _nova_pagina()
                y = DIARIO_MARGIN
            fx = x + col * (col_w + gap_x)
            try:
                thumb = Image.open(foto.imagem.path).convert('RGB')
                thumb.thumbnail((col_w, photo_h))
                draw.rectangle((fx, y, fx + col_w, y + photo_h), outline=(112, 119, 124), width=1)
                image.paste(thumb, (fx + (col_w - thumb.width) // 2, y + (photo_h - thumb.height) // 2))
            except OSError:
                draw.rectangle((fx, y, fx + col_w, y + photo_h), outline=(112, 119, 124), width=1)
                draw.text((fx + 18, y + 190), 'Imagem indisponivel', font=_font(16), fill=(88, 98, 102))
            _draw_wrapped(draw, foto.legenda or '-', (fx, y + photo_h + 10), _font(14), (50, 56, 58), col_w, line_spacing=4)
        pages.append(image)

    for index, page in enumerate(pages, start=1):
        _diario_footer(ImageDraw.Draw(page), index, len(pages))

    return _report_pdf_response_pages(pages, f'diario_obra_{diario.id}')


def diario_pdf(request, diario_id):
    if not _exigir_visualizacao(request):
        return redirect('home')
    diario = get_object_or_404(_base_queryset(), id=diario_id)
    return _pdf_diario(diario)
