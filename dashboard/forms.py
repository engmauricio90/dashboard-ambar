from django import forms

from obras.models import Obra


class DashboardFiltroForm(forms.Form):
    ORDENACAO_CHOICES = [
        ('resultado_real_desc', 'Resultado real: maior para menor'),
        ('resultado_real_asc', 'Resultado real: menor para maior'),
        ('nome_asc', 'Obra: A-Z'),
        ('nome_desc', 'Obra: Z-A'),
        ('contrato_desc', 'Contrato: maior para menor'),
        ('contrato_asc', 'Contrato: menor para maior'),
        ('faturado_desc', 'Faturado: maior para menor'),
        ('faturado_asc', 'Faturado: menor para maior'),
    ]

    busca = forms.CharField(required=False)
    cliente = forms.CharField(required=False)
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'Todos'), *Obra.STATUS_CHOICES],
    )
    ordenacao = forms.ChoiceField(
        required=False,
        choices=ORDENACAO_CHOICES,
        initial='resultado_real_desc',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                css_class = 'form-select'
            else:
                css_class = 'form-control'

            existing = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{existing} {css_class}'.strip()
