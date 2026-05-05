import csv
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from openpyxl import Workbook

from controles.views import _build_simple_pdf

from .forms import (
    ImportarOrcamentoForm,
    ItemMedicaoConstrutoraFormSet,
    ItemMedicaoEmpreiteiroFormSet,
    MedicaoConstrutoraForm,
    MedicaoEmpreiteiroForm,
)
from .models import (
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


def _read_csv(file):
    raw = file.read()
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
    return csv.DictReader(StringIO(content), delimiter=delimiter)


def medicoes_home(request):
    contexto = {
        'orcamentos': OrcamentoMedicao.objects.select_related('obra')[:8],
        'medicoes_construtora': MedicaoConstrutora.objects.select_related('orcamento', 'orcamento__obra')[:8],
        'medicoes_empreiteiro': MedicaoEmpreiteiro.objects.select_related('obra', 'orcamento')[:8],
    }
    return render(request, 'medicoes/home.html', contexto)


def lista_orcamentos(request):
    orcamentos = OrcamentoMedicao.objects.select_related('obra')
    return render(request, 'medicoes/lista_orcamentos.html', {'orcamentos': orcamentos})


def importar_orcamento(request):
    if request.method == 'POST':
        form = ImportarOrcamentoForm(request.POST, request.FILES)
        if form.is_valid():
            reader = _read_csv(form.cleaned_data['arquivo'])
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
            messages.success(request, f'Orcamento importado com {len(itens)} itens.')
            return redirect('detalhe_orcamento_medicao', orcamento_id=orcamento.id)
    else:
        form = ImportarOrcamentoForm()
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
        form = MedicaoConstrutoraForm(request.POST)
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
        form = MedicaoConstrutoraForm(initial=initial)
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


def nova_medicao_empreiteiro_simples(request):
    if request.method == 'POST':
        form = MedicaoEmpreiteiroForm(request.POST)
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
        form = MedicaoEmpreiteiroForm(
            initial={
                'numero': _next_numero(MedicaoEmpreiteiro, tipo=MedicaoEmpreiteiro.TIPO_SIMPLES),
                'data_medicao': timezone.localdate(),
                'periodo_inicio': timezone.localdate(),
                'periodo_fim': timezone.localdate(),
            }
        )
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
        form = MedicaoEmpreiteiroForm(request.POST)
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
        form = MedicaoEmpreiteiroForm(initial=initial)
    return render(request, 'medicoes/form_medicao.html', {'form': form, 'titulo': 'Nova medicao cumulativa de empreiteiro'})


def editar_medicao_empreiteiro(request, medicao_id):
    medicao = get_object_or_404(MedicaoEmpreiteiro.objects.select_related('obra', 'orcamento'), id=medicao_id)
    if request.method == 'POST':
        form = MedicaoEmpreiteiroForm(request.POST, instance=medicao)
        formset = ItemMedicaoEmpreiteiroFormSet(request.POST, instance=medicao, orcamento=medicao.orcamento)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
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
                f'Faturamento direto: {_money(medicao.valor_faturamento_direto)}',
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
    response = HttpResponse(
        _linhas_pdf_medicao(medicao, medicao.itens.select_related('item_orcamento'), 'Boletim de medicao de empreiteiro'),
        content_type='application/pdf',
    )
    response['Content-Disposition'] = f'inline; filename="medicao_empreiteiro_{medicao.numero}.pdf"'
    return response


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
    ws.append(['Subtotal', float(medicao.subtotal_periodo)])
    ws.append(['Retencao tecnica', float(medicao.retencao_tecnica)])
    if isinstance(medicao, MedicaoConstrutora):
        ws.append(['ISSQN', float(medicao.issqn)])
        ws.append(['INSS', float(medicao.inss)])
        ws.append(['Faturamento direto', float(medicao.valor_faturamento_direto)])
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
