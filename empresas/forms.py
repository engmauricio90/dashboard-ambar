from django import forms

from .models import Empresa


class IdentidadeVisualEmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = [
            'logo',
            'cabecalho_documentos',
            'rodape_documentos',
            'texto_rodape',
            'cor_primaria',
            'cor_secundaria',
            'razao_social',
            'nome_fantasia',
            'cnpj',
            'endereco',
            'cidade',
            'estado',
            'cep',
            'telefone',
            'email',
            'responsavel_tecnico',
            'crea_responsavel',
        ]
        widgets = {
            'texto_rodape': forms.Textarea(attrs={'rows': 3}),
            'cor_primaria': forms.TextInput(attrs={'type': 'color'}),
            'cor_secundaria': forms.TextInput(attrs={'type': 'color'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = 'form-control'
            if isinstance(field.widget, forms.ClearableFileInput):
                css_class = 'form-control'
            field.widget.attrs.setdefault('class', css_class)
