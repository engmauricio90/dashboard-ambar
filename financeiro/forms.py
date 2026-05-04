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
    class Meta:
        model = ContaPagar
        fields = [
            'fornecedor',
            'fornecedor_cadastro',
            'obra',
            'centro_custo',
            'categoria',
            'descricao',
            'data_emissao',
            'data_vencimento',
            'data_pagamento',
            'valor',
            'status',
            'observacoes',
        ]
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_vencimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_pagamento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        data_pagamento = cleaned_data.get('data_pagamento')
        if status == ContaPagar.STATUS_PAGO and not data_pagamento:
            self.add_error('data_pagamento', 'Informe a data de pagamento.')
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
