from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import Group
from django.conf import settings
from django.core.exceptions import ValidationError
from urllib.parse import urlparse

from obras.forms import BootstrapModelForm

from .models import PerfilUsuario


User = get_user_model()
MAX_AVATAR_SIZE = 5 * 1024 * 1024


class PlataformaPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label='E-mail',
        max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'class': 'form-control'}),
    )

    def get_users(self, email):
        usuarios = [
            user
            for user in User._default_manager.filter(email__iexact=email, is_active=True)
            if user.has_usable_password() and user.email.lower() == email.lower()
        ]
        if len(usuarios) != 1:
            return []
        return usuarios

    def save(self, *args, **kwargs):
        extra_context = kwargs.pop('extra_email_context', None) or {}
        extra_context.setdefault('platform_name', settings.PLATFORM_NAME)
        extra_context.setdefault('support_email', settings.PLATFORM_SUPPORT_EMAIL)

        if settings.PLATFORM_BASE_URL:
            parsed = urlparse(settings.PLATFORM_BASE_URL)
            if parsed.netloc:
                kwargs['domain_override'] = parsed.netloc
                kwargs['use_https'] = parsed.scheme == 'https'

        kwargs['extra_email_context'] = extra_context
        return super().save(*args, **kwargs)


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

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar and getattr(avatar, 'size', 0) > MAX_AVATAR_SIZE:
            raise ValidationError('Envie uma imagem com no maximo 5 MB.')
        return avatar


class MeuPerfilForm(BootstrapModelForm):
    class Meta:
        model = PerfilUsuario
        fields = ['telefone', 'cargo', 'setor', 'avatar', 'dashboard_inicial', 'itens_por_pagina']
        labels = {
            'dashboard_inicial': 'Dashboard inicial',
            'itens_por_pagina': 'Itens por pagina',
        }

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar and getattr(avatar, 'size', 0) > MAX_AVATAR_SIZE:
            raise ValidationError('Envie uma imagem com no maximo 5 MB.')
        return avatar
