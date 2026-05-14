from django import forms
from django.db import models
from django.forms import inlineformset_factory

from controles.models import FaturamentoDireto
from obras.forms import BootstrapForm, BootstrapModelForm

from .models import (
    ItemMedicaoConstrutora,
    ItemMedicaoEmpreiteiro,
    MedicaoConstrutora,
    MedicaoEmpreiteiro,
    OrcamentoMedicao,
)


class ImportarOrcamentoForm(BootstrapForm):
    obra = forms.ModelChoiceField(queryset=None)
    nome = forms.CharField(max_length=180)
    tipo = forms.ChoiceField(choices=OrcamentoMedicao.TIPO_CHOICES)
    arquivo = forms.FileField(
        help_text='CSV com cabecalho: item, descricao, unidade, quantidade, unitario material, unitario mao de obra e unitario equipamentos.'
    )
    observacoes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        from obras.models import Obra

        super().__init__(*args, **kwargs)
        self.fields['obra'].queryset = Obra.objects.all()


class MedicaoConstrutoraForm(BootstrapModelForm):
    faturamentos_diretos = forms.ModelMultipleChoiceField(
        queryset=FaturamentoDireto.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Faturamentos diretos descontados nesta medicao',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        obra = self.instance.orcamento.obra if self.instance and self.instance.pk else None
        if obra:
            vinculados = self.instance.faturamentos_diretos.values_list('faturamento_direto_id', flat=True)
            self.fields['faturamentos_diretos'].queryset = FaturamentoDireto.objects.filter(
                obra=obra,
            ).filter(
                models.Q(vinculo_medicao__isnull=True) | models.Q(id__in=vinculados)
            ).order_by('data_lancamento', 'id')
            self.fields['faturamentos_diretos'].initial = list(vinculados)

    def clean(self):
        cleaned_data = super().clean()
        inicio = cleaned_data.get('periodo_inicio')
        fim = cleaned_data.get('periodo_fim')
        if inicio and fim and fim < inicio:
            self.add_error('periodo_fim', 'A data final nao pode ser anterior ao inicio do periodo.')
        for field in [
            'retencao_tecnica',
            'retencao_tecnica_percentual',
            'issqn',
            'issqn_percentual',
            'inss',
            'inss_percentual',
            'desconto_adicional',
            'desconto_adicional_percentual',
        ]:
            value = cleaned_data.get(field)
            if value is not None and value < 0:
                self.add_error(field, 'Informe um valor positivo.')
        return cleaned_data

    class Meta:
        model = MedicaoConstrutora
        fields = [
            'numero',
            'periodo_inicio',
            'periodo_fim',
            'data_medicao',
            'retencao_tecnica',
            'retencao_tecnica_percentual',
            'issqn',
            'issqn_percentual',
            'inss',
            'inss_percentual',
            'desconto_adicional',
            'desconto_adicional_percentual',
            'observacoes',
        ]
        widgets = {
            'periodo_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'periodo_fim': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_medicao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'retencao_tecnica': forms.NumberInput(attrs={'step': '0.01'}),
            'retencao_tecnica_percentual': forms.NumberInput(attrs={'step': '0.0001'}),
            'issqn': forms.NumberInput(attrs={'step': '0.01'}),
            'issqn_percentual': forms.NumberInput(attrs={'step': '0.0001'}),
            'inss': forms.NumberInput(attrs={'step': '0.01'}),
            'inss_percentual': forms.NumberInput(attrs={'step': '0.0001'}),
            'desconto_adicional': forms.NumberInput(attrs={'step': '0.01'}),
            'desconto_adicional_percentual': forms.NumberInput(attrs={'step': '0.0001'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'retencao_tecnica': 'Retencao tecnica (R$)',
            'retencao_tecnica_percentual': 'Retencao tecnica (%)',
            'issqn': 'ISSQN (R$)',
            'issqn_percentual': 'ISSQN (%)',
            'inss': 'INSS (R$)',
            'inss_percentual': 'INSS (%)',
            'desconto_adicional': 'Desconto adicional (R$)',
            'desconto_adicional_percentual': 'Desconto adicional (%)',
        }


class MedicaoConstrutoraCabecalhoForm(MedicaoConstrutoraForm):
    class Meta(MedicaoConstrutoraForm.Meta):
        fields = ['numero', 'periodo_inicio', 'periodo_fim', 'data_medicao', 'observacoes']


class ItemMedicaoConstrutoraForm(BootstrapModelForm):
    class Meta:
        model = ItemMedicaoConstrutora
        fields = ['quantidade_periodo']
        widgets = {
            'quantidade_periodo': forms.NumberInput(attrs={'step': '0.0001'}),
        }

    def clean_quantidade_periodo(self):
        quantidade = self.cleaned_data.get('quantidade_periodo') or 0
        if quantidade < 0:
            raise forms.ValidationError('Informe uma quantidade positiva.')
        if self.instance and self.instance.pk:
            saldo_disponivel = self.instance.item_orcamento.quantidade - self.instance.quantidade_acumulada_anterior
            if quantidade > saldo_disponivel:
                raise forms.ValidationError(f'Quantidade acima do saldo disponivel ({saldo_disponivel:.4f}).')
        return quantidade


class MedicaoEmpreiteiroForm(BootstrapModelForm):
    def clean(self):
        cleaned_data = super().clean()
        inicio = cleaned_data.get('periodo_inicio')
        fim = cleaned_data.get('periodo_fim')
        if inicio and fim and fim < inicio:
            self.add_error('periodo_fim', 'A data final nao pode ser anterior ao inicio do periodo.')
        for field in ['retencao_tecnica', 'retencao_tecnica_percentual', 'desconto_adicional', 'desconto_adicional_percentual']:
            value = cleaned_data.get(field)
            if value is not None and value < 0:
                self.add_error(field, 'Informe um valor positivo.')
        return cleaned_data

    class Meta:
        model = MedicaoEmpreiteiro
        fields = [
            'obra',
            'empreiteiro',
            'cpf_cnpj',
            'pix',
            'numero',
            'periodo_inicio',
            'periodo_fim',
            'data_medicao',
            'retencao_tecnica',
            'retencao_tecnica_percentual',
            'desconto_adicional',
            'desconto_adicional_percentual',
            'observacoes',
        ]
        widgets = {
            'periodo_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'periodo_fim': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_medicao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'retencao_tecnica': forms.NumberInput(attrs={'step': '0.01'}),
            'retencao_tecnica_percentual': forms.NumberInput(attrs={'step': '0.0001'}),
            'desconto_adicional': forms.NumberInput(attrs={'step': '0.01'}),
            'desconto_adicional_percentual': forms.NumberInput(attrs={'step': '0.0001'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'retencao_tecnica': 'Retencao tecnica (R$)',
            'retencao_tecnica_percentual': 'Retencao tecnica (%)',
            'desconto_adicional': 'Desconto adicional (R$)',
            'desconto_adicional_percentual': 'Desconto adicional (%)',
        }


class MedicaoEmpreiteiroCabecalhoForm(MedicaoEmpreiteiroForm):
    class Meta(MedicaoEmpreiteiroForm.Meta):
        fields = [
            'obra',
            'empreiteiro',
            'cpf_cnpj',
            'pix',
            'numero',
            'periodo_inicio',
            'periodo_fim',
            'data_medicao',
            'observacoes',
        ]


class ItemMedicaoEmpreiteiroForm(BootstrapModelForm):
    class Meta:
        model = ItemMedicaoEmpreiteiro
        fields = ['item_orcamento', 'item', 'descricao', 'unidade', 'quantidade_periodo', 'valor_unitario']
        widgets = {
            'quantidade_periodo': forms.NumberInput(attrs={'step': '0.0001'}),
            'valor_unitario': forms.NumberInput(attrs={'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        orcamento = kwargs.pop('orcamento', None)
        super().__init__(*args, **kwargs)
        if orcamento:
            self.fields['item_orcamento'].queryset = orcamento.itens.all()
        else:
            self.fields['item_orcamento'].required = False
        for field in self.fields.values():
            field.required = False

    def clean(self):
        cleaned_data = super().clean()
        marked_delete = cleaned_data.get('DELETE')
        if marked_delete:
            return cleaned_data

        item_orcamento = cleaned_data.get('item_orcamento')
        descricao = cleaned_data.get('descricao')
        quantidade = cleaned_data.get('quantidade_periodo')
        valor_unitario = cleaned_data.get('valor_unitario')
        has_data = item_orcamento or descricao or quantidade not in (None, '') or valor_unitario not in (None, '')
        if has_data:
            if not item_orcamento and not descricao:
                self.add_error('descricao', 'Informe a descricao do item.')
            if quantidade in (None, ''):
                self.add_error('quantidade_periodo', 'Informe a quantidade medida.')
            if not item_orcamento and valor_unitario in (None, ''):
                self.add_error('valor_unitario', 'Informe o valor unitario.')
        return cleaned_data


ItemMedicaoConstrutoraFormSet = inlineformset_factory(
    MedicaoConstrutora,
    ItemMedicaoConstrutora,
    form=ItemMedicaoConstrutoraForm,
    extra=0,
    can_delete=False,
)


class BaseItemMedicaoEmpreiteiroFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.orcamento = kwargs.pop('orcamento', None)
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['orcamento'] = self.orcamento
        return super()._construct_form(i, **kwargs)


ItemMedicaoEmpreiteiroFormSet = inlineformset_factory(
    MedicaoEmpreiteiro,
    ItemMedicaoEmpreiteiro,
    form=ItemMedicaoEmpreiteiroForm,
    formset=BaseItemMedicaoEmpreiteiroFormSet,
    extra=8,
    can_delete=True,
)
