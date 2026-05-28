from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image, ImageDraw

from config.permissions import user_in_groups
from controles.views import (
    _clean_pdf_text,
    _draw_key_value_grid,
    _draw_section_title,
    _draw_table,
    _draw_wrapped,
    _font,
    _report_background,
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
    FrenteServicoFormSet,
    MaterialDiarioFormSet,
    OcorrenciaDiarioFormSet,
)
from .models import (
    ChecklistDiario,
    DiarioObra,
    FotoDiario,
    FrenteServicoDiario,
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
            'frentes',
            'efetivos',
            'equipamentos',
            'materiais',
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
        'frentes': FrenteServicoFormSet(prefix='frentes', **kwargs),
        'efetivos': EfetivoDiarioFormSet(prefix='efetivos', **kwargs),
        'equipamentos': EquipamentoDiarioFormSet(prefix='equipamentos', **kwargs),
        'materiais': MaterialDiarioFormSet(prefix='materiais', **kwargs),
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


def _validar_formsets_para_finalizacao(formsets):
    tem_frente = any(
        form.cleaned_data and not form.cleaned_data.get('DELETE') and form.cleaned_data.get('nome')
        for form in formsets['frentes'].forms
    )
    return tem_frente


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
    return render(request, 'diarios/list.html', {'form': form, 'diarios': diarios[:200], 'obra': None})


def lista_diarios_obra(request, obra_id):
    if not _exigir_visualizacao(request):
        return redirect('home')
    obra = get_object_or_404(Obra, id=obra_id)
    form, diarios = _filtros_diarios(request, obra=obra)
    return render(request, 'diarios/list.html', {'form': form, 'diarios': diarios[:200], 'obra': obra})


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
        if obra_id:
            initial['obra'] = obra_id
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
    diario = get_object_or_404(DiarioObra.objects.prefetch_related('frentes'), id=diario_id)
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


def _nova_pagina():
    image = _report_background()
    draw = ImageDraw.Draw(image)
    return image, draw


def _garantir_espaco(pages, image, draw, y, needed=220):
    if y + needed < 2160:
        return image, draw, y
    pages.append(image)
    return (*_nova_pagina(), 360)


def _linhas_tabela(queryset, fields, empty='Sem registros.'):
    rows = []
    for item in queryset:
        rows.append([getter(item) if callable(getter) else getattr(item, getter, '') for getter in fields])
    return rows or [[empty]]


def _pdf_diario(diario):
    pages = []
    image, draw = _nova_pagina()
    x, y, w = 220, 330, 1213

    draw.text((x, 160), 'DIARIO DE OBRA', font=_font(34, True), fill=(38, 48, 52))
    draw.text((x, 210), _clean_pdf_text(diario.obra.nome_obra), font=_font(22), fill=(80, 92, 98))
    draw.text((x + 980, 210), diario.data.strftime('%d/%m/%Y'), font=_font(20, True), fill=(80, 92, 98))

    y = _draw_key_value_grid(
        draw,
        [
            ('Obra', diario.obra.nome_obra),
            ('Cliente', diario.obra.cliente or '-'),
            ('Responsavel', diario.responsavel_preenchimento),
            ('Responsavel tecnico', diario.responsavel_tecnico or '-'),
            ('Clima', diario.get_condicao_climatica_display() or '-'),
            ('Situacao', diario.get_situacao_obra_display() or '-'),
            ('Turno', diario.get_turno_display()),
            ('Status', diario.get_status_display()),
        ],
        x,
        y,
        w,
        columns=2,
    )

    for titulo, texto in [
        ('Servicos executados', diario.descricao_servicos),
        ('Ocorrencias / interferencias', diario.ocorrencias_interferencias),
        ('Pendencias', diario.pendencias),
        ('Orientacoes', diario.orientacoes),
        ('Observacoes finais', diario.observacoes),
    ]:
        image, draw, y = _garantir_espaco(pages, image, draw, y, 190)
        y = _draw_section_title(draw, titulo, x, y, w)
        y = _draw_wrapped(draw, texto or '-', (x + 12, y), _font(16), (42, 48, 51), w - 24, line_spacing=6) + 24

    tabelas = [
        (
            'Frentes de servico',
            ['Frente', 'Local', '%', 'Situacao'],
            _linhas_tabela(
                diario.frentes.all(),
                ['nome', 'local_trecho', lambda i: i.percentual_executado or '-', lambda i: i.get_situacao_display()],
            ),
            [420, 330, 120, 343],
        ),
        (
            'Efetivo',
            ['Funcao', 'Equipe', 'Qtd', 'Horas'],
            _linhas_tabela(
                diario.efetivos.all(),
                [lambda i: i.get_funcao_display(), 'empresa_equipe', 'quantidade', 'total_horas'],
            ),
            [420, 360, 120, 313],
        ),
        (
            'Equipamentos',
            ['Tipo', 'Identificacao', 'Qtd', 'Situacao'],
            _linhas_tabela(
                diario.equipamentos.all(),
                [lambda i: i.get_tipo_display(), 'identificacao', 'quantidade', lambda i: i.get_situacao_display()],
            ),
            [420, 330, 120, 343],
        ),
        (
            'Materiais',
            ['Material', 'Qtd', 'Fornecedor', 'Movimento'],
            _linhas_tabela(
                diario.materiais.all(),
                ['material', lambda i: f'{i.quantidade} {i.unidade}', 'fornecedor', lambda i: i.get_movimento_display()],
            ),
            [420, 190, 360, 243],
        ),
        (
            'Ocorrencias',
            ['Tipo', 'Impacto prazo', 'Impacto financeiro', 'Status'],
            _linhas_tabela(
                diario.ocorrencias.all(),
                [lambda i: i.get_tipo_display(), lambda i: i.get_impacto_prazo_display(), lambda i: i.get_impacto_financeiro_display(), lambda i: i.get_status_display()],
            ),
            [420, 250, 270, 273],
        ),
        (
            'Checklist',
            ['Item', 'Resultado', 'Obs'],
            _linhas_tabela(
                diario.checklist.all(),
                [lambda i: i.get_item_display(), lambda i: i.get_resultado_display(), 'observacoes'],
            ),
            [600, 220, 393],
        ),
    ]
    for titulo, headers, rows, widths in tabelas:
        image, draw, y = _garantir_espaco(pages, image, draw, y, 120 + 46 * len(rows))
        y = _draw_section_title(draw, titulo, x, y, w)
        y = _draw_table(draw, headers, rows, x, y, widths)

    fotos = list(diario.fotos.all())
    if fotos:
        image, draw, y = _garantir_espaco(pages, image, draw, y, 380)
        y = _draw_section_title(draw, 'Fotos', x, y, w)
        col_w = 580
        for index, foto in enumerate(fotos):
            image, draw, y = _garantir_espaco(pages, image, draw, y, 360)
            col = index % 2
            if col == 0 and index > 0:
                y += 330
            fx = x + col * (col_w + 40)
            try:
                thumb = Image.open(foto.imagem.path).convert('RGB')
                thumb.thumbnail((col_w, 260))
                draw.rectangle((fx, y, fx + col_w, y + 260), outline=(205, 211, 214), width=1)
                image.paste(thumb, (fx + (col_w - thumb.width) // 2, y + 8))
            except OSError:
                draw.rectangle((fx, y, fx + col_w, y + 260), outline=(205, 211, 214), width=1)
                draw.text((fx + 16, y + 110), 'Imagem indisponivel', font=_font(16), fill=(88, 98, 102))
            _draw_wrapped(draw, foto.legenda or '-', (fx, y + 270), _font(14), (50, 56, 58), col_w, line_spacing=4)
        y += 360

    image, draw, y = _garantir_espaco(pages, image, draw, y, 220)
    y += 60
    draw.line((x, y, x + 470, y), fill=(44, 49, 52), width=2)
    draw.line((x + 700, y, x + 1170, y), fill=(44, 49, 52), width=2)
    draw.text((x + 95, y + 18), 'Responsavel tecnico', font=_font(15, True), fill=(44, 49, 52))
    draw.text((x + 810, y + 18), 'Cliente / Fiscal', font=_font(15, True), fill=(44, 49, 52))
    pages.append(image)
    return _report_pdf_response_pages(pages, f'diario_obra_{diario.id}')


def diario_pdf(request, diario_id):
    if not _exigir_visualizacao(request):
        return redirect('home')
    diario = get_object_or_404(_base_queryset(), id=diario_id)
    return _pdf_diario(diario)
