from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory

from obras.forms import BootstrapForm, BootstrapModelForm

from .models import CentroCusto, ContaPagar, ContaReceber, Fornecedor, ItemContaPagarOrdemCompra


class ImportarCredoresSiengeForm(forms.Form):
    TIPO_RELATORIO_CHOICES = [
        ('aberto', 'Contas em aberto'),
        ('pago', 'Contas pagas'),
    ]

    tipo_relatorio = forms.ChoiceField(label='Tipo de relatório', choices=TIPO_RELATORIO_CHOICES)
    arquivo = forms.FileField(label='Arquivo CSV')


class FornecedorForm(BootstrapModelForm):
    class Meta:
        model = Fornecedor
        fields = [
            'nome',
            'cpf_cnpj',
            'ie_identidade',
            'endereco',
            'bairro',
            'cidade',
            'uf',
            'municipio',
            'cep',
            'telefone',
            'ativo',
        ]
        labels = {
            'municipio': 'Municipio legado',
            'uf': 'UF',
        }
        help_texts = {
            'municipio': 'Campo antigo mantido para compatibilidade. Priorize cidade e UF.',
        }


class CentroCustoForm(BootstrapModelForm):
    class Meta:
        model = CentroCusto
        fields = ['nome', 'descricao', 'ativo']
        widgets = {
            'descricao': forms.Textarea(attrs={'rows': 3}),
        }


class ContaReceberForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['obra'].required = True
        self.fields['numero_nf'].required = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.obra_id:
            instance.cliente = instance.obra.cliente or instance.obra.nome_obra
        if not instance.pk:
            instance.status = ContaReceber.STATUS_ABERTO
            instance.data_recebimento = None
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    class Meta:
        model = ContaReceber
        fields = [
            'obra',
            'centro_custo',
            'numero_nf',
            'descricao',
            'data_emissao',
            'data_vencimento',
            'valor_bruto',
            'issqn_retido',
            'inss_retido',
            'retencao_tecnica',
            'outras_retencoes',
            'observacoes',
        ]
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_vencimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor_bruto': forms.NumberInput(attrs={'step': '0.01'}),
            'issqn_retido': forms.NumberInput(attrs={'step': '0.01'}),
            'inss_retido': forms.NumberInput(attrs={'step': '0.01'}),
            'retencao_tecnica': forms.NumberInput(attrs={'step': '0.01'}),
            'outras_retencoes': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        obra = cleaned_data.get('obra')
        numero_nf = cleaned_data.get('numero_nf')

        if not obra:
            self.add_error('obra', 'Informe a obra da receita.')
        if not numero_nf:
            self.add_error('numero_nf', 'Informe o numero da NF para integrar com a obra.')
        return cleaned_data


class ContaReceberBaixaForm(forms.Form):
    data_recebimento = forms.DateField(
        label='Data do recebimento',
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
    )
    observacoes = forms.CharField(
        label='Observacoes do recebimento',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
    )


class ContaPagarForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from controles.models import ItemOrdemCompraGeral, OrdemCompraGeral

        self.fields['ordem_compra'].queryset = OrdemCompraGeral.objects.all()
        self.fields['ordem_compra'].empty_label = 'Nao possui OC'

        ordem_id = None
        if self.is_bound:
            ordem_id = self.data.get(self.add_prefix('ordem_compra'))
        elif self.instance and self.instance.ordem_compra_id:
            ordem_id = self.instance.ordem_compra_id
        elif self.initial.get('ordem_compra'):
            ordem_id = self.initial['ordem_compra']

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.pk:
            instance.status = ContaPagar.STATUS_ABERTO
            instance.data_pagamento = None
            instance.valor_pago = Decimal('0')
        if commit:
            instance.save()
            self.save_m2m()
        return instance


    class Meta:
        model = ContaPagar
        fields = [
            'fornecedor',
            'fornecedor_cadastro',
            'obra',
            'centro_custo',
            'categoria',
            'ordem_compra',
            'numero_nf',
            'descricao',
            'data_emissao',
            'data_vencimento',
            'valor',
            'observacoes',
        ]
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_vencimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'ordem_compra': 'Ordem de compra',
            'numero_nf': 'Numero da NF',
        }

    def clean(self):
        cleaned_data = super().clean()
        ordem_compra = cleaned_data.get('ordem_compra')
        numero_nf = cleaned_data.get('numero_nf')
        if ordem_compra:
            if not numero_nf:
                self.add_error('numero_nf', 'Informe o numero da NF para vincular a OC.')
        return cleaned_data


class ContaPagarBaixaForm(forms.Form):
    data_pagamento = forms.DateField(
        label='Data do pagamento',
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
    )
    valor_pago = forms.DecimalField(
        label='Valor pago efetivamente',
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
    )
    observacoes = forms.CharField(
        label='Observacoes do pagamento',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
    )


class ItemContaPagarOrdemCompraForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        ordem = kwargs.pop('ordem', None)
        super().__init__(*args, **kwargs)
        from controles.models import ItemOrdemCompraGeral

        self.fields['item_ordem_compra'].queryset = (
            ItemOrdemCompraGeral.objects.filter(ordem=ordem) if ordem else ItemOrdemCompraGeral.objects.all()
        )
        self.fields['item_ordem_compra'].empty_label = 'Selecione o item'
        self.fields['item_ordem_compra'].label_from_instance = (
            lambda item: f'OC {item.ordem_id} - {item.item:02d} - {item.descricao} - R$ {item.valor_unitario:.2f}'
        )
        for field in self.fields.values():
            field.required = False

    def has_changed(self):
        if self.data and self.prefix and not self.data.get(f'{self.prefix}-id'):
            relevant_fields = ['item_ordem_compra', 'quantidade']
            if not any((self.data.get(f'{self.prefix}-{field}') or '').strip() for field in relevant_fields):
                return False
        return super().has_changed()

    class Meta:
        model = ItemContaPagarOrdemCompra
        fields = ['item_ordem_compra', 'quantidade']
        widgets = {
            'quantidade': forms.NumberInput(attrs={'step': '0.01'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        marked_delete = cleaned_data.get('DELETE')
        if marked_delete:
            return cleaned_data
        item = cleaned_data.get('item_ordem_compra')
        quantidade = cleaned_data.get('quantidade')
        if item or quantidade not in (None, ''):
            if not item:
                self.add_error('item_ordem_compra', 'Selecione o item da OC.')
            if not quantidade or quantidade <= 0:
                self.add_error('quantidade', 'Informe a quantidade faturada.')
        return cleaned_data


class BaseItemContaPagarOrdemCompraFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.ordem = kwargs.pop('ordem', None)
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['ordem'] = self.ordem
        return super()._construct_form(i, **kwargs)


ItemContaPagarOrdemCompraFormSet = inlineformset_factory(
    ContaPagar,
    ItemContaPagarOrdemCompra,
    form=ItemContaPagarOrdemCompraForm,
    formset=BaseItemContaPagarOrdemCompraFormSet,
    extra=0,
    can_delete=True,
)


class FinanceiroFiltroForm(BootstrapForm):
    TIPO_CHOICES = [
        ('', 'Todos'),
        ('receber', 'Contas a receber'),
        ('pagar', 'Contas a pagar'),
    ]
    STATUS_CHOICES = [
        ('', 'Todos'),
        ('aberto', 'Em aberto'),
        ('baixado', 'Recebido/Pago'),
        ('cancelado', 'Cancelado'),
        ('atrasado', 'Atrasado'),
    ]
    ORDENACAO_CHOICES = [
        ('data_asc', 'Data: menor para maior'),
        ('data_desc', 'Data: maior para menor'),
        ('fornecedor', 'Fornecedor/cliente'),
        ('centro_custo', 'Centro de custo'),
        ('obra', 'Obra'),
        ('valor_desc', 'Valor: maior para menor'),
        ('valor_asc', 'Valor: menor para maior'),
    ]
    AGRUPAMENTO_CHOICES = [
        ('', 'Sem agrupamento'),
        ('centro_custo', 'Centro de custo'),
        ('fornecedor', 'Fornecedor/cliente'),
        ('obra', 'Obra'),
        ('status', 'Status'),
        ('tipo', 'Tipo'),
    ]

    tipo = forms.ChoiceField(label='Tipo', required=False, choices=TIPO_CHOICES)
    status = forms.ChoiceField(label='Status', required=False, choices=STATUS_CHOICES)
    ordenacao = forms.ChoiceField(
        label='Ordenar por',
        required=False,
        choices=ORDENACAO_CHOICES,
        initial='data_asc',
    )
    agrupamento = forms.ChoiceField(label='Separar por', required=False, choices=AGRUPAMENTO_CHOICES)
    data_inicial = forms.DateField(
        label='Data inicial',
        required=False,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
    )
    data_final = forms.DateField(
        label='Data final',
        required=False,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
    )
    obra = forms.CharField(label='Obra', required=False)
    centro_custo = forms.ModelChoiceField(label='Centro de custo', required=False, queryset=CentroCusto.objects.all())
    busca = forms.CharField(label='Busca', required=False)

    def clean(self):
        cleaned_data = super().clean()
        data_inicial = cleaned_data.get('data_inicial')
        data_final = cleaned_data.get('data_final')
        if data_inicial and data_final and data_inicial > data_final:
            raise forms.ValidationError('A data inicial nao pode ser maior que a data final.')
        return cleaned_data
