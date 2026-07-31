from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from obras.forms import BootstrapModelForm

from .models import PerfilUsuario


User = get_user_model()


class UsuarioForm(BootstrapModelForm):
    password = forms.CharField(
        label='Senha provisoria',
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Preencha apenas ao criar usuario ou para redefinir a senha.',
    )
    grupos = forms.ModelMultipleChoiceField(
        label='Grupos',
        queryset=Group.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 8}),
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']
        labels = {
            'username': 'Usuario',
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'email': 'E-mail',
            'is_active': 'Ativo',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grupos'].queryset = Group.objects.order_by('name')
        if self.instance and self.instance.pk:
            self.fields['grupos'].initial = self.instance.groups.all()

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        elif not user.pk:
            user.set_unusable_password()
        if commit:
            user.save()
            user.groups.set(self.cleaned_data.get('grupos'))
        return user


class PerfilUsuarioForm(BootstrapModelForm):
    class Meta:
        model = PerfilUsuario
        fields = [
            'telefone',
            'cargo',
            'setor',
            'avatar',
            'obras',
            'dashboard_inicial',
            'itens_por_pagina',
            'observacoes',
        ]
        widgets = {
            'obras': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 10}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'dashboard_inicial': 'Dashboard inicial',
            'itens_por_pagina': 'Itens por pagina',
        }


class MeuPerfilForm(BootstrapModelForm):
    class Meta:
        model = PerfilUsuario
        fields = ['telefone', 'cargo', 'setor', 'avatar', 'dashboard_inicial', 'itens_por_pagina']
        labels = {
            'dashboard_inicial': 'Dashboard inicial',
            'itens_por_pagina': 'Itens por pagina',
        }
