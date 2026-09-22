from django import forms
from django.contrib.auth import get_user_model

from empresas.models import Empresa

from .models import Assinatura, CheckoutIntent
from .services.comercial import PERIODICIDADE_CONFIG


class PrepararContratacaoForm(forms.Form):
    empresa = forms.ModelChoiceField(
        queryset=Empresa.objects.none(),
        label='Empresa cliente',
        help_text='Selecione uma empresa ja criada no onboarding assistido.',
    )
    periodicidade = forms.ChoiceField(choices=Assinatura.Periodicidade.choices, label='Periodicidade')

    def __init__(self, *args, initial_periodicidade=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['empresa'].queryset = Empresa.objects.filter(ativa=True).order_by('nome')
        self.fields['empresa'].widget.attrs.update({'class': 'form-select'})
        self.fields['periodicidade'].widget.attrs.update({'class': 'form-select'})
        if initial_periodicidade:
            self.fields['periodicidade'].initial = initial_periodicidade

    def resumo_periodicidade(self):
        periodicidade = self['periodicidade'].value() or self.fields['periodicidade'].initial or Assinatura.Periodicidade.ANUAL
        config = PERIODICIDADE_CONFIG.get(periodicidade, PERIODICIDADE_CONFIG[Assinatura.Periodicidade.ANUAL])
        return {
            'periodicidade': periodicidade,
            'valor': config['valor'],
            'meses': config['meses'],
            'rotulo': config['rotulo'],
        }


class AssinaturaFiltroForm(forms.Form):
    status = forms.ChoiceField(required=False, choices=[('', 'Todos os status'), *Assinatura.Status.choices])
    periodicidade = forms.ChoiceField(required=False, choices=[('', 'Todas as periodicidades'), *Assinatura.Periodicidade.choices])
    busca = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        self.fields['periodicidade'].widget.attrs.update({'class': 'form-select'})
        self.fields['busca'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Buscar por empresa'})


class CheckoutIntentForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    consentimento = forms.BooleanField(required=True)

    class Meta:
        model = CheckoutIntent
        fields = [
            'nome_responsavel', 'nome_empresa', 'email', 'telefone', 'periodicidade',
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
            'gclid', 'fbclid',
        ]
        widgets = {
            'utm_source': forms.HiddenInput(),
            'utm_medium': forms.HiddenInput(),
            'utm_campaign': forms.HiddenInput(),
            'utm_content': forms.HiddenInput(),
            'utm_term': forms.HiddenInput(),
            'gclid': forms.HiddenInput(),
            'fbclid': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {
            'nome_responsavel': 'Nome do responsável',
            'nome_empresa': 'Nome da empresa',
            'email': 'E-mail',
            'telefone': 'WhatsApp',
            'periodicidade': 'Periodicidade',
        }
        for name, label in labels.items():
            self.fields[name].label = label
        for name in ('nome_responsavel', 'nome_empresa', 'email', 'telefone', 'periodicidade'):
            self.fields[name].widget.attrs['class'] = 'form-control' if name != 'periodicidade' else 'form-select'
        self.fields['email'].widget.attrs['autocomplete'] = 'email'
        self.fields['telefone'].widget.attrs['autocomplete'] = 'tel'

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Já existe uma conta para este e-mail. Entre na plataforma ou fale com nosso time.')
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('website'):
            raise forms.ValidationError('Não foi possível processar a solicitação.')
        return cleaned


class CheckoutIntentFiltroForm(forms.Form):
    status = forms.ChoiceField(required=False, choices=[('', 'Todos os status'), *CheckoutIntent.Status.choices])
    periodicidade = forms.ChoiceField(required=False, choices=[('', 'Todas as periodicidades'), *Assinatura.Periodicidade.choices])
    data_inicio = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    data_fim = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    utm_source = forms.CharField(required=False)
    busca = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-select' if isinstance(field.widget, forms.Select) else 'form-control')
