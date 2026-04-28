from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import PropostaForm, PropostaPlanilhaItemFormSet, PropostaResumoItemFormSet
from .models import Proposta


def normalizar_post_decimais(post_data):
    data = post_data.copy()
    suffixes = [
        'bdi_percentual',
        'valor',
        'quantidade',
        'preco_unit_material',
        'preco_unit_mao_obra',
    ]
    for key in list(data.keys()):
        if any(key.endswith(suffix) for suffix in suffixes):
            value = data.get(key, '')
            if value and ',' in value:
                if '.' in value:
                    value = value.replace('.', '')
                data[key] = value.replace(',', '.')
    return data


def salvar_formset_preenchido(formset):
    instances = formset.save(commit=False)

    for obj in formset.deleted_objects:
        obj.delete()

    for instance in instances:
        if getattr(instance, 'descricao', None):
            for field_name in ['ordem', 'quantidade', 'preco_unit_material', 'preco_unit_mao_obra', 'valor']:
                if hasattr(instance, field_name) and getattr(instance, field_name) is None:
                    field = instance._meta.get_field(field_name)
                    setattr(instance, field_name, field.default)
            instance.save()


def lista_propostas(request):
    propostas = Proposta.objects.prefetch_related('itens_resumo', 'itens_planilha').all()
    totais = {
        'total_propostas': propostas.count(),
        'aguardando_resposta': propostas.filter(situacao='aguardando_resposta').count(),
        'fechadas': propostas.filter(situacao='fechada').count(),
        'valor_em_aberto': sum(
            (proposta.total_final for proposta in propostas.filter(situacao='aguardando_resposta')),
            Decimal('0'),
        ),
    }
    return render(
        request,
        'propostas/lista_propostas.html',
        {'propostas': propostas, 'totais': totais},
    )


def nova_proposta(request):
    if request.method == 'POST':
        post_data = normalizar_post_decimais(request.POST)
        form = PropostaForm(post_data, request.FILES)
        resumo_formset = PropostaResumoItemFormSet(post_data, prefix='resumo')
        planilha_formset = PropostaPlanilhaItemFormSet(post_data, prefix='planilha')

        if form.is_valid() and resumo_formset.is_valid() and planilha_formset.is_valid():
            proposta = form.save()
            resumo_formset.instance = proposta
            salvar_formset_preenchido(resumo_formset)
            planilha_formset.instance = proposta
            salvar_formset_preenchido(planilha_formset)
            proposta.sincronizar_radar()
            messages.success(request, f'Proposta {proposta.numero_formatado} criada com sucesso.')
            return redirect('editar_proposta', proposta_id=proposta.id)
    else:
        form = PropostaForm()
        resumo_formset = PropostaResumoItemFormSet(prefix='resumo')
        planilha_formset = PropostaPlanilhaItemFormSet(prefix='planilha')

    return render(
        request,
        'propostas/form_proposta.html',
        {
            'form': form,
            'resumo_formset': resumo_formset,
            'planilha_formset': planilha_formset,
            'titulo': 'Nova proposta comercial',
        },
    )


def editar_proposta(request, proposta_id):
    proposta = get_object_or_404(Proposta, id=proposta_id)

    if request.method == 'POST':
        post_data = normalizar_post_decimais(request.POST)
        form = PropostaForm(post_data, request.FILES, instance=proposta)
        resumo_formset = PropostaResumoItemFormSet(post_data, instance=proposta, prefix='resumo')
        planilha_formset = PropostaPlanilhaItemFormSet(post_data, instance=proposta, prefix='planilha')

        if form.is_valid() and resumo_formset.is_valid() and planilha_formset.is_valid():
            proposta = form.save()
            salvar_formset_preenchido(resumo_formset)
            salvar_formset_preenchido(planilha_formset)
            proposta.sincronizar_radar()
            messages.success(request, f'Proposta {proposta.numero_formatado} atualizada com sucesso.')
            return redirect('editar_proposta', proposta_id=proposta.id)
    else:
        form = PropostaForm(instance=proposta)
        resumo_formset = PropostaResumoItemFormSet(instance=proposta, prefix='resumo')
        planilha_formset = PropostaPlanilhaItemFormSet(instance=proposta, prefix='planilha')

    return render(
        request,
        'propostas/form_proposta.html',
        {
            'form': form,
            'resumo_formset': resumo_formset,
            'planilha_formset': planilha_formset,
            'proposta': proposta,
            'titulo': f'Editar proposta {proposta.numero_formatado}',
        },
    )


def visualizar_proposta(request, proposta_id):
    proposta = get_object_or_404(
        Proposta.objects.prefetch_related('itens_resumo', 'itens_planilha'),
        id=proposta_id,
    )
    return render(
        request,
        'propostas/visualizar_proposta.html',
        {'proposta': proposta},
    )
