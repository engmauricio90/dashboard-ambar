from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import SocialBaseImage, SocialContent, SocialProfile, validate_horarios_publicacao


class BootstrapMixin:
    def _apply_bootstrap(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault('class', 'form-control')
            else:
                widget.attrs.setdefault('class', 'form-control')


class SocialProfileForm(BootstrapMixin, forms.ModelForm):
    horarios_texto = forms.CharField(
        label='Horarios de publicacao',
        required=False,
        help_text='Use um horario por linha ou separado por virgula. Ex.: 12:00, 19:30',
        widget=forms.Textarea(attrs={'rows': 2}),
    )

    class Meta:
        model = SocialProfile
        fields = [
            'nome',
            'username',
            'plataforma',
            'ativo',
            'timezone',
            'modo_operacao',
            'posts_por_dia',
            'estilo',
            'instrucoes_ia',
            'responder_comentarios',
            'limite_respostas',
        ]
        widgets = {
            'estilo': forms.Textarea(attrs={'rows': 3}),
            'instrucoes_ia': forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['timezone'].widget = forms.Select(
            choices=[(tz, tz) for tz in sorted(available_timezones())],
            attrs={'class': 'form-select'},
        )
        if self.instance and self.instance.pk:
            self.fields['horarios_texto'].initial = '\n'.join(self.instance.horarios_publicacao or [])
        else:
            self.fields['horarios_texto'].initial = '12:00\n19:30'
        self._apply_bootstrap()
        self.fields['plataforma'].widget.attrs['class'] = 'form-select'
        self.fields['modo_operacao'].widget.attrs['class'] = 'form-select'
        self.fields['timezone'].widget.attrs['class'] = 'form-select'

    def clean_horarios_texto(self):
        raw = self.cleaned_data.get('horarios_texto') or ''
        horarios = [item.strip() for bloco in raw.splitlines() for item in bloco.split(',') if item.strip()]
        try:
            validate_horarios_publicacao(horarios)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return horarios

    def clean_posts_por_dia(self):
        valor = self.cleaned_data['posts_por_dia']
        if valor < 1:
            raise forms.ValidationError('Informe pelo menos 1 post por dia.')
        return valor

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.horarios_publicacao = self.cleaned_data['horarios_texto']
        if commit:
            instance.save()
        return instance


class SocialBaseImageForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SocialBaseImage
        fields = ['arquivo', 'nome', 'tags', 'ativa']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


class SocialContentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SocialContent
        fields = ['profile', 'base_image', 'frase', 'legenda', 'hashtags']
        widgets = {
            'frase': forms.Textarea(attrs={'rows': 3}),
            'legenda': forms.Textarea(attrs={'rows': 4}),
            'hashtags': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile_context = profile
        if profile:
            self.fields['profile'].initial = profile
            self.fields['profile'].queryset = SocialProfile.objects.filter(pk=profile.pk)
            self.fields['profile'].widget = forms.HiddenInput()
            self.fields['base_image'].queryset = SocialBaseImage.objects.filter(profile=profile, ativa=True)
        else:
            self.fields['profile'].queryset = SocialProfile.objects.order_by('nome')
            self.fields['base_image'].queryset = SocialBaseImage.objects.filter(ativa=True).select_related('profile')
        self._apply_bootstrap()
        if not isinstance(self.fields['profile'].widget, forms.HiddenInput):
            self.fields['profile'].widget.attrs['class'] = 'form-select'
        self.fields['base_image'].widget.attrs['class'] = 'form-select'

    def clean(self):
        cleaned = super().clean()
        profile = cleaned.get('profile')
        base_image = cleaned.get('base_image')
        if base_image and profile and base_image.profile_id != profile.id:
            raise forms.ValidationError('A imagem-base precisa pertencer ao perfil selecionado.')
        return cleaned


class SocialScheduleForm(BootstrapMixin, forms.Form):
    data = forms.DateField(label='Data', widget=forms.DateInput(attrs={'type': 'date'}))
    hora = forms.TimeField(label='Hora', widget=forms.TimeInput(attrs={'type': 'time'}))

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        data = cleaned.get('data')
        hora = cleaned.get('hora')
        if not data or not hora:
            return cleaned
        try:
            zone = ZoneInfo(self.profile.timezone)
        except ZoneInfoNotFoundError as exc:
            raise forms.ValidationError('Timezone do perfil invalido.') from exc
        scheduled_at = datetime.combine(data, hora, tzinfo=zone)
        scheduled_at = scheduled_at.astimezone(timezone.get_current_timezone())
        if scheduled_at <= timezone.now():
            raise forms.ValidationError('Informe uma data e hora futura.')
        cleaned['scheduled_at'] = scheduled_at
        return cleaned
