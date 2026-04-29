from django import forms
from django.forms import inlineformset_factory

from .models import (
    AditivoContrato,
    DespesaObra,
    ImpostoNotaFiscal,
    NotaFiscal,
    Obra,
    RetencaoTecnicaObra,
    RetencaoNotaFiscal,
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


class BootstrapForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = 'form-check-input'
            elif isinstance(field.widget, forms.Select):
                css_class = 'form-select'
            else:
                css_class = 'form-control'

            existing = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{existing} {css_class}'.strip()


class ObraForm(BootstrapModelForm):
    class Meta:
        model = Obra
        fields = [
            'nome_obra',
            'cliente',
            'status_obra',
            'responsavel',
            'data_inicio',
            'observacoes',
            'valor_contrato',
            'projecao_despesa',
        ]
        widgets = {
            'data_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
            'valor_contrato': forms.NumberInput(attrs={'step': '0.01'}),
            'projecao_despesa': forms.NumberInput(attrs={'step': '0.01'}),
        }


class NotaFiscalForm(BootstrapModelForm):
    class Meta:
        model = NotaFiscal
        fields = ['numero', 'data_emissao', 'valor_bruto', 'status', 'observacoes']
        widgets = {
            'data_emissao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor_bruto': forms.NumberInput(attrs={'step': '0.01'}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }


class RetencaoNotaFiscalForm(BootstrapModelForm):
    class Meta:
        model = RetencaoNotaFiscal
        fields = ['tipo', 'descricao', 'valor']
        widgets = {
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
        }


class RetencaoNotaFiscalInlineForm(RetencaoNotaFiscalForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get('tipo')
        descricao = cleaned_data.get('descricao')
        valor = cleaned_data.get('valor')

        if tipo or descricao or valor is not None:
            if not tipo:
                self.add_error('tipo', 'Informe o tipo da retencao.')
            if valor in (None, ''):
                self.add_error('valor', 'Informe o valor da retencao.')

        return cleaned_data


class ImpostoNotaFiscalForm(BootstrapModelForm):
    class Meta:
        model = ImpostoNotaFiscal
        fields = ['tipo', 'descricao', 'valor']
        widgets = {
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
        }


class ImpostoNotaFiscalInlineForm(ImpostoNotaFiscalForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get('tipo')
        descricao = cleaned_data.get('descricao')
        valor = cleaned_data.get('valor')

        if tipo or descricao or valor is not None:
            if not tipo:
                self.add_error('tipo', 'Informe o tipo do imposto.')
            if valor in (None, ''):
                self.add_error('valor', 'Informe o valor do imposto.')

        return cleaned_data


class DespesaObraForm(BootstrapModelForm):
    class Meta:
        model = DespesaObra
        fields = ['data_referencia', 'categoria', 'descricao', 'valor']
        widgets = {
            'data_referencia': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
        }


class AditivoContratoForm(BootstrapModelForm):
    class Meta:
        model = AditivoContrato
        fields = ['data_referencia', 'tipo', 'descricao', 'valor']
        widgets = {
            'data_referencia': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
        }


class RetencaoTecnicaObraForm(BootstrapModelForm):
    class Meta:
        model = RetencaoTecnicaObra
        fields = ['tipo', 'data_referencia', 'descricao', 'valor', 'data_prevista_devolucao', 'data_devolucao']
        widgets = {
            'data_referencia': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_prevista_devolucao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'data_devolucao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valor': forms.NumberInput(attrs={'step': '0.01'}),
        }


class RelatorioObraFiltroForm(BootstrapForm):
    data_inicial = forms.DateField(required=False, widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    data_final = forms.DateField(required=False, widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))

    def clean(self):
        cleaned_data = super().clean()
        data_inicial = cleaned_data.get('data_inicial')
        data_final = cleaned_data.get('data_final')

        if data_inicial and data_final and data_inicial > data_final:
            raise forms.ValidationError('A data inicial nao pode ser maior que a data final.')

        return cleaned_data


RetencaoNotaFiscalFormSet = inlineformset_factory(
    NotaFiscal,
    RetencaoNotaFiscal,
    form=RetencaoNotaFiscalInlineForm,
    extra=2,
    can_delete=True,
)


ImpostoNotaFiscalFormSet = inlineformset_factory(
    NotaFiscal,
    ImpostoNotaFiscal,
    form=ImpostoNotaFiscalInlineForm,
    extra=2,
    can_delete=True,
)
