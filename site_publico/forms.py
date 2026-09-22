import re

from django import forms
from django.utils import timezone

from .models import PublicLead


ACQUISITION_FIELDS = (
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_term',
    'gclid',
    'fbclid',
    'landing_path',
    'billing_preference',
)


def normalize_phone(value):
    digits = re.sub(r'\D+', '', value or '')
    if len(digits) in {10, 11}:
        return f'55{digits}'
    return digits[:20]


class PublicLeadForm(forms.ModelForm):
    consentimento = forms.BooleanField(required=True)
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = PublicLead
        fields = [
            'nome',
            'empresa',
            'telefone',
            'email',
            'quantidade_obras',
            'cargo_funcao',
            'como_controla_hoje',
            'principal_dificuldade',
            'mensagem',
            *ACQUISITION_FIELDS,
        ]
        widgets = {
            'mensagem': forms.Textarea(attrs={'rows': 4}),
            **{field: forms.HiddenInput for field in ACQUISITION_FIELDS},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            'nome': 'Seu nome',
            'empresa': 'Nome da construtora ou empreiteira',
            'telefone': '(00) 00000-0000',
            'email': 'voce@empresa.com.br',
            'quantidade_obras': 'Ex.: 3',
            'cargo_funcao': 'Diretoria, engenharia, financeiro...',
            'mensagem': 'Conte rapidamente o que voc\u00ea quer organizar',
        }
        for name, field in self.fields.items():
            if name in {'consentimento', 'website', *ACQUISITION_FIELDS}:
                continue
            field.widget.attrs.setdefault('placeholder', placeholders.get(name, ''))

    def clean_website(self):
        value = self.cleaned_data.get('website', '')
        if value:
            raise forms.ValidationError('Campo inv\u00e1lido.')
        return value

    def clean_quantidade_obras(self):
        value = self.cleaned_data.get('quantidade_obras')
        if value is not None and value > 10000:
            raise forms.ValidationError('Informe uma quantidade v\u00e1lida de obras.')
        return value

    def save(self, commit=True):
        lead = super().save(commit=False)
        lead.telefone_normalizado = normalize_phone(lead.telefone)
        lead.consent_at = timezone.now()
        if commit:
            lead.save()
        return lead


class PublicLeadStatusForm(forms.ModelForm):
    class Meta:
        model = PublicLead
        fields = ['status', 'observacao_comercial']
        widgets = {
            'observacao_comercial': forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        self.fields['observacao_comercial'].widget.attrs.update({'class': 'form-control'})
