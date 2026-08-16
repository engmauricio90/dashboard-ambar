from django import forms
from django.forms import inlineformset_factory

from obras.forms import BootstrapForm, BootstrapModelForm

from .models import (
    Empreiteiro,
    ItemMedicaoConstrutora,
    ItemMedicaoEmpreiteiro,
    ItemOrcamentoMedicao,
    MedicaoConstrutora,
    MedicaoEmpreiteiro,
    OrcamentoMedicao,
)


class ImportarOrcamentoForm(BootstrapForm):
    obra = forms.ModelChoiceField(queryset=None)
    nome = forms.CharField(max_length=180)
    tipo = forms.ChoiceField(choices=OrcamentoMedicao.TIPO_CHOICES)
    arquivo = forms.FileField(
        help_text='CSV com cabecalho: item, tipo, descricao, unidade, quantidade, preco_unitario_material, preco_unitario_mao_obra e preco_unitario_equipamentos.'
    )
    observacoes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        from obras.models import Obra

        empresa = kwargs.pop('empresa', None)
        super().__init__(*args, **kwargs)
        self.fields['obra'].queryset = Obra.objects.filter(empresa=empresa) if empresa else Obra.objects.none()


class OrcamentoMedicaoManualForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        from obras.models import Obra

        self.empresa = kwargs.pop('empresa', None)
        super().__init__(*args, **kwargs)
        self.fields['obra'].queryset = Obra.objects.filter(empresa=self.empresa) if self.empresa else Obra.objects.none()

    class Meta:
        model = OrcamentoMedicao
        fields = ['obra', 'nome', 'tipo', 'observacoes']
        widgets = {
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class EmpreiteiroForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        self.empresa = kwargs.pop('empresa', None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.empresa:
            instance.empresa = self.empresa
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    class Meta:
        model = Empreiteiro
        fields = ['nome', 'cpf_cnpj', 'pix', 'telefone', 'ativo', 'observacoes']
        widgets = {
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class RelatorioMedicoesForm(BootstrapForm):
    TIPO_CHOICES = [
        ('', 'Todas'),
        ('construtora', 'Construtora'),
        ('empreiteiro', 'Empreiteiros'),
        ('empreiteiro_simples', 'Empreiteiro simples'),
        ('empreiteiro_cumulativa', 'Empreiteiro cumulativa'),
    ]
    COLUNAS_CHOICES = [
        ('tipo', 'Tipo'),
        ('obra', 'Obra'),
        ('planilha', 'Planilha'),
        ('empreiteiro', 'Empreiteiro'),
        ('numero', 'Numero'),
        ('data_medicao', 'Data da medicao'),
        ('periodo', 'Periodo'),
        ('medido', 'Valor medido'),
        ('descontos', 'Descontos'),
        ('liquido', 'Valor liquido'),
        ('percentual', '% concluida'),
    ]
    COLUNAS_PADRAO = ['tipo', 'obra', 'planilha', 'empreiteiro', 'numero', 'data_medicao', 'medido', 'liquido']

    tipo = forms.ChoiceField(label='Tipo', required=False, choices=TIPO_CHOICES)
    obra = forms.ModelChoiceField(label='Obra', required=False, queryset=None)
    empreiteiro = forms.ModelChoiceField(label='Empreiteiro', required=False, queryset=None)
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
    colunas = forms.MultipleChoiceField(
        label='Colunas do relatorio',
        required=False,
        choices=COLUNAS_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        from obras.models import Obra

        empresa = kwargs.pop('empresa', None)
        super().__init__(*args, **kwargs)
        self.fields['obra'].queryset = Obra.objects.filter(empresa=empresa).order_by('nome_obra') if empresa else Obra.objects.none()
        self.fields['empreiteiro'].queryset = (
            Empreiteiro.objects.filter(empresa=empresa).order_by('nome') if empresa else Empreiteiro.objects.none()
        )
        self.fields['colunas'].initial = self.COLUNAS_PADRAO
        self.fields['colunas'].widget.attrs['class'] = 'form-check-input'

    def clean_colunas(self):
        return self.cleaned_data.get('colunas') or self.COLUNAS_PADRAO

    def clean(self):
        cleaned_data = super().clean()
        data_inicial = cleaned_data.get('data_inicial')
        data_final = cleaned_data.get('data_final')
        if data_inicial and data_final and data_inicial > data_final:
            raise forms.ValidationError('A data inicial nao pode ser maior que a data final.')
        return cleaned_data


class ItemOrcamentoMedicaoForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in [
            'quantidade',
            'preco_unitario_material',
            'preco_unitario_mao_obra',
            'preco_unitario_equipamentos',
        ]:
            self.fields[field].required = False

    class Meta:
        model = ItemOrcamentoMedicao
        fields = [
            'tipo',
            'ordem',
            'item',
            'descricao',
            'unidade',
            'quantidade',
            'preco_unitario_material',
            'preco_unitario_mao_obra',
            'preco_unitario_equipamentos',
        ]
        widgets = {
            'ordem': forms.HiddenInput(),
            'quantidade': forms.NumberInput(attrs={'step': '0.0001'}),
            'preco_unitario_material': forms.NumberInput(attrs={'step': '0.0001'}),
            'preco_unitario_mao_obra': forms.NumberInput(attrs={'step': '0.0001'}),
            'preco_unitario_equipamentos': forms.NumberInput(attrs={'step': '0.0001'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('DELETE'):
            return cleaned_data
        for field in [
            'quantidade',
            'preco_unitario_material',
            'preco_unitario_mao_obra',
            'preco_unitario_equipamentos',
        ]:
            cleaned_data[field] = cleaned_data.get(field) or 0
        if cleaned_data.get('tipo') == ItemOrcamentoMedicao.TIPO_GRUPO:
            cleaned_data['unidade'] = ''
            cleaned_data['quantidade'] = 0
            cleaned_data['preco_unitario_material'] = 0
            cleaned_data['preco_unitario_mao_obra'] = 0
            cleaned_data['preco_unitario_equipamentos'] = 0
            return cleaned_data
        if cleaned_data.get('descricao') and not cleaned_data.get('item'):
            self.add_error('item', 'Informe o item.')
        return cleaned_data


class MedicaoConstrutoraForm(BootstrapModelForm):
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
            'desconto_adicional_reduz_base_nf',
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
            'numero': 'Número',
            'periodo_inicio': 'Período início',
            'periodo_fim': 'Período fim',
            'data_medicao': 'Data medição',
            'observacoes': 'Observações',
            'retencao_tecnica': 'Retenção técnica (R$)',
            'retencao_tecnica_percentual': 'Retenção técnica (%)',
            'issqn': 'ISSQN (R$)',
            'issqn_percentual': 'ISSQN (%)',
            'inss': 'INSS (R$)',
            'inss_percentual': 'INSS (%)',
            'desconto_adicional': 'Desconto adicional (R$)',
            'desconto_adicional_percentual': 'Desconto adicional (%)',
            'desconto_adicional_reduz_base_nf': 'Desconto adicional reduz base da NF',
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
    def __init__(self, *args, **kwargs):
        from obras.models import Obra

        self.empresa = kwargs.pop('empresa', None)
        super().__init__(*args, **kwargs)
        self.fields['obra'].queryset = Obra.objects.filter(empresa=self.empresa) if self.empresa else Obra.objects.none()
        self.fields['empreiteiro_cadastro'].queryset = (
            Empreiteiro.objects.filter(empresa=self.empresa, ativo=True).order_by('nome')
            if self.empresa
            else Empreiteiro.objects.none()
        )
        self.fields['empreiteiro_cadastro'].required = True
        self.fields['empreiteiro_cadastro'].empty_label = 'Selecione um empreiteiro cadastrado'
        self.fields['empreiteiro_cadastro'].label_from_instance = (
            lambda empreiteiro: ' - '.join(
                value
                for value in [empreiteiro.nome, empreiteiro.cpf_cnpj, empreiteiro.pix]
                if value
            )
        )
        self.fields['empreiteiro_cadastro'].widget.attrs.update(
            {
                'data-empreiteiro-search': '1',
                'autocomplete': 'off',
            }
        )
        self.fields['empreiteiro'].required = False
        self.fields['empreiteiro'].widget = forms.HiddenInput()
        self.fields['cpf_cnpj'].required = False
        self.fields['cpf_cnpj'].widget.attrs.update({'readonly': 'readonly'})
        self.fields['pix'].required = False
        self.fields['pix'].widget.attrs.update({'readonly': 'readonly'})

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
        cadastro = cleaned_data.get('empreiteiro_cadastro')
        if cadastro:
            cleaned_data['empreiteiro'] = cadastro.nome
            cleaned_data['cpf_cnpj'] = cadastro.cpf_cnpj
            cleaned_data['pix'] = cadastro.pix
        else:
            self.add_error('empreiteiro_cadastro', 'Selecione um empreiteiro cadastrado.')
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.empresa:
            instance.empresa = self.empresa
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    class Meta:
        model = MedicaoEmpreiteiro
        fields = [
            'obra',
            'empreiteiro_cadastro',
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
            'empreiteiro_cadastro': 'Empreiteiro cadastrado',
            'cpf_cnpj': 'CPF/CNPJ',
            'pix': 'PIX',
            'numero': 'Número',
            'periodo_inicio': 'Período início',
            'periodo_fim': 'Período fim',
            'data_medicao': 'Data medição',
            'observacoes': 'Observações',
            'retencao_tecnica': 'Retenção técnica (R$)',
            'retencao_tecnica_percentual': 'Retenção técnica (%)',
            'desconto_adicional': 'Desconto adicional (R$)',
            'desconto_adicional_percentual': 'Desconto adicional (%)',
        }


class MedicaoEmpreiteiroCabecalhoForm(MedicaoEmpreiteiroForm):
    class Meta(MedicaoEmpreiteiroForm.Meta):
        fields = [
            'obra',
            'empreiteiro_cadastro',
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


ItemOrcamentoMedicaoFormSet = inlineformset_factory(
    OrcamentoMedicao,
    ItemOrcamentoMedicao,
    form=ItemOrcamentoMedicaoForm,
    extra=0,
    can_delete=True,
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
    extra=0,
    can_delete=True,
)
