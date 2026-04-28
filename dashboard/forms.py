from django import forms

from obras.models import Obra


class DashboardFiltroForm(forms.Form):
    busca = forms.CharField(required=False)
    cliente = forms.CharField(required=False)
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'Todos'), *Obra.STATUS_CHOICES],
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
