from django import forms
from django.forms import inlineformset_factory

from .models import Proposta, PropostaPlanilhaItem, PropostaResumoItem


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

            if is_new_unbound_form and isinstance(field, (forms.DecimalField, forms.IntegerField)):
                if getattr(self.instance, name, None) == 0:
                    setattr(self.instance, name, None)
                if field.initial == 0:
                    field.initial = None
                if self.initial.get(name) in (0, 0.0, '0'):
                    self.initial[name] = ''
                field.widget.attrs.setdefault('placeholder', '0,00')


class PropostaForm(BootstrapModelForm):
    def clean_servico_incluso(self):
        servico = (self.cleaned_data.get('servico_incluso') or '').strip()
        limite = 1500
        if len(servico) > limite:
            raise forms.ValidationError(
                f'O texto de servico incluso pode ter no maximo {limite} caracteres para preservar a formatacao da proposta.'
            )
        return servico

    class Meta:
        model = Proposta
        fields = [
            'cliente',
            'tipo_execucao',
            'data_proposta',
            'servico_incluso',
            'prazo_execucao',
            'forma_pagamento',
            'observacoes',
            'incluir_planilha',
            'planilha_imagem',
            'bdi_percentual',
            'local_fechamento',
            'data_encerramento',
            'engenheiro_nome',
            'engenheiro_crea',
            'situacao',
        ]
        widgets = {
            'data_proposta': forms.DateInput(attrs={'type': 'date'}),
            'servico_incluso': forms.Textarea(attrs={'rows': 5}),
            'forma_pagamento': forms.Textarea(attrs={'rows': 4}),
            'observacoes': forms.Textarea(attrs={'rows': 6}),
            'data_encerramento': forms.DateInput(attrs={'type': 'date'}),
            'bdi_percentual': forms.NumberInput(attrs={'step': '0.01'}),
        }


class PropostaResumoItemForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

    class Meta:
        model = PropostaResumoItem
        fields = ['ordem', 'descricao', 'quantidade_descricao', 'valor']
        widgets = {
            'ordem': forms.NumberInput(attrs={'min': '1'}),
            'descricao': forms.Textarea(attrs={'rows': 2}),
            'valor': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': '0,00'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        descricao = cleaned_data.get('descricao')
        quantidade = cleaned_data.get('quantidade_descricao')
        valor = cleaned_data.get('valor')

        if descricao or quantidade or valor is not None:
            if not descricao:
                self.add_error('descricao', 'Informe a descricao.')
            if not quantidade:
                self.add_error('quantidade_descricao', 'Informe a quantidade.')
            if valor in (None, ''):
                self.add_error('valor', 'Informe o valor.')

        return cleaned_data


class PropostaPlanilhaItemForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

    class Meta:
        model = PropostaPlanilhaItem
        fields = [
            'ordem',
            'descricao',
            'unidade',
            'quantidade',
            'preco_unit_material',
            'preco_unit_mao_obra',
        ]
        widgets = {
            'ordem': forms.NumberInput(attrs={'min': '1'}),
            'descricao': forms.Textarea(attrs={'rows': 2}),
            'quantidade': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': '0,00'}),
            'preco_unit_material': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': '0,00'}),
            'preco_unit_mao_obra': forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': '0,00'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        descricao = cleaned_data.get('descricao')
        unidade = cleaned_data.get('unidade')
        quantidade = cleaned_data.get('quantidade')
        preco_material = cleaned_data.get('preco_unit_material')
        preco_mao = cleaned_data.get('preco_unit_mao_obra')

        if descricao or unidade or quantidade is not None or preco_material is not None or preco_mao is not None:
            if not descricao:
                self.add_error('descricao', 'Informe a descricao.')
            if not unidade:
                self.add_error('unidade', 'Informe a unidade.')
            if quantidade in (None, ''):
                self.add_error('quantidade', 'Informe a quantidade.')

        return cleaned_data


PropostaResumoItemFormSet = inlineformset_factory(
    Proposta,
    PropostaResumoItem,
    form=PropostaResumoItemForm,
    extra=2,
    can_delete=True,
)


PropostaPlanilhaItemFormSet = inlineformset_factory(
    Proposta,
    PropostaPlanilhaItem,
    form=PropostaPlanilhaItemForm,
    extra=3,
    can_delete=True,
)
