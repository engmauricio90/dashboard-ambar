from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from config.permissions import user_in_groups_for_empresa
from documentos.formatting import format_date_br, format_decimal_br
from documentos.pdf import PdfDocument, PdfTableColumn
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


def _pode_visualizar(request):
    return user_in_groups_for_empresa(request.user, GRUPOS_VISUALIZACAO, getattr(request, 'empresa', None))


def _pode_operar(request):
    return user_in_groups_for_empresa(request.user, GRUPOS_OPERACAO, getattr(request, 'empresa', None))


def _pode_admin(request):
    return user_in_groups_for_empresa(request.user, ('Diretoria',), getattr(request, 'empresa', None))


def _exigir_visualizacao(request):
    if not _pode_visualizar(request):
        messages.error(request, 'Voce nao tem permissao para acessar os diarios de obra.')
        return False
    return True


def _exigir_operacao(request):
    if not _pode_operar(request):
        messages.error(request, 'Voce nao tem permissao para alterar diarios de obra.')
        return False
    return True


def _base_queryset(empresa):
    return (
        DiarioObra.objects.select_related('obra', 'created_by', 'updated_by')
        .filter(obra__empresa=empresa)
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
    diarios = _base_queryset(request.empresa)
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
            'pode_operar': _pode_operar(request),
        },
    )


def lista_diarios_obra(request, obra_id):
    if not _exigir_visualizacao(request):
        return redirect('home')
    obra = get_object_or_404(Obra, id=obra_id, empresa=request.empresa)
    form, diarios = _filtros_diarios(request, obra=obra)
    return render(
        request,
        'diarios/list.html',
        {
            'form': form,
            'diarios': diarios[:200],
            'obra': obra,
            'pode_operar': _pode_operar(request),
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
    if diario and not diario.pode_editar and not _pode_admin(request):
        messages.error(request, 'Diario finalizado/revisado nao permite edicao direta. Reabra antes de editar.')
        return redirect('detalhe_diario', diario_id=diario.id)

    if request.method == 'POST':
        form = DiarioObraForm(
            request.POST,
            request.FILES,
            instance=diario,
            usuario=request.user,
            pode_alterar_status=_pode_admin(request),
            empresa=request.empresa,
        )
        formsets = _build_formsets(request.POST, request.FILES, instance=diario)
        formsets_validos = all(formset.is_valid() for formset in formsets.values())
        if form.is_valid() and formsets_validos:
            try:
                with transaction.atomic():
                    diario_salvo = form.save(commit=False)
                    if not diario_salvo.pk:
                        diario_salvo.created_by = request.user
                    diario_salvo.updated_by = request.user
                    if not _pode_admin(request) and diario:
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
        form = DiarioObraForm(
            instance=diario,
            initial=initial,
            usuario=request.user,
            pode_alterar_status=_pode_admin(request),
            empresa=request.empresa,
        )
        formsets = _build_formsets(instance=diario)

    titulo = 'Editar diario de obra' if diario else 'Novo diario de obra'
    return _render_form(request, form, formsets, titulo, diario=diario)


def novo_diario(request):
    return _salvar_diario(request)


def novo_diario_obra(request, obra_id):
    get_object_or_404(Obra, id=obra_id, empresa=request.empresa)
    return _salvar_diario(request, obra_id=obra_id)


def editar_diario(request, diario_id):
    diario = get_object_or_404(_base_queryset(request.empresa), id=diario_id)
    return _salvar_diario(request, diario=diario)


def detalhe_diario(request, diario_id):
    if not _exigir_visualizacao(request):
        return redirect('home')
    diario = get_object_or_404(_base_queryset(request.empresa), id=diario_id)
    return render(
        request,
        'diarios/detail.html',
        {
            'diario': diario,
            'pode_operar': _pode_operar(request),
            'pode_admin': _pode_admin(request),
        },
    )


@require_POST
def finalizar_diario(request, diario_id):
    if not _exigir_operacao(request):
        return redirect('lista_diarios')
    diario = get_object_or_404(DiarioObra, id=diario_id, obra__empresa=request.empresa)
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
    if not _pode_admin(request):
        messages.error(request, 'Apenas usuario autorizado pode reabrir diario.')
        return redirect('detalhe_diario', diario_id=diario_id)
    diario = get_object_or_404(DiarioObra, id=diario_id, obra__empresa=request.empresa)
    diario.status = DiarioObra.STATUS_RASCUNHO
    diario.updated_by = request.user
    diario.save(update_fields=['status', 'updated_by', 'updated_at'])
    _registrar_historico(diario, request.user, HistoricoDiario.ACAO_REABERTO)
    messages.success(request, 'Diario reaberto.')
    return redirect('detalhe_diario', diario_id=diario.id)


@require_POST
def cancelar_diario(request, diario_id):
    if not _pode_admin(request):
        messages.error(request, 'Apenas usuario autorizado pode cancelar diario.')
        return redirect('detalhe_diario', diario_id=diario_id)
    diario = get_object_or_404(DiarioObra, id=diario_id, obra__empresa=request.empresa)
    diario.status = DiarioObra.STATUS_CANCELADO
    diario.updated_by = request.user
    diario.save(update_fields=['status', 'updated_by', 'updated_at'])
    _registrar_historico(diario, request.user, HistoricoDiario.ACAO_CANCELADO)
    messages.success(request, 'Diario cancelado.')
    return redirect('detalhe_diario', diario_id=diario.id)


@require_POST
def excluir_diario(request, diario_id):
    diario = get_object_or_404(DiarioObra, id=diario_id, obra__empresa=request.empresa)
    if not (diario.status == DiarioObra.STATUS_RASCUNHO or _pode_admin(request)):
        messages.error(request, 'Somente diarios em rascunho podem ser excluidos.')
        return redirect('detalhe_diario', diario_id=diario.id)
    obra_id = diario.obra_id
    diario.delete()
    messages.success(request, 'Diario excluido.')
    return redirect('lista_diarios_obra', obra_id=obra_id)


def _rows_from(queryset, columns):
    rows = []
    for item in queryset:
        row = {}
        for key, getter in columns:
            row[key] = getter(item) if callable(getter) else getattr(item, getter, '')
        rows.append(row)
    return rows


def _add_table_if_any(pdf, title, columns, rows, row_height='auto'):
    if not rows:
        return
    pdf.add_section_header(title)
    pdf.add_table(columns, rows, row_height=row_height, header_fill=pdf.theme.header_fill)


def _pdf_diario(diario):
    empresa = diario.obra.empresa
    weekdays = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
    pdf = PdfDocument(
        empresa,
        title='Diário de Obra',
        subtitle=f'{diario.obra.nome_obra} | {format_date_br(diario.data)}',
        orientation='portrait',
        filename=f'diario_obra_{diario.id}.pdf',
    )
    pdf.add_title(emitted_on=diario.data)
    pdf.add_info_grid(
        [
            ('Obra', diario.obra.nome_obra),
            ('Cliente', diario.obra.cliente or '-'),
            ('Data', format_date_br(diario.data)),
            ('Dia da semana', weekdays[diario.data.weekday()]),
            ('Responsável', diario.responsavel_preenchimento),
            ('Responsável técnico', diario.responsavel_tecnico or '-'),
            ('Turno', diario.get_turno_display()),
            ('Status', diario.get_status_display()),
        ],
        columns=4,
    )
    pdf.add_section_header('Condições do dia')
    pdf.add_table(
        [
            PdfTableColumn('turno', 'Turno', weight=1),
            PdfTableColumn('clima', 'Tempo', weight=1.2),
            PdfTableColumn('situacao', 'Situação da obra', weight=1.5),
            PdfTableColumn('visita', 'Visita', weight=1.3),
        ],
        [
            {
                'turno': diario.get_turno_display(),
                'clima': diario.get_condicao_climatica_display() or '-',
                'situacao': diario.get_situacao_obra_display() or '-',
                'visita': diario.visitante_nome if diario.houve_visita else 'Não houve',
            }
        ],
        row_height=50,
    )
    pdf.add_section_header('Serviços executados')
    pdf.add_text_block('Descrição geral', diario.descricao_servicos or '-', min_height=118)
    if diario.observacoes:
        pdf.add_text_block('Observações', diario.observacoes, min_height=96)

    efetivo_rows = _rows_from(
        diario.efetivos.all(),
        [
            ('funcao', lambda i: i.get_funcao_display()),
            ('quantidade', lambda i: str(i.quantidade)),
            ('observacoes', 'observacoes'),
        ],
    )
    _add_table_if_any(
        pdf,
        'Efetivo',
        [
            PdfTableColumn('funcao', 'Função', weight=2),
            PdfTableColumn('quantidade', 'Quantidade', width=180, align='center'),
            PdfTableColumn('observacoes', 'Observações', weight=2),
        ],
        efetivo_rows,
    )

    equipamento_rows = _rows_from(
        diario.equipamentos.all(),
        [
            ('tipo', lambda i: i.get_tipo_display()),
            ('quantidade', lambda i: str(i.quantidade)),
            ('situacao', lambda i: i.get_situacao_display()),
            ('horas', lambda i: format_decimal_br(i.total_horas) if i.total_horas else '-'),
            ('observacoes', 'observacoes'),
        ],
    )
    _add_table_if_any(
        pdf,
        'Equipamentos',
        [
            PdfTableColumn('tipo', 'Tipo', weight=2),
            PdfTableColumn('quantidade', 'Qtd.', width=120, align='center'),
            PdfTableColumn('situacao', 'Situação', width=210, align='center'),
            PdfTableColumn('horas', 'Horas', width=130, align='right'),
            PdfTableColumn('observacoes', 'Observações', weight=2),
        ],
        equipamento_rows,
    )

    if diario.ocorrencias_interferencias:
        pdf.add_section_header('Ocorrências e interferências')
        pdf.add_text_block('Descrição', diario.ocorrencias_interferencias, min_height=110)

    ocorrencia_rows = _rows_from(
        diario.ocorrencias.all(),
        [
            ('tipo', lambda i: i.get_tipo_display()),
            ('descricao', 'descricao'),
            ('impacto_prazo', lambda i: i.get_impacto_prazo_display()),
            ('status', lambda i: i.get_status_display()),
        ],
    )
    _add_table_if_any(
        pdf,
        'Ocorrências registradas',
        [
            PdfTableColumn('tipo', 'Tipo', width=260),
            PdfTableColumn('descricao', 'Descrição', weight=3),
            PdfTableColumn('impacto_prazo', 'Impacto prazo', width=190, align='center'),
            PdfTableColumn('status', 'Status', width=170, align='center'),
        ],
        ocorrencia_rows,
    )

    for titulo, texto in [
        ('Pendências', diario.pendencias),
        ('Orientações', diario.orientacoes),
    ]:
        if texto:
            pdf.add_text_block(titulo, texto, min_height=96)

    checklist_rows = _rows_from(
        diario.checklist.all(),
        [
            ('item', lambda i: i.get_item_display()),
            ('resultado', lambda i: i.get_resultado_display()),
            ('observacoes', 'observacoes'),
        ],
    )
    _add_table_if_any(
        pdf,
        'Checklist',
        [
            PdfTableColumn('item', 'Item', weight=2),
            PdfTableColumn('resultado', 'Resultado', width=210, align='center'),
            PdfTableColumn('observacoes', 'Observações', weight=2),
        ],
        checklist_rows,
    )

    fotos = list(diario.fotos.all())
    if fotos:
        pdf.add_section_header('Registro fotográfico')
        pdf.add_photo_grid(
            [{'image': foto.imagem, 'caption': foto.legenda} for foto in fotos],
            columns=2,
            image_height=430,
            caption_height=70,
        )

    signatures = [diario.responsavel_preenchimento]
    if diario.responsavel_tecnico:
        signatures.append(diario.responsavel_tecnico)
    pdf.add_signature_block(signatures)
    return pdf.response()


def diario_pdf(request, diario_id):
    if not _exigir_visualizacao(request):
        return redirect('home')
    diario = get_object_or_404(_base_queryset(request.empresa), id=diario_id)
    return _pdf_diario(diario)
