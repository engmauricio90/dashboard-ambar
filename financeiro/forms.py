from django import forms

from obras.forms import BootstrapForm, BootstrapModelForm

from .models import CentroCusto, ContaPagar, ContaReceber, Fornecedor


class FornecedorForm(BootstrapModelForm):
    class Meta:
        model = Fornecedor
        fields = ['nome', 'cpf_cnpj', 'ie_identidade', 'endereco', 'municipio', 'cep', 'telefone', 'ativo']


class CentroCustoForm(BootstrapModelForm):
    class Meta:
        model = CentroCusto
        fields = ['nome', 'descricao', 'ativo']
        widgets = {
            'descricao': forms.Textarea(attrs={'rows': 3}),
        }


class ContaReceberForm(BootstrapModelForm):
    class Meta:
        model = ContaReceber
        fields = [
            'cliente',
            'obra',
            'centro_custo',
            'numero_nf',
            'descricao',
            'data_emissao',
            'data_vencimento',
            'data_recebimento',
            'valor_bruto',
            'issqn_retido',
            'inss_retido',
            'retencao_tecnica',
            'outras_retencoes',
            'status',
            'observacoes',
        ]
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_vencimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_recebimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
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
        status = cleaned_data.get('status')
        data_recebimento = cleaned_data.get('data_recebimento')

        if obra and not numero_nf:
            self.add_error('numero_nf', 'Informe o numero da NF para integrar com a obra.')
        if status == ContaReceber.STATUS_RECEBIDO and not data_recebimento:
            self.add_error('data_recebimento', 'Informe a data de recebimento.')
        return cleaned_data


class ContaPagarForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from controles.models import ItemOrdemCompraGeral, OrdemCompraGeral

        self.fields['quantidade_oc'].required = False
        self.fields['valor_unitario_oc'].required = False
        self.fields['valor_pago'].required = False
        self.fields['ordem_compra'].queryset = OrdemCompraGeral.objects.all()
        self.fields['ordem_compra'].empty_label = 'Nao possui OC'

        ordem_id = None
        if self.is_bound:
            ordem_id = self.data.get(self.add_prefix('ordem_compra'))
        elif self.instance and self.instance.ordem_compra_id:
            ordem_id = self.instance.ordem_compra_id
        elif self.initial.get('ordem_compra'):
            ordem_id = self.initial['ordem_compra']

        if ordem_id:
            self.fields['item_ordem_compra'].queryset = ItemOrdemCompraGeral.objects.filter(ordem_id=ordem_id)
        else:
            self.fields['item_ordem_compra'].queryset = ItemOrdemCompraGeral.objects.all()
        self.fields['item_ordem_compra'].empty_label = 'Selecione o item da OC'
        self.fields['item_ordem_compra'].label_from_instance = (
            lambda item: f'OC {item.ordem_id} - {item.item:02d} - {item.descricao}'
        )

    class Meta:
        model = ContaPagar
        fields = [
            'fornecedor',
            'fornecedor_cadastro',
            'obra',
            'centro_custo',
            'categoria',
            'ordem_compra',
            'item_ordem_compra',
            'numero_nf',
            'quantidade_oc',
            'valor_unitario_oc',
            'descricao',
            'data_emissao',
            'data_vencimento',
            'data_pagamento',
            'valor',
            'valor_pago',
            'status',
            'observacoes',
        ]
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_vencimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_pagamento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'quantidade_oc': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_unitario_oc': forms.NumberInput(attrs={'step': '0.01'}),
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_pago': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'ordem_compra': 'Ordem de compra',
            'item_ordem_compra': 'Item da OC',
            'numero_nf': 'Numero da NF',
            'quantidade_oc': 'Quantidade faturada da OC',
            'valor_unitario_oc': 'Valor unitario da OC',
            'valor_pago': 'Valor pago efetivamente',
        }

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        data_pagamento = cleaned_data.get('data_pagamento')
        ordem_compra = cleaned_data.get('ordem_compra')
        item_ordem_compra = cleaned_data.get('item_ordem_compra')
        numero_nf = cleaned_data.get('numero_nf')
        quantidade_oc = cleaned_data.get('quantidade_oc')
        if status == ContaPagar.STATUS_PAGO and not data_pagamento:
            self.add_error('data_pagamento', 'Informe a data de pagamento.')
        if ordem_compra:
            if not item_ordem_compra:
                self.add_error('item_ordem_compra', 'Selecione o item da OC para vincular a nota.')
            if not numero_nf:
                self.add_error('numero_nf', 'Informe o numero da NF para vincular a OC.')
            if not quantidade_oc or quantidade_oc <= 0:
                self.add_error('quantidade_oc', 'Informe a quantidade faturada da OC.')
            if item_ordem_compra and item_ordem_compra.ordem_id != ordem_compra.id:
                self.add_error('item_ordem_compra', 'O item selecionado nao pertence a OC.')
        return cleaned_data


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

    tipo = forms.ChoiceField(required=False, choices=TIPO_CHOICES)
    status = forms.ChoiceField(required=False, choices=STATUS_CHOICES)
    data_inicial = forms.DateField(required=False, widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    data_final = forms.DateField(required=False, widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    obra = forms.CharField(required=False)
    centro_custo = forms.ModelChoiceField(required=False, queryset=CentroCusto.objects.all())
    busca = forms.CharField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        data_inicial = cleaned_data.get('data_inicial')
        data_final = cleaned_data.get('data_final')
        if data_inicial and data_final and data_inicial > data_final:
            raise forms.ValidationError('A data inicial nao pode ser maior que a data final.')
        return cleaned_data
