from decimal import Decimal
from datetime import date, timedelta
import calendar
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from documentos.formatting import format_date_br, format_money_br
from documentos.pdf import PdfDocument, PdfTableColumn
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


def _format_decimal4(value):
    return f'{value:.4f}'


def _format_money4(value):
    return f'R$ {value:.4f}'


def _format_decimal2(value):
    if value is None:
        return '-'
    return f'{value:.2f}'.replace('.', ',')


def _format_decimal4_br(value):
    if value is None:
        return '-'
    return f'{value:.4f}'.replace('.', ',')


def _queryset_locacoes_filtradas(request):
    locacoes = LocacaoEquipamento.objects.select_related('equipamento', 'locadora', 'obra').filter(
        obra__empresa=request.empresa,
    )

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


def _fornecedores_json(empresa):
    return [
        {
            'id': fornecedor.id,
            'nome': fornecedor.nome,
            'cpf_cnpj': fornecedor.cpf_cnpj,
            'ie_identidade': fornecedor.ie_identidade,
            'endereco': fornecedor.endereco,
            'bairro': fornecedor.bairro,
            'municipio': fornecedor.municipio,
            'cidade': fornecedor.cidade,
            'uf': fornecedor.uf,
            'cep': fornecedor.cep,
            'telefone': fornecedor.telefone,
        }
        for fornecedor in Fornecedor.objects.filter(empresa=empresa, ativo=True).order_by('nome')
    ]


def _add_month(value):
    year = value.year + (value.month // 12)
    month = (value.month % 12) + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


DIAS_SEMANA = [
    'segunda',
    'terça',
    'quarta',
    'quinta',
    'sexta',
    'sábado',
    'domingo',
]


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
                'dia_semana': DIAS_SEMANA[atual.weekday()],
                'is_weekend': atual.weekday() >= 5 if cronograma.formato == CronogramaObra.FORMATO_DIA else False,
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
        'veiculos': VeiculoMaquina.objects.filter(empresa=request.empresa).count(),
        'abastecimentos': RegistroAbastecimento.objects.filter(veiculo__empresa=request.empresa).count(),
        'ordens_compra_gerais': OrdemCompraGeral.objects.filter(empresa=request.empresa).count(),
        'ordens_compra_gerais_abertas': OrdemCompraGeral.objects.filter(empresa=request.empresa).exclude(
            status__in=['encerrada', 'cancelada'],
        ).count(),
        'ordens_combustivel': OrdemCompraCombustivel.objects.filter(empresa=request.empresa).count(),
        'ordens_combustivel_abertas': OrdemCompraCombustivel.objects.filter(empresa=request.empresa).exclude(
            status__in=['encerrada', 'cancelada'],
        ).count(),
        'bombonas_combustivel': BombonaCombustivel.objects.filter(empresa=request.empresa).count(),
        'locacoes_abertas': LocacaoEquipamento.objects.filter(
            obra__empresa=request.empresa,
            status__in=['locado', 'retirada_solicitada'],
        ).count(),
        'ordens_maquinas': OrdemServicoLocacaoMaquina.objects.filter(obra__empresa=request.empresa).count(),
        'ordens_maquinas_abertas': OrdemServicoLocacaoMaquina.objects.filter(obra__empresa=request.empresa).exclude(
            status__in=['encerrada', 'cancelada'],
        ).count(),
        'orcamentos_aguardando': OrcamentoRadarObra.objects.filter(empresa=request.empresa, situacao='aguardando_resposta').count(),
        'contratos_concretagem': ContratoConcretagem.objects.filter(obra__empresa=request.empresa, status='ativo').count(),
        'faturamentos_diretos': FaturamentoDireto.objects.filter(obra__empresa=request.empresa).count(),
        'cronogramas_obras': CronogramaObra.objects.filter(empresa=request.empresa).count(),
        'total_abastecido': sum(
            RegistroAbastecimento.objects.filter(veiculo__empresa=request.empresa).values_list('valor_total', flat=True),
            Decimal('0'),
        ),
    }
    return render(request, 'controles/home.html', totais)


def lista_cronogramas_obras(request):
    cronogramas = CronogramaObra.objects.select_related('obra').prefetch_related('linhas').filter(empresa=request.empresa)
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
        form = CronogramaObraForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            cronograma = form.save()
            messages.success(request, 'Cronograma criado. Agora adicione os servicos na grade.')
            return redirect('editar_cronograma_obra', cronograma_id=cronograma.id)
    else:
        form = CronogramaObraForm(empresa=request.empresa)
    return render(
        request,
        'controles/form_cronograma_obra.html',
        {'form': form, 'titulo': 'Novo cronograma de obra'},
    )


def editar_cronograma_obra(request, cronograma_id):
    cronograma = get_object_or_404(CronogramaObra.objects.select_related('obra'), id=cronograma_id, empresa=request.empresa)
    if request.method == 'POST':
        form = CronogramaObraForm(request.POST, instance=cronograma, empresa=request.empresa)
        if form.is_valid():
            with transaction.atomic():
                cronograma = form.save()
                total_linhas = int(request.POST.get('linhas-TOTAL_FORMS') or 0)
                for index in range(total_linhas):
                    linha_id = request.POST.get(f'linhas-{index}-id')
                    tipo = request.POST.get(f'linhas-{index}-tipo') or LinhaCronogramaObra.TIPO_SERVICO
                    servico = (request.POST.get(f'linhas-{index}-servico') or '').strip()
                    observacao_periodo = (request.POST.get(f'linhas-{index}-observacao_periodo') or '').strip()
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
                    linha.observacao_periodo = observacao_periodo
                    linha.save()
            messages.success(request, 'Cronograma salvo com sucesso.')
            return redirect('editar_cronograma_obra', cronograma_id=cronograma.id)
    else:
        form = CronogramaObraForm(instance=cronograma, empresa=request.empresa)
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
    cronograma = get_object_or_404(
        CronogramaObra.objects.select_related('obra').prefetch_related('linhas'),
        id=cronograma_id,
        empresa=request.empresa,
    )
    periodos = _periodos_cronograma(cronograma)
    linhas = list(cronograma.linhas.all())
    obra_nome = cronograma.obra.nome_obra if cronograma.obra else 'Sem obra vinculada'
    doc = PdfDocument(
        cronograma.empresa,
        title='Cronograma de atividades',
        subtitle=f'{cronograma.nome} - {obra_nome}',
        orientation='landscape',
        filename=f'cronograma-{cronograma.id}.pdf',
    )
    doc.add_title(emitted_on=date.today())
    doc.add_info_grid(
        [
            ('Obra', obra_nome),
            ('Formato', cronograma.get_formato_display()),
            ('Início', format_date_br(cronograma.data_inicio)),
            ('Término', format_date_br(cronograma.data_fim)),
        ],
        columns=4,
    )
    doc.add_timeline_grid(
        [
            {
                'key': periodo['key'],
                'label': (
                    f"{periodo['label']} {periodo['dia_semana']}"
                    if cronograma.formato == CronogramaObra.FORMATO_DIA
                    else periodo['label']
                ),
                'group': periodo['grupo'],
                'is_weekend': periodo.get('is_weekend', False),
            }
            for periodo in periodos
        ],
        [
            {
                'label': linha.servico,
                'active_keys': set(str(periodo) for periodo in linha.periodos),
                'is_group': linha.tipo == LinhaCronogramaObra.TIPO_GERAL,
                'note': linha.observacao_periodo,
            }
            for linha in linhas
        ],
        service_label='Serviço',
        service_width=520 if len(periodos) <= 12 else 460,
        min_period_width=64 if cronograma.formato == CronogramaObra.FORMATO_DIA else 96,
        ideal_period_width=112 if cronograma.formato == CronogramaObra.FORMATO_SEMANA else 84,
    )
    return doc.response()


def lista_faturamentos_diretos(request):
    faturamentos = FaturamentoDireto.objects.select_related('obra').filter(obra__empresa=request.empresa)
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
        form = FaturamentoDiretoForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faturamento direto cadastrado com sucesso.')
            return redirect('lista_faturamentos_diretos')
    else:
        initial = {}
        obra_id = request.GET.get('obra')
        if obra_id:
            initial['obra'] = obra_id
        form = FaturamentoDiretoForm(initial=initial, empresa=request.empresa)

    return render(
        request,
        'controles/form_faturamento_direto.html',
        {'form': form, 'titulo': 'Novo Faturamento Direto'},
    )


def editar_faturamento_direto(request, faturamento_id):
    faturamento = get_object_or_404(FaturamentoDireto, id=faturamento_id, obra__empresa=request.empresa)
    if request.method == 'POST':
        form = FaturamentoDiretoForm(request.POST, instance=faturamento, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faturamento direto atualizado com sucesso.')
            return redirect('lista_faturamentos_diretos')
    else:
        form = FaturamentoDiretoForm(instance=faturamento, empresa=request.empresa)

    return render(
        request,
        'controles/form_faturamento_direto.html',
        {'form': form, 'titulo': 'Editar Faturamento Direto', 'faturamento': faturamento},
    )


def excluir_faturamento_direto(request, faturamento_id):
    faturamento = get_object_or_404(
        FaturamentoDireto.objects.select_related('obra'),
        id=faturamento_id,
        obra__empresa=request.empresa,
    )

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
    abastecimentos = RegistroAbastecimento.objects.select_related('veiculo').filter(veiculo__empresa=request.empresa)
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
        form = RegistroAbastecimentoForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Abastecimento registrado com sucesso.')
            return redirect('lista_abastecimentos')
    else:
        form = RegistroAbastecimentoForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_abastecimento.html',
        {'form': form, 'titulo': 'Novo Abastecimento'},
    )


def lista_ordens_compra_gerais(request):
    ordens = OrdemCompraGeral.objects.filter(empresa=request.empresa).select_related('obra').prefetch_related('itens')
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
    ordens_filtradas = list(ordens)
    total_filtrado = sum((ordem.total for ordem in ordens_filtradas), Decimal('0'))
    total_por_obra = {}
    for ordem in ordens_filtradas:
        obra_nome = ordem.obra.nome_obra if ordem.obra_id else 'Sem obra'
        if obra_nome not in total_por_obra:
            total_por_obra[obra_nome] = {'obra': obra_nome, 'quantidade': 0, 'total': Decimal('0')}
        total_por_obra[obra_nome]['quantidade'] += 1
        total_por_obra[obra_nome]['total'] += ordem.total
    paginator = Paginator(ordens_filtradas, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    return render(
        request,
        'controles/lista_ordens_compra_gerais.html',
        {
            'ordens': page_obj,
            'page_obj': page_obj,
            'query_string': query_string,
            'obras': Obra.objects.filter(empresa=request.empresa).order_by('nome_obra'),
            'status_choices': OrdemCompraGeral.STATUS_CHOICES,
            'filtros': {'status': status, 'obra': obra_id, 'busca': busca},
            'total_filtrado': total_filtrado,
            'total_por_obra': sorted(total_por_obra.values(), key=lambda item: item['obra']),
        },
    )


def _salvar_ordem_compra_geral(request, ordem=None):
    if request.method == 'POST':
        form = OrdemCompraGeralForm(request.POST, instance=ordem, empresa=request.empresa)
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
        form = OrdemCompraGeralForm(instance=ordem, empresa=request.empresa)
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
            'fornecedores_json': _fornecedores_json(request.empresa),
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
        empresa=request.empresa,
    )
    return render(request, 'controles/detalhe_ordem_compra_geral.html', {'ordem': ordem})


def editar_ordem_compra_geral(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraGeral, id=ordem_id, empresa=request.empresa)
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
            'fornecedores_json': _fornecedores_json(request.empresa),
        },
    )


def excluir_ordem_compra_geral(request, ordem_id):
    ordem = get_object_or_404(
        OrdemCompraGeral.objects.prefetch_related('itens', 'notas_fiscais').select_related('obra'),
        id=ordem_id,
        empresa=request.empresa,
    )

    if request.method == 'POST':
        from financeiro.models import ItemContaPagarOrdemCompra

        numero = ordem.numero
        with transaction.atomic():
            ItemContaPagarOrdemCompra.objects.filter(item_ordem_compra__ordem=ordem).delete()
            ContaPagar.objects.filter(ordem_compra=ordem, empresa=request.empresa).update(
                ordem_compra=None,
                item_ordem_compra=None,
                quantidade_oc=Decimal('0'),
                valor_unitario_oc=Decimal('0'),
            )
            ordem.notas_fiscais.all().delete()
            ordem.delete()
        messages.success(request, f'OC "{numero}" excluida com sucesso. Contas a pagar vinculadas foram preservadas.')
        return redirect('lista_ordens_compra_gerais')

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir ordem de compra',
            'mensagem': f'Voce esta prestes a excluir a OC "{ordem.numero}".',
            'detalhe': (
                'Itens e notas vinculadas a esta OC serao excluidos. Contas a pagar ja lancadas no financeiro '
                'serao preservadas, mas ficarao sem vinculo com esta OC.'
            ),
            'confirmar_label': 'Excluir OC',
            'cancelar_href': reverse('detalhe_ordem_compra_geral', args=[ordem.id]),
        },
    )


def nova_nf_ordem_compra_geral(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraGeral, id=ordem_id, empresa=request.empresa)
    messages.info(request, 'Lance a conta a pagar no financeiro e selecione a OC para vincular a NF automaticamente.')
    return redirect(f'{reverse("nova_conta_pagar")}?ordem_compra={ordem.id}')


def editar_nf_ordem_compra_geral(request, nota_id):
    nota = get_object_or_404(
        NotaFiscalOrdemCompraGeral.objects.select_related('ordem'),
        id=nota_id,
        ordem__empresa=request.empresa,
    )
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
        ordem__empresa=request.empresa,
    )
    if nota.conta_pagar_id:
        messages.info(request, 'Esta NF ja possui conta a pagar vinculada.')
        return redirect('detalhe_ordem_compra_geral', ordem_id=nota.ordem_id)

    from financeiro.models import ItemContaPagarOrdemCompra

    conta = ContaPagar.objects.create(
        empresa=nota.ordem.empresa,
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
    ordem = get_object_or_404(
        OrdemCompraGeral.objects.select_related('obra', 'centro_custo').prefetch_related('itens'),
        id=ordem_id,
        empresa=request.empresa,
    )
    rows = [
        {
            'item': f'{item.item:02d}',
            'descricao': item.descricao,
            'quantidade': _format_decimal4_br(item.quantidade),
            'unidade': item.unidade,
            'valor_unitario': format_money_br(item.valor_unitario),
            'valor_total': format_money_br(item.valor_total),
            'entrega': format_date_br(item.data_entrega),
        }
        for item in ordem.itens.all()
    ]
    filename = f'OC {ordem.numero}'.replace('/', '-')
    pdf = PdfDocument(
        ordem.empresa,
        title='Ordem de compra',
        subtitle=f'Número {ordem.numero}',
        orientation='portrait',
        filename=f'{filename}.pdf',
    )
    pdf.add_title(emitted_on=ordem.data_emissao)
    pdf.add_info_grid(
        [
            ('Número', ordem.numero),
            ('Data', format_date_br(ordem.data_emissao)),
            ('Status', ordem.get_status_display()),
            ('Comprador', ordem.comprador or '-'),
            ('Obra', ordem.obra or '-'),
            ('Centro de custo', ordem.centro_custo or '-'),
            ('Categoria', ordem.categoria_despesa or '-'),
            ('Total', format_money_br(ordem.total)),
        ],
        columns=4,
    )
    pdf.add_section_header('Empresa compradora')
    pdf.add_info_grid(
        [
            ('Razão social', ordem.empresa_razao_social),
            ('CNPJ', ordem.empresa_cnpj or '-'),
            ('Endereço', ordem.empresa_endereco or '-'),
            ('Comprador', ordem.comprador or '-'),
        ],
        columns=2,
    )
    pdf.add_section_header('Fornecedor')
    pdf.add_info_grid(
        [
            ('Fornecedor', ordem.fornecedor),
            ('CPF/CNPJ', ordem.fornecedor_cpf_cnpj or '-'),
            ('Endereço', ordem.fornecedor_endereco or '-'),
            ('Bairro', ordem.fornecedor_bairro or '-'),
            ('Cidade/UF', f'{ordem.fornecedor_cidade or "-"} / {ordem.fornecedor_uf or "-"}'),
            ('CEP', ordem.fornecedor_cep or '-'),
            ('Fone', ordem.fornecedor_fone or '-'),
            ('IE', ordem.fornecedor_ie or '-'),
        ],
        columns=2,
    )
    pdf.add_text_block(
        'Aviso fiscal',
        'Nas notas fiscais e faturas e obrigatorio aparecer o numero desta ordem de compra.',
        min_height=70,
    )
    pdf.add_section_header('Itens')
    pdf.add_table(
        [
            PdfTableColumn('item', 'Item', width=78, align='center'),
            PdfTableColumn('descricao', 'Descrição', weight=3.6),
            PdfTableColumn('quantidade', 'Qtd', width=124, align='center'),
            PdfTableColumn('unidade', 'Un', width=72, align='center'),
            PdfTableColumn('valor_unitario', 'Vlr. unit.', width=150, align='right'),
            PdfTableColumn('valor_total', 'Total', width=160, align='right'),
            PdfTableColumn('entrega', 'Entrega', width=126, align='center'),
        ],
        rows,
        row_height='auto',
    )
    pdf.add_totals_box([('Total da ordem', format_money_br(ordem.total), True)], width=560)
    pdf.add_text_block('Condições de pagamento', ordem.condicoes_pagamento or '-', min_height=84)
    pdf.add_text_block('Observações', ordem.observacoes or '-', min_height=84)
    pdf.add_signature_block([ordem.comprador or 'Comprador'])
    return pdf.response()


def lista_ordens_combustivel(request):
    ordens = OrdemCompraCombustivel.objects.filter(empresa=request.empresa).select_related('veiculo', 'bombona').prefetch_related('notas_fiscais')

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
        form = OrdemCompraCombustivelForm(request.POST, empresa=request.empresa)
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
        form = OrdemCompraCombustivelForm(empresa=request.empresa)

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
        empresa=request.empresa,
    )
    return render(request, 'controles/detalhe_ordem_combustivel.html', {'ordem': ordem})


def ordem_combustivel_pdf(request, ordem_id):
    ordem = get_object_or_404(
        OrdemCompraCombustivel.objects.select_related('veiculo', 'bombona'),
        id=ordem_id,
        empresa=request.empresa,
    )
    pdf = PdfDocument(
        ordem.empresa,
        title='Ordem de compra de combustível',
        subtitle=f'Número {ordem.numero}',
        orientation='portrait',
        filename=f'{ordem.numero}.pdf',
    )
    pdf.add_title(emitted_on=ordem.data_ordem)
    pdf.add_info_grid(
        [
            ('Número', ordem.numero),
            ('Data', format_date_br(ordem.data_ordem)),
            ('Fornecedor/Posto', ordem.fornecedor),
            ('Solicitante', ordem.solicitante or '-'),
            ('Status', ordem.get_status_display()),
            ('Tipo destino', ordem.get_tipo_destino_display()),
            ('Destino', ordem.destino_display),
            ('Combustível', ordem.get_tipo_combustivel_display()),
            ('Total previsto', format_money_br(ordem.valor_total_previsto)),
        ],
        columns=4,
    )
    pdf.add_section_header('Item autorizado')
    pdf.add_table(
        [
            PdfTableColumn('descricao', 'Descrição', weight=3),
            PdfTableColumn('quantidade', 'Quantidade', width=210, align='center'),
            PdfTableColumn('valor_unitario', 'Valor unitário', width=230, align='right'),
            PdfTableColumn('total', 'Total previsto', width=250, align='right'),
        ],
        [
            {
                'descricao': f'Combustível - {ordem.get_tipo_combustivel_display()}',
                'quantidade': f'{_format_decimal2(ordem.quantidade_litros)} L',
                'valor_unitario': format_money_br(ordem.valor_litro_previsto),
                'total': format_money_br(ordem.valor_total_previsto),
            }
        ],
        row_height=52,
    )
    pdf.add_text_block('Observações', ordem.observacoes or '-', min_height=92)
    pdf.add_signature_block([ordem.solicitante or 'Solicitante', 'Aprovação'])
    return pdf.response()


def editar_ordem_combustivel(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraCombustivel, id=ordem_id, empresa=request.empresa)
    status_anterior = ordem.status

    if request.method == 'POST':
        form = OrdemCompraCombustivelForm(request.POST, instance=ordem, empresa=request.empresa)
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
        form = OrdemCompraCombustivelForm(instance=ordem, empresa=request.empresa)

    return render(
        request,
        'controles/form_ordem_combustivel.html',
        {'form': form, 'titulo': 'Editar Ordem de Combustivel', 'ordem': ordem},
    )


def nova_nf_combustivel(request, ordem_id):
    ordem = get_object_or_404(OrdemCompraCombustivel, id=ordem_id, empresa=request.empresa)

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
    nota = get_object_or_404(
        NotaFiscalCombustivel.objects.select_related('ordem'),
        id=nota_id,
        ordem__empresa=request.empresa,
    )
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
    bombonas = BombonaCombustivel.objects.filter(empresa=request.empresa)
    return render(request, 'controles/lista_bombonas_combustivel.html', {'bombonas': bombonas})


def nova_bombona_combustivel(request):
    if request.method == 'POST':
        form = BombonaCombustivelForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bombona cadastrada com sucesso.')
            return redirect('lista_bombonas_combustivel')
    else:
        form = BombonaCombustivelForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_bombona_combustivel.html',
        {'form': form, 'titulo': 'Nova Bombona'},
    )


def editar_bombona_combustivel(request, bombona_id):
    bombona = get_object_or_404(BombonaCombustivel, id=bombona_id, empresa=request.empresa)

    if request.method == 'POST':
        form = BombonaCombustivelForm(request.POST, instance=bombona, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bombona atualizada com sucesso.')
            return redirect('lista_bombonas_combustivel')
    else:
        form = BombonaCombustivelForm(instance=bombona, empresa=request.empresa)

    return render(
        request,
        'controles/form_bombona_combustivel.html',
        {'form': form, 'titulo': 'Editar Bombona', 'bombona': bombona},
    )


def lista_veiculos(request):
    veiculos = VeiculoMaquina.objects.filter(empresa=request.empresa)
    return render(request, 'controles/lista_veiculos.html', {'veiculos': veiculos})


def novo_veiculo(request):
    if request.method == 'POST':
        form = VeiculoMaquinaForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Veiculo/maquina cadastrado com sucesso.')
            return redirect('lista_veiculos')
    else:
        form = VeiculoMaquinaForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_veiculo.html',
        {'form': form, 'titulo': 'Novo Veiculo/Maquina'},
    )


def editar_veiculo(request, veiculo_id):
    veiculo = get_object_or_404(VeiculoMaquina, id=veiculo_id, empresa=request.empresa)

    if request.method == 'POST':
        form = VeiculoMaquinaForm(request.POST, instance=veiculo, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Veiculo/maquina atualizado com sucesso.')
            return redirect('lista_veiculos')
    else:
        form = VeiculoMaquinaForm(instance=veiculo, empresa=request.empresa)

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
    ).filter(obra__empresa=request.empresa).prefetch_related('apontamentos', 'notas_fiscais')

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
            'obras_filtro': OrdemServicoLocacaoMaquina.objects.filter(obra__empresa=request.empresa).select_related('obra').values_list(
                'obra_id',
                'obra__nome_obra',
            ).distinct().order_by('obra__nome_obra'),
            'fornecedores_filtro': FornecedorMaquinaLocacao.objects.filter(
                empresa=request.empresa,
                ordens__isnull=False,
            ).distinct().order_by('nome'),
        },
    )


def nova_ordem_locacao_maquina(request):
    if request.method == 'POST':
        form = OrdemServicoLocacaoMaquinaForm(request.POST, empresa=request.empresa)
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
        form = OrdemServicoLocacaoMaquinaForm(empresa=request.empresa)

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
        obra__empresa=request.empresa,
    )
    return render(request, 'controles/detalhe_ordem_locacao_maquina.html', {'ordem': ordem})


def ordem_locacao_maquina_pdf(request, ordem_id):
    ordem = get_object_or_404(
        OrdemServicoLocacaoMaquina.objects.select_related('obra', 'fornecedor', 'maquina'),
        id=ordem_id,
        obra__empresa=request.empresa,
    )
    empresa = ordem.obra.empresa
    pdf = PdfDocument(
        empresa,
        title='Ordem de serviço de locação de máquina',
        subtitle=f'Número {ordem.numero}',
        orientation='portrait',
        filename=f'{ordem.numero}.pdf',
    )
    periodo_previsto = '-'
    if ordem.data_prevista_inicio or ordem.data_prevista_fim:
        periodo_previsto = f'{format_date_br(ordem.data_prevista_inicio)} a {format_date_br(ordem.data_prevista_fim)}'
    pdf.add_title(emitted_on=ordem.data_solicitacao)
    pdf.add_info_grid(
        [
            ('Número', ordem.numero),
            ('Data', format_date_br(ordem.data_solicitacao)),
            ('Obra', ordem.obra),
            ('Fornecedor', ordem.fornecedor),
            ('Máquina', ordem.maquina),
            ('Status', ordem.get_status_display()),
            ('Solicitante', ordem.solicitante or '-'),
            ('Responsavel', ordem.responsavel or '-'),
            ('Tipo de cobrança', ordem.get_tipo_cobranca_display()),
            ('Operador incluso', 'Sim' if ordem.operador_incluso else 'Não'),
            ('Combustível incluso', 'Sim' if ordem.combustivel_incluso else 'Não'),
            ('Valor previsto', format_money_br(ordem.valor_previsto_total)),
        ],
        columns=4,
    )
    pdf.add_section_header('Prazos e operação')
    pdf.add_table(
        [
            PdfTableColumn('periodo', 'Período previsto', weight=2),
            PdfTableColumn('mobilizacao', 'Mobilização', width=230, align='center'),
            PdfTableColumn('inicio', 'Início operação', width=230, align='center'),
            PdfTableColumn('desmobilizacao', 'Desmobilização', width=230, align='center'),
        ],
        [
            {
                'periodo': periodo_previsto,
                'mobilizacao': format_date_br(ordem.data_mobilizacao),
                'inicio': format_date_br(ordem.data_inicio_operacao),
                'desmobilizacao': format_date_br(ordem.data_desmobilizacao),
            }
        ],
        row_height=52,
    )
    pdf.add_section_header('Valores contratados')
    pdf.add_table(
        [
            PdfTableColumn('item_a', 'Item', weight=1.4),
            PdfTableColumn('valor_a', 'Valor/Info', width=250, align='right'),
            PdfTableColumn('item_b', 'Item', weight=1.4),
            PdfTableColumn('valor_b', 'Valor/Info', width=250, align='right'),
        ],
        [
            {'item_a': 'Valor hora', 'valor_a': format_money_br(ordem.valor_hora), 'item_b': 'Valor diaria', 'valor_b': format_money_br(ordem.valor_diaria)},
            {'item_a': 'Valor mensal', 'valor_a': format_money_br(ordem.valor_mensal), 'item_b': 'Franquia horas', 'valor_b': _format_decimal2(ordem.franquia_horas)},
            {
                'item_a': 'Mobilização',
                'valor_a': format_money_br(ordem.valor_mobilizacao),
                'item_b': 'Desmobilização',
                'valor_b': format_money_br(ordem.valor_desmobilizacao),
            },
            {
                'item_a': 'Valor previsto manual',
                'valor_a': format_money_br(ordem.valor_previsto_manual) if ordem.valor_previsto_manual is not None else '-',
                'item_b': 'Tipo cobrança',
                'valor_b': ordem.get_tipo_cobranca_display(),
            },
        ],
        row_height=46,
    )
    pdf.add_totals_box([('Valor previsto total', format_money_br(ordem.valor_previsto_total), True)], width=620)
    pdf.add_text_block('Observações', ordem.observacoes or '-', min_height=92)
    pdf.add_signature_block([ordem.solicitante or 'Solicitante', ordem.responsavel or 'Responsável'])
    return pdf.response()


def editar_ordem_locacao_maquina(request, ordem_id):
    ordem = get_object_or_404(OrdemServicoLocacaoMaquina, id=ordem_id, obra__empresa=request.empresa)
    status_anterior = ordem.status

    if request.method == 'POST':
        form = OrdemServicoLocacaoMaquinaForm(request.POST, instance=ordem, empresa=request.empresa)
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
        form = OrdemServicoLocacaoMaquinaForm(instance=ordem, empresa=request.empresa)

    return render(
        request,
        'controles/form_ordem_locacao_maquina.html',
        {'form': form, 'titulo': 'Editar OS de Locacao de Maquina', 'ordem': ordem},
    )


def excluir_ordem_locacao_maquina(request, ordem_id):
    ordem = get_object_or_404(
        OrdemServicoLocacaoMaquina.objects.select_related('obra', 'fornecedor', 'maquina'),
        id=ordem_id,
        obra__empresa=request.empresa,
    )

    if request.method == 'POST':
        numero = ordem.numero
        ordem.delete()
        messages.success(request, f'OS de locacao de maquina "{numero}" excluida com sucesso.')
        return redirect('lista_ordens_locacao_maquinas')

    return render(
        request,
        'obras/confirmar_exclusao.html',
        {
            'titulo': 'Excluir OS de locacao de maquina',
            'mensagem': f'Voce esta prestes a excluir a OS "{ordem.numero}".',
            'detalhe': (
                'Os apontamentos, notas fiscais e historico vinculados a esta OS tambem serao excluidos. '
                'Essa acao nao altera o cadastro da obra, maquina ou fornecedor.'
            ),
            'confirmar_label': 'Excluir OS',
            'cancelar_href': reverse('detalhe_ordem_locacao_maquina', args=[ordem.id]),
        },
    )


def novo_apontamento_maquina(request, ordem_id):
    ordem = get_object_or_404(OrdemServicoLocacaoMaquina, id=ordem_id, obra__empresa=request.empresa)

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
        ordem__obra__empresa=request.empresa,
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
    ordem = get_object_or_404(OrdemServicoLocacaoMaquina, id=ordem_id, obra__empresa=request.empresa)

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
    nota = get_object_or_404(
        NotaFiscalLocacaoMaquina.objects.select_related('ordem'),
        id=nota_id,
        ordem__obra__empresa=request.empresa,
    )
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
    fornecedores = FornecedorMaquinaLocacao.objects.filter(empresa=request.empresa)
    return render(request, 'controles/lista_fornecedores_maquinas.html', {'fornecedores': fornecedores})


def novo_fornecedor_maquina(request):
    if request.method == 'POST':
        form = FornecedorMaquinaLocacaoForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fornecedor de maquina cadastrado com sucesso.')
            return redirect('lista_fornecedores_maquinas')
    else:
        form = FornecedorMaquinaLocacaoForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_fornecedor_maquina.html',
        {'form': form, 'titulo': 'Novo Fornecedor de Maquina'},
    )


def editar_fornecedor_maquina(request, fornecedor_id):
    fornecedor = get_object_or_404(FornecedorMaquinaLocacao, id=fornecedor_id, empresa=request.empresa)

    if request.method == 'POST':
        form = FornecedorMaquinaLocacaoForm(request.POST, instance=fornecedor, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fornecedor de maquina atualizado com sucesso.')
            return redirect('lista_fornecedores_maquinas')
    else:
        form = FornecedorMaquinaLocacaoForm(instance=fornecedor, empresa=request.empresa)

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
            'obras_filtro': LocacaoEquipamento.objects.filter(obra__empresa=request.empresa).select_related('obra').values_list(
                'obra_id', 'obra__nome_obra'
            ).distinct().order_by('obra__nome_obra'),
            'locadoras_filtro': LocadoraEquipamento.objects.filter(
                empresa=request.empresa,
                locacoes__isnull=False,
            ).distinct().order_by('nome'),
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
        locadora = LocadoraEquipamento.objects.filter(id=filtros['locadora'], empresa=request.empresa).first()
        if locadora:
            active_filters.append(f'Locadora: {locadora.nome}')
    if filtros['status']:
        active_filters.append(
            f"Situacao: {dict(LocacaoEquipamento.STATUS_CHOICES).get(filtros['status'], filtros['status'])}"
        )
    if filtros['busca']:
        active_filters.append(f"Busca: {filtros['busca']}")

    rows = []
    for locacao in locacoes:
        rows.append(
            {
                'data': format_date_br(locacao.data_locacao),
                'obra': locacao.obra.nome_obra,
                'locadora': str(locacao.locadora),
                'situacao': locacao.get_status_display(),
                'equipamento': str(locacao.equipamento),
                'quantidade': str(locacao.quantidade),
                'coleta': format_date_br(locacao.data_retirada),
                'observacao': (locacao.observacoes or '-').replace('\n', ' '),
            }
        )
    doc = PdfDocument(
        empresa=request.empresa,
        title='Relatorio de equipamentos locados',
        subtitle=f'{len(rows)} registro(s)',
        orientation='landscape',
        filename='relatorio_locacoes_equipamentos.pdf',
    )
    doc.add_title(filters=' | '.join(active_filters) if active_filters else 'Filtros: todos', emitted_on=date.today())
    doc.add_table(
        [
            PdfTableColumn('data', 'Data', weight=0.8, align='center'),
            PdfTableColumn('obra', 'Obra', weight=1.6),
            PdfTableColumn('locadora', 'Locadora', weight=1.3),
            PdfTableColumn('situacao', 'Situacao', weight=1.0, align='center'),
            PdfTableColumn('equipamento', 'Equipamento', weight=1.6),
            PdfTableColumn('quantidade', 'Qtd', weight=0.6, align='center'),
            PdfTableColumn('coleta', 'Coleta', weight=0.8, align='center'),
            PdfTableColumn('observacao', 'Observacao', weight=2.0),
        ],
        rows,
        row_height=44,
    )
    return doc.response()


def nova_locacao_equipamento(request):
    if request.method == 'POST':
        form = LocacaoEquipamentoForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Locacao de equipamento registrada com sucesso.')
            return redirect('lista_equipamentos_locados')
    else:
        form = LocacaoEquipamentoForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_locacao_equipamento.html',
        {'form': form, 'titulo': 'Nova Locacao de Equipamento'},
    )


def editar_locacao_equipamento(request, locacao_id):
    locacao = get_object_or_404(LocacaoEquipamento, id=locacao_id, obra__empresa=request.empresa)

    if request.method == 'POST':
        form = LocacaoEquipamentoForm(request.POST, instance=locacao, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Locacao de equipamento atualizada com sucesso.')
            return redirect('lista_equipamentos_locados')
    else:
        form = LocacaoEquipamentoForm(instance=locacao, empresa=request.empresa)

    return render(
        request,
        'controles/form_locacao_equipamento.html',
        {'form': form, 'titulo': 'Editar Locacao de Equipamento', 'locacao': locacao},
    )


def solicitar_retirada_equipamento(request, locacao_id):
    locacao = get_object_or_404(LocacaoEquipamento, id=locacao_id, obra__empresa=request.empresa)

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
    locacao = get_object_or_404(LocacaoEquipamento, id=locacao_id, obra__empresa=request.empresa)

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
    locadoras = LocadoraEquipamento.objects.filter(empresa=request.empresa)
    return render(request, 'controles/lista_locadoras.html', {'locadoras': locadoras})


def nova_locadora(request):
    if request.method == 'POST':
        form = LocadoraEquipamentoForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Locadora cadastrada com sucesso.')
            return redirect('lista_locadoras')
    else:
        form = LocadoraEquipamentoForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_locadora.html',
        {'form': form, 'titulo': 'Nova Locadora'},
    )


def lista_radar_obras(request):
    orcamentos = _radar_obras_queryset(request)
    ativos = OrcamentoRadarObra.objects.filter(empresa=request.empresa, arquivado=False)
    contadores = {
        'aguardando_resposta': ativos.filter(situacao='aguardando_resposta').count(),
        'em_revisao': ativos.filter(situacao='em_revisao').count(),
        'fechada': ativos.filter(situacao='fechada').count(),
        'nao_foi_para_frente': ativos.filter(situacao='nao_foi_para_frente').count(),
        'cancelada': ativos.filter(situacao='cancelada').count(),
        'arquivados': OrcamentoRadarObra.objects.filter(empresa=request.empresa, arquivado=True).count(),
    }
    return render(
        request,
        'controles/lista_radar_obras.html',
        {
            'orcamentos': orcamentos,
            'contadores': contadores,
            'filtros': _radar_obras_filtros(request),
            'situacao_choices': OrcamentoRadarObra.SITUACAO_CHOICES,
            'temperatura_choices': OrcamentoRadarObra.TEMPERATURA_CHOICES,
        },
    )


def _radar_obras_filtros(request):
    return {
        'busca': request.GET.get('busca', '').strip(),
        'situacao': request.GET.get('situacao', ''),
        'temperatura': request.GET.get('temperatura', ''),
        'responsavel': request.GET.get('responsavel', '').strip(),
        'valor_min': request.GET.get('valor_min', '').strip(),
        'valor_max': request.GET.get('valor_max', '').strip(),
        'data_inicio': request.GET.get('data_inicio', ''),
        'data_fim': request.GET.get('data_fim', ''),
        'arquivados': request.GET.get('arquivados', 'ativos'),
        'ordenar': request.GET.get('ordenar', 'temperatura_desc'),
    }


def _radar_obras_queryset(request):
    filtros = _radar_obras_filtros(request)
    queryset = OrcamentoRadarObra.objects.filter(empresa=request.empresa)

    if filtros['arquivados'] == 'arquivados':
        queryset = queryset.filter(arquivado=True)
    elif filtros['arquivados'] != 'todos':
        queryset = queryset.filter(arquivado=False)

    if filtros['busca']:
        busca = filtros['busca']
        queryset = queryset.filter(
            Q(numero__icontains=busca)
            | Q(cliente__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(responsavel__icontains=busca)
        )
    if filtros['situacao']:
        queryset = queryset.filter(situacao=filtros['situacao'])
    if filtros['temperatura']:
        queryset = queryset.filter(temperatura=filtros['temperatura'])
    if filtros['responsavel']:
        queryset = queryset.filter(responsavel__icontains=filtros['responsavel'])
    if filtros['valor_min']:
        try:
            queryset = queryset.filter(valor_estimado__gte=Decimal(filtros['valor_min'].replace(',', '.')))
        except Exception:
            pass
    if filtros['valor_max']:
        try:
            queryset = queryset.filter(valor_estimado__lte=Decimal(filtros['valor_max'].replace(',', '.')))
        except Exception:
            pass
    if filtros['data_inicio']:
        queryset = queryset.filter(data_orcamento__gte=filtros['data_inicio'])
    if filtros['data_fim']:
        queryset = queryset.filter(data_orcamento__lte=filtros['data_fim'])

    order_map = {
        'temperatura_desc': ['-temperatura', '-valor_estimado', '-data_orcamento'],
        'temperatura_asc': ['temperatura', '-valor_estimado', '-data_orcamento'],
        'valor_desc': ['-valor_estimado', '-temperatura', '-data_orcamento'],
        'valor_asc': ['valor_estimado', '-temperatura', '-data_orcamento'],
        'data_desc': ['-data_orcamento', '-id'],
        'data_asc': ['data_orcamento', 'id'],
        'cliente': ['cliente', '-data_orcamento'],
        'responsavel': ['responsavel', '-temperatura', '-valor_estimado'],
        'situacao': ['situacao', '-temperatura', '-valor_estimado'],
    }
    return queryset.order_by(*order_map.get(filtros['ordenar'], order_map['temperatura_desc']))


def atualizar_radar_obra(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoRadarObra, id=orcamento_id, empresa=request.empresa)
    if request.method == 'POST':
        situacoes = {choice[0] for choice in OrcamentoRadarObra.SITUACAO_CHOICES}
        temperaturas = {str(choice[0]) for choice in OrcamentoRadarObra.TEMPERATURA_CHOICES}
        situacao = request.POST.get('situacao')
        temperatura = request.POST.get('temperatura')
        update_fields = []
        if situacao in situacoes:
            orcamento.situacao = situacao
            update_fields.append('situacao')
        if temperatura in temperaturas:
            orcamento.temperatura = int(temperatura)
            update_fields.append('temperatura')
        if update_fields:
            orcamento.save(update_fields=update_fields + ['updated_at'])
            messages.success(request, 'Radar atualizado com sucesso.')
    return redirect(f"{reverse('lista_radar_obras')}?{request.GET.urlencode()}")


def atualizar_radar_obras_em_lote(request):
    if request.method == 'POST':
        situacoes = {choice[0] for choice in OrcamentoRadarObra.SITUACAO_CHOICES}
        temperaturas = {str(choice[0]) for choice in OrcamentoRadarObra.TEMPERATURA_CHOICES}
        ids = request.POST.getlist('orcamento_id')
        atualizados = 0

        for orcamento in OrcamentoRadarObra.objects.filter(empresa=request.empresa, id__in=ids):
            situacao = request.POST.get(f'situacao_{orcamento.id}')
            temperatura = request.POST.get(f'temperatura_{orcamento.id}')
            update_fields = []

            if situacao in situacoes and situacao != orcamento.situacao:
                orcamento.situacao = situacao
                update_fields.append('situacao')
            if temperatura in temperaturas and int(temperatura) != orcamento.temperatura:
                orcamento.temperatura = int(temperatura)
                update_fields.append('temperatura')

            if update_fields:
                orcamento.save(update_fields=update_fields + ['updated_at'])
                atualizados += 1

        if atualizados:
            messages.success(request, f'{atualizados} orcamento(s) atualizado(s) no radar.')
        else:
            messages.info(request, 'Nenhuma alteracao para salvar no radar.')

    return redirect(f"{reverse('lista_radar_obras')}?{request.GET.urlencode()}")


def arquivar_radar_obra(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoRadarObra, id=orcamento_id, empresa=request.empresa)
    if request.method == 'POST':
        orcamento.arquivado = request.POST.get('arquivar') == '1'
        orcamento.save(update_fields=['arquivado', 'updated_at'])
        messages.success(request, 'Orçamento arquivado.' if orcamento.arquivado else 'Orçamento reativado.')
    return redirect(f"{reverse('lista_radar_obras')}?{request.GET.urlencode()}")


def radar_obras_pdf(request):
    orcamentos = list(_radar_obras_queryset(request))
    pdf = _radar_obras_pdf(orcamentos, _radar_obras_filtros(request), request.empresa)
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="radar_obras.pdf"'
    return response


def _radar_obras_pdf(orcamentos, filtros, empresa=None):
    empresa = empresa or (orcamentos[0].empresa if orcamentos else None)
    rows = [
        {
            'numero': orcamento.numero,
            'data': format_date_br(orcamento.data_orcamento),
            'cliente': orcamento.cliente,
            'descricao': orcamento.descricao,
            'situacao': orcamento.get_situacao_display(),
            'calor': orcamento.get_temperatura_display(),
            'valor': format_money_br(orcamento.valor_estimado),
            'responsavel': orcamento.responsavel or '-',
        }
        for orcamento in orcamentos
    ]
    doc = PdfDocument(
        empresa=empresa,
        title='Radar de Obras',
        subtitle=f'{len(orcamentos)} registro(s)',
        orientation='landscape',
        filename='radar_obras.pdf',
    )
    doc.add_title(
        filters=f"Arquivados: {filtros['arquivados']} | Ordenacao: {filtros['ordenar']}",
        emitted_on=date.today(),
    )
    doc.add_table(
        [
            PdfTableColumn('numero', 'Nr orcamento', weight=0.9, align='center'),
            PdfTableColumn('data', 'Data', weight=0.9, align='center'),
            PdfTableColumn('cliente', 'Cliente', weight=1.5),
            PdfTableColumn('descricao', 'Descricao', weight=2.7),
            PdfTableColumn('situacao', 'Situacao', weight=1.3, align='center'),
            PdfTableColumn('calor', 'Calor', weight=0.9, align='center'),
            PdfTableColumn('valor', 'Valor', weight=1.2, align='right'),
            PdfTableColumn('responsavel', 'Responsavel', weight=1.3),
        ],
        rows,
        row_height=42,
    )
    return doc.build()


def novo_radar_obra(request):
    if request.method == 'POST':
        form = OrcamentoRadarObraForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Orcamento cadastrado no radar com sucesso.')
            return redirect('lista_radar_obras')
    else:
        form = OrcamentoRadarObraForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_radar_obra.html',
        {'form': form, 'titulo': 'Novo Orcamento'},
    )


def editar_radar_obra(request, orcamento_id):
    orcamento = get_object_or_404(OrcamentoRadarObra, id=orcamento_id, empresa=request.empresa)

    if request.method == 'POST':
        form = OrcamentoRadarObraForm(request.POST, instance=orcamento, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Orcamento atualizado com sucesso.')
            return redirect('lista_radar_obras')
    else:
        form = OrcamentoRadarObraForm(instance=orcamento, empresa=request.empresa)

    return render(
        request,
        'controles/form_radar_obra.html',
        {'form': form, 'titulo': 'Editar Orcamento', 'orcamento': orcamento},
    )


def lista_concretagens(request):
    contratos = ContratoConcretagem.objects.select_related('obra').prefetch_related('faturamentos').filter(
        obra__empresa=request.empresa,
    )
    return render(request, 'controles/lista_concretagens.html', {'contratos': contratos})


def lista_solicitantes_concretagem(request):
    solicitantes = SolicitanteConcretagem.objects.filter(empresa=request.empresa)
    return render(
        request,
        'controles/lista_solicitantes_concretagem.html',
        {'solicitantes': solicitantes},
    )


def novo_solicitante_concretagem(request):
    if request.method == 'POST':
        form = SolicitanteConcretagemForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Solicitante cadastrado com sucesso.')
            return redirect('lista_solicitantes_concretagem')
    else:
        form = SolicitanteConcretagemForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_solicitante_concretagem.html',
        {'form': form, 'titulo': 'Novo Solicitante'},
    )


def editar_solicitante_concretagem(request, solicitante_id):
    solicitante = get_object_or_404(SolicitanteConcretagem, id=solicitante_id, empresa=request.empresa)

    if request.method == 'POST':
        form = SolicitanteConcretagemForm(request.POST, instance=solicitante, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Solicitante atualizado com sucesso.')
            return redirect('lista_solicitantes_concretagem')
    else:
        form = SolicitanteConcretagemForm(instance=solicitante, empresa=request.empresa)

    return render(
        request,
        'controles/form_solicitante_concretagem.html',
        {'form': form, 'titulo': 'Editar Solicitante', 'solicitante': solicitante},
    )


def novo_contrato_concretagem(request):
    if request.method == 'POST':
        form = ContratoConcretagemForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            contrato = form.save()
            messages.success(request, 'Contrato de concretagem cadastrado com sucesso.')
            return redirect('detalhe_contrato_concretagem', contrato_id=contrato.id)
    else:
        form = ContratoConcretagemForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_contrato_concretagem.html',
        {'form': form, 'titulo': 'Novo Contrato de Concretagem'},
    )


def detalhe_contrato_concretagem(request, contrato_id):
    contrato = get_object_or_404(
        ContratoConcretagem.objects.select_related('obra').prefetch_related('faturamentos'),
        id=contrato_id,
        obra__empresa=request.empresa,
    )
    return render(request, 'controles/detalhe_contrato_concretagem.html', {'contrato': contrato})


def editar_contrato_concretagem(request, contrato_id):
    contrato = get_object_or_404(ContratoConcretagem, id=contrato_id, obra__empresa=request.empresa)

    if request.method == 'POST':
        form = ContratoConcretagemForm(request.POST, instance=contrato, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Contrato de concretagem atualizado com sucesso.')
            return redirect('detalhe_contrato_concretagem', contrato_id=contrato.id)
    else:
        form = ContratoConcretagemForm(instance=contrato, empresa=request.empresa)

    return render(
        request,
        'controles/form_contrato_concretagem.html',
        {'form': form, 'titulo': 'Editar Contrato de Concretagem', 'contrato': contrato},
    )


def novo_faturamento_concretagem(request, contrato_id):
    contrato = get_object_or_404(ContratoConcretagem, id=contrato_id, obra__empresa=request.empresa)

    if request.method == 'POST':
        form = FaturamentoConcretagemForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            faturamento = form.save(commit=False)
            faturamento.contrato = contrato
            faturamento.save()
            messages.success(request, 'Faturamento de concretagem cadastrado com sucesso.')
            return redirect('detalhe_contrato_concretagem', contrato_id=contrato.id)
    else:
        form = FaturamentoConcretagemForm(empresa=request.empresa)

    return render(
        request,
        'controles/form_faturamento_concretagem.html',
        {'form': form, 'titulo': 'Nova Concretagem', 'contrato': contrato},
    )


def editar_faturamento_concretagem(request, faturamento_id):
    faturamento = get_object_or_404(
        FaturamentoConcretagem.objects.select_related('contrato'),
        id=faturamento_id,
        contrato__obra__empresa=request.empresa,
    )
    contrato = faturamento.contrato

    if request.method == 'POST':
        form = FaturamentoConcretagemForm(request.POST, instance=faturamento, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faturamento de concretagem atualizado com sucesso.')
            return redirect('detalhe_contrato_concretagem', contrato_id=contrato.id)
    else:
        form = FaturamentoConcretagemForm(instance=faturamento, empresa=request.empresa)

    return render(
        request,
        'controles/form_faturamento_concretagem.html',
        {'form': form, 'titulo': 'Editar Concretagem', 'contrato': contrato},
    )
