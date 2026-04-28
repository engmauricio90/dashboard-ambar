from decimal import Decimal
from io import BytesIO
import unicodedata

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    BaixarLocacaoEquipamentoForm,
    ContratoConcretagemForm,
    EquipamentoLocadoCatalogoForm,
    FaturamentoConcretagemForm,
    LocacaoEquipamentoForm,
    LocadoraEquipamentoForm,
    OrcamentoRadarObraForm,
    RegistroAbastecimentoForm,
    SolicitarRetiradaEquipamentoForm,
    SolicitanteConcretagemForm,
    VeiculoMaquinaForm,
)
from .models import (
    ContratoConcretagem,
    EquipamentoLocadoCatalogo,
    FaturamentoConcretagem,
    LocacaoEquipamento,
    LocadoraEquipamento,
    OrcamentoRadarObra,
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


def home(request):
    totais = {
        'veiculos': VeiculoMaquina.objects.count(),
        'abastecimentos': RegistroAbastecimento.objects.count(),
        'locacoes_abertas': LocacaoEquipamento.objects.filter(
            status__in=['locado', 'retirada_solicitada'],
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
