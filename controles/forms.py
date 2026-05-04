from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from .models import (
    ApontamentoMaquinaLocacao,
    BombonaCombustivel,
    ContratoConcretagem,
    EquipamentoLocadoCatalogo,
    FornecedorMaquinaLocacao,
    FaturamentoConcretagem,
    MaquinaLocacaoCatalogo,
    NotaFiscalCombustivel,
    NotaFiscalLocacaoMaquina,
    LocacaoEquipamento,
    LocadoraEquipamento,
    OrcamentoRadarObra,
    OrdemCompraCombustivel,
    OrdemCompraGeral,
    OrdemServicoLocacaoMaquina,
    ItemOrdemCompraGeral,
    RegistroAbastecimento,
    SolicitanteConcretagem,
    VeiculoMaquina,
)


class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_new_unbound_form = not self.is_bound and not getattr(self.instance, 'pk', None)

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = 'form-check-input'
            elif isinstance(field.widget, forms.Select):
                css_class = 'form-select'
            elif isinstance(field.widget, forms.Textarea):
                css_class = 'form-control'
            else:
                css_class = 'form-control'

            existing = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{existing} {css_class}'.strip()

            if isinstance(field.widget, forms.DateInput) and field.widget.attrs.get('type') == 'date':
                field.widget.format = '%Y-%m-%d'
                field.input_formats = ['%Y-%m-%d']
                initial_value = self.initial.get(name) or getattr(self.instance, name, None)
                if initial_value:
                    self.initial[name] = initial_value.strftime('%Y-%m-%d')

            if is_new_unbound_form and isinstance(field, (forms.DecimalField, forms.IntegerField)):
                if getattr(self.instance, name, None) == 0:
                    setattr(self.instance, name, None)
                if field.initial == 0:
                    field.initial = None
                if self.initial.get(name) in (0, 0.0, '0'):
                    self.initial[name] = ''
                field.widget.attrs.setdefault('placeholder', '0,00')


class VeiculoMaquinaForm(BootstrapModelForm):
    class Meta:
        model = VeiculoMaquina
        fields = ['placa', 'descricao', 'tipo', 'status', 'observacoes']
        widgets = {
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class RegistroAbastecimentoForm(BootstrapModelForm):
    class Meta:
        model = RegistroAbastecimento
        fields = [
            'data_abastecimento',
            'veiculo',
            'posto',
            'responsavel',
            'litros',
            'valor_litro',
            'valor_total',
            'observacoes',
        ]
        widgets = {
            'data_abastecimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'litros': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_litro': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_total': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class BombonaCombustivelForm(BootstrapModelForm):
    class Meta:
        model = BombonaCombustivel
        fields = ['identificacao', 'capacidade_litros', 'localizacao', 'status', 'observacoes']
        widgets = {
            'capacidade_litros': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class OrdemCompraCombustivelForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fornecedor'].required = False
        self.fields['valor_total_previsto'].required = False

    class Meta:
        model = OrdemCompraCombustivel
        fields = [
            'numero',
            'data_ordem',
            'fornecedor_cadastro',
            'fornecedor',
            'solicitante',
            'tipo_combustivel',
            'tipo_destino',
            'veiculo',
            'bombona',
            'quantidade_litros',
            'valor_litro_previsto',
            'valor_total_previsto',
            'status',
            'observacoes',
        ]
        widgets = {
            'data_ordem': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'quantidade_litros': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_litro_previsto': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_total_previsto': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'numero': 'Deixe em branco para gerar automaticamente.',
        }

    def clean(self):
        cleaned_data = super().clean()
        tipo_destino = cleaned_data.get('tipo_destino')
        veiculo = cleaned_data.get('veiculo')
        bombona = cleaned_data.get('bombona')
        fornecedor = cleaned_data.get('fornecedor')
        fornecedor_cadastro = cleaned_data.get('fornecedor_cadastro')

        if not fornecedor and not fornecedor_cadastro:
            self.add_error('fornecedor_cadastro', 'Informe um fornecedor do cadastro central ou digite o fornecedor/posto.')

        if tipo_destino == OrdemCompraCombustivel.DESTINO_VEICULO:
            if not veiculo:
                self.add_error('veiculo', 'Informe o veiculo/maquina da ordem.')
            cleaned_data['bombona'] = None
        elif tipo_destino == OrdemCompraCombustivel.DESTINO_BOMBONA:
            if not bombona:
                self.add_error('bombona', 'Informe a bombona da ordem.')
            cleaned_data['veiculo'] = None

        return cleaned_data


class NotaFiscalCombustivelForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['valor_total'].required = False

    class Meta:
        model = NotaFiscalCombustivel
        fields = ['numero', 'data_emissao', 'litros', 'valor_litro', 'valor_total', 'status', 'observacoes']
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'litros': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_litro': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_total': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class OrdemCompraGeralForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fornecedor'].required = False

    class Meta:
        model = OrdemCompraGeral
        fields = [
            'numero',
            'data_emissao',
            'status',
            'comprador',
            'empresa_razao_social',
            'empresa_cnpj',
            'empresa_endereco',
            'fornecedor',
            'fornecedor_cadastro',
            'fornecedor_cpf_cnpj',
            'fornecedor_endereco',
            'fornecedor_bairro',
            'fornecedor_cidade',
            'fornecedor_uf',
            'fornecedor_cep',
            'fornecedor_fone',
            'fornecedor_ie',
            'observacoes',
        ]
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'numero': 'Deixe em branco para gerar automaticamente no formato 001/2026.',
        }

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('fornecedor') and not cleaned_data.get('fornecedor_cadastro'):
            self.add_error('fornecedor_cadastro', 'Informe um fornecedor do cadastro central ou digite o fornecedor.')
        return cleaned_data


class ItemOrdemCompraGeralForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['valor_total'].required = False

    def has_changed(self):
        if self.data and self.prefix and not self.data.get(f'{self.prefix}-id'):
            relevant_fields = ['descricao', 'quantidade', 'valor_unitario', 'valor_total', 'data_entrega']
            if not any((self.data.get(f'{self.prefix}-{field}') or '').strip() for field in relevant_fields):
                return False
        return super().has_changed()

    class Meta:
        model = ItemOrdemCompraGeral
        fields = ['item', 'descricao', 'quantidade', 'unidade', 'valor_unitario', 'valor_total', 'data_entrega']
        widgets = {
            'quantidade': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_unitario': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_total': forms.NumberInput(attrs={'step': '0.01'}),
            'data_entrega': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }


ItemOrdemCompraGeralFormSet = inlineformset_factory(
    OrdemCompraGeral,
    ItemOrdemCompraGeral,
    form=ItemOrdemCompraGeralForm,
    extra=5,
    can_delete=True,
)


class EquipamentoLocadoCatalogoForm(BootstrapModelForm):
    class Meta:
        model = EquipamentoLocadoCatalogo
        fields = ['nome', 'categoria', 'status', 'observacoes']
        widgets = {
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class LocadoraEquipamentoForm(BootstrapModelForm):
    class Meta:
        model = LocadoraEquipamento
        fields = ['nome', 'contato', 'telefone', 'email', 'observacoes']
        widgets = {
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class LocacaoEquipamentoForm(BootstrapModelForm):
    class Meta:
        model = LocacaoEquipamento
        fields = [
            'data_locacao',
            'solicitante',
            'equipamento',
            'locadora',
            'obra',
            'status',
            'numero_contrato',
            'quantidade',
            'data_solicitacao_retirada',
            'data_retirada',
            'prazo',
            'valor_referencia',
            'observacoes',
        ]
        widgets = {
            'data_locacao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_solicitacao_retirada': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_retirada': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'quantidade': forms.NumberInput(attrs={'min': '1'}),
            'valor_referencia': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class SolicitarRetiradaEquipamentoForm(BootstrapModelForm):
    class Meta:
        model = LocacaoEquipamento
        fields = ['data_solicitacao_retirada', 'observacoes']
        widgets = {
            'data_solicitacao_retirada': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class BaixarLocacaoEquipamentoForm(BootstrapModelForm):
    class Meta:
        model = LocacaoEquipamento
        fields = ['data_retirada', 'observacoes']
        widgets = {
            'data_retirada': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class MaquinaLocacaoCatalogoForm(BootstrapModelForm):
    class Meta:
        model = MaquinaLocacaoCatalogo
        fields = ['nome', 'categoria', 'status', 'observacoes']
        widgets = {
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class FornecedorMaquinaLocacaoForm(BootstrapModelForm):
    class Meta:
        model = FornecedorMaquinaLocacao
        fields = ['nome', 'contato', 'telefone', 'email', 'observacoes']
        widgets = {
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class OrdemServicoLocacaoMaquinaForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in [
            'valor_hora',
            'valor_diaria',
            'valor_mensal',
            'franquia_horas',
            'valor_mobilizacao',
            'valor_desmobilizacao',
            'valor_previsto_manual',
        ]:
            self.fields[field_name].required = False
        self.fields['fornecedor'].required = False

    class Meta:
        model = OrdemServicoLocacaoMaquina
        fields = [
            'numero',
            'data_solicitacao',
            'obra',
            'fornecedor_cadastro',
            'fornecedor',
            'maquina',
            'solicitante',
            'responsavel',
            'status',
            'tipo_cobranca',
            'data_prevista_inicio',
            'data_prevista_fim',
            'data_mobilizacao',
            'data_inicio_operacao',
            'data_solicitacao_desmobilizacao',
            'data_desmobilizacao',
            'valor_hora',
            'valor_diaria',
            'valor_mensal',
            'franquia_horas',
            'valor_mobilizacao',
            'valor_desmobilizacao',
            'valor_previsto_manual',
            'operador_incluso',
            'combustivel_incluso',
            'observacoes',
        ]
        widgets = {
            'data_solicitacao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_prevista_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_prevista_fim': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_mobilizacao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_inicio_operacao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_solicitacao_desmobilizacao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_desmobilizacao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor_hora': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_diaria': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_mensal': forms.NumberInput(attrs={'step': '0.01'}),
            'franquia_horas': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_mobilizacao': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_desmobilizacao': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_previsto_manual': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'numero': 'Deixe em branco para gerar automaticamente.',
            'valor_previsto_manual': 'Use quando a cobranca nao for por hora ou precisar travar um valor fechado.',
        }

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('fornecedor') and not cleaned_data.get('fornecedor_cadastro'):
            self.add_error('fornecedor_cadastro', 'Informe um fornecedor do cadastro central ou selecione um fornecedor de maquina.')
        return cleaned_data


class ApontamentoMaquinaLocacaoForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['horas_trabalhadas'].required = False
        self.fields['horas_paradas'].required = False

    class Meta:
        model = ApontamentoMaquinaLocacao
        fields = [
            'data',
            'horimetro_inicial',
            'horimetro_final',
            'horas_trabalhadas',
            'horas_paradas',
            'motivo_parada',
            'operador',
            'responsavel_apontamento',
            'observacoes',
        ]
        widgets = {
            'data': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'horimetro_inicial': forms.NumberInput(attrs={'step': '0.01'}),
            'horimetro_final': forms.NumberInput(attrs={'step': '0.01'}),
            'horas_trabalhadas': forms.NumberInput(attrs={'step': '0.01'}),
            'horas_paradas': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class NotaFiscalLocacaoMaquinaForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['valor_total'].required = False

    class Meta:
        model = NotaFiscalLocacaoMaquina
        fields = [
            'numero',
            'data_emissao',
            'periodo_inicio',
            'periodo_fim',
            'horas_faturadas',
            'valor_maquina',
            'valor_mobilizacao',
            'valor_desmobilizacao',
            'valor_total',
            'status',
            'observacoes',
        ]
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'periodo_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'periodo_fim': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'horas_faturadas': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_maquina': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_mobilizacao': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_desmobilizacao': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_total': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class OrcamentoRadarObraForm(BootstrapModelForm):
    class Meta:
        model = OrcamentoRadarObra
        fields = [
            'numero',
            'cliente',
            'descricao',
            'data_orcamento',
            'situacao',
            'valor_estimado',
            'responsavel',
            'observacoes',
        ]
        widgets = {
            'data_orcamento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor_estimado': forms.NumberInput(attrs={'step': '0.01'}),
            'descricao': forms.Textarea(attrs={'rows': 3}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class ContratoConcretagemForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fornecedor'].required = False

    class Meta:
        model = ContratoConcretagem
        fields = [
            'obra',
            'numero_contrato',
            'fornecedor_cadastro',
            'fornecedor',
            'descricao',
            'data_inicio',
            'status',
            'custo_m3_concreto',
            'custo_bomba',
            'adicional_noturno',
            'adicional_sabado',
            'adicional_m3_faltante',
            'volume_minimo_m3',
            'observacoes',
        ]
        widgets = {
            'data_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'custo_m3_concreto': forms.NumberInput(attrs={'step': '0.01'}),
            'custo_bomba': forms.NumberInput(attrs={'step': '0.01'}),
            'adicional_noturno': forms.NumberInput(attrs={'step': '0.01'}),
            'adicional_sabado': forms.NumberInput(attrs={'step': '0.01'}),
            'adicional_m3_faltante': forms.NumberInput(attrs={'step': '0.01'}),
            'volume_minimo_m3': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('fornecedor') and not cleaned_data.get('fornecedor_cadastro'):
            self.add_error('fornecedor_cadastro', 'Informe um fornecedor do cadastro central ou digite o fornecedor.')
        return cleaned_data


class SolicitanteConcretagemForm(BootstrapModelForm):
    class Meta:
        model = SolicitanteConcretagem
        fields = ['nome', 'ativo', 'observacoes']
        widgets = {
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class FaturamentoConcretagemForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = SolicitanteConcretagem.objects.filter(ativo=True)
        if self.instance and self.instance.solicitante_id:
            queryset = SolicitanteConcretagem.objects.filter(
                Q(ativo=True) | Q(id=self.instance.solicitante_id),
            )
        self.fields['solicitante'].queryset = queryset

    class Meta:
        model = FaturamentoConcretagem
        fields = [
            'data_faturamento',
            'solicitante',
            'status',
            'numero_documento',
            'data_conferencia',
            'volume_m3',
            'fck_traco',
            'tipo_bomba',
            'usou_bomba',
            'adicional_noturno_aplicado',
            'adicional_sabado_aplicado',
            'volume_faltante_m3',
            'valor_previsto_manual',
            'valor_cobrado',
            'observacoes',
        ]
        widgets = {
            'data_faturamento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_conferencia': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'volume_m3': forms.NumberInput(attrs={'step': '0.01'}),
            'volume_faltante_m3': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_previsto_manual': forms.NumberInput(attrs={'step': '0.01'}),
            'valor_cobrado': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
