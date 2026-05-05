from django import forms
from django.forms import inlineformset_factory

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
        help_text='CSV com item, descricao, unidade, quantidade, unitario material, unitario mao de obra e unitario equipamentos.'
    )
    observacoes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        from obras.models import Obra

        super().__init__(*args, **kwargs)
        self.fields['obra'].queryset = Obra.objects.all()


class MedicaoConstrutoraForm(BootstrapModelForm):
    class Meta:
        model = MedicaoConstrutora
        fields = [
            'numero',
            'periodo_inicio',
            'periodo_fim',
            'data_medicao',
            'retencao_tecnica',
            'issqn',
            'inss',
            'desconto_adicional',
            'faturamento_direto',
            'descricao_faturamento_direto',
            'valor_faturamento_direto',
            'observacoes',
        ]
        widgets = {
            'periodo_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'periodo_fim': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_medicao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'retencao_tecnica': forms.NumberInput(attrs={'step': '0.01'}),
            'issqn': forms.NumberInput(attrs={'step': '0.01'}),
            'inss': forms.NumberInput(attrs={'step': '0.01'}),
            'desconto_adicional': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_faturamento_direto': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class ItemMedicaoConstrutoraForm(BootstrapModelForm):
    class Meta:
        model = ItemMedicaoConstrutora
        fields = ['quantidade_periodo']
        widgets = {
            'quantidade_periodo': forms.NumberInput(attrs={'step': '0.0001'}),
        }


class MedicaoEmpreiteiroForm(BootstrapModelForm):
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
            'desconto_adicional',
            'observacoes',
        ]
        widgets = {
            'periodo_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'periodo_fim': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_medicao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'retencao_tecnica': forms.NumberInput(attrs={'step': '0.01'}),
            'desconto_adicional': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


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
