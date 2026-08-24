from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django import forms
from django.conf import settings
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
    PRESET_BOXES = {
        SocialBaseImage.TextBoxPreset.TOP_LEFT: (7, 8, 43, 32),
        SocialBaseImage.TextBoxPreset.TOP_RIGHT: (50, 8, 43, 32),
        SocialBaseImage.TextBoxPreset.MIDDLE_LEFT: (7, 34, 43, 32),
        SocialBaseImage.TextBoxPreset.MIDDLE_RIGHT: (50, 34, 43, 32),
        SocialBaseImage.TextBoxPreset.BOTTOM_LEFT: (7, 60, 43, 32),
        SocialBaseImage.TextBoxPreset.BOTTOM_RIGHT: (50, 60, 43, 32),
    }

    class Meta:
        model = SocialBaseImage
        fields = [
            'arquivo',
            'nome',
            'tags',
            'text_position',
            'text_box_preset',
            'primary_text_box_x',
            'primary_text_box_y',
            'primary_text_box_width',
            'primary_text_box_height',
            'text_align_horizontal',
            'text_align_vertical',
            'secondary_text_box_x',
            'secondary_text_box_y',
            'secondary_text_box_width',
            'secondary_text_box_height',
            'secondary_text_align_horizontal',
            'secondary_text_align_vertical',
            'ativa',
        ]
        labels = {
            'text_position': 'Posicao preferencial do texto',
            'text_box_preset': 'Preset da caixa principal',
            'primary_text_box_x': 'X principal (%)',
            'primary_text_box_y': 'Y principal (%)',
            'primary_text_box_width': 'Largura principal (%)',
            'primary_text_box_height': 'Altura principal (%)',
            'text_align_horizontal': 'Alinhamento horizontal',
            'text_align_vertical': 'Alinhamento vertical',
            'secondary_text_box_x': 'X secundaria (%)',
            'secondary_text_box_y': 'Y secundaria (%)',
            'secondary_text_box_width': 'Largura secundaria (%)',
            'secondary_text_box_height': 'Altura secundaria (%)',
            'secondary_text_align_horizontal': 'Alinh. horizontal secundaria',
            'secondary_text_align_vertical': 'Alinh. vertical secundaria',
        }
        help_texts = {
            'text_box_preset': 'Preenche a caixa principal quando os percentuais estiverem vazios. Depois e possivel ajustar manualmente.',
            'primary_text_box_x': 'Use valores de 0 a 100. Ex.: 7 posiciona a caixa a 7% da esquerda.',
            'secondary_text_box_x': 'Opcional. Usada se a frase nao couber bem na caixa principal.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()
        self.fields['text_position'].widget.attrs['class'] = 'form-select'
        self.fields['text_box_preset'].widget.attrs['class'] = 'form-select'
        self.fields['text_align_horizontal'].widget.attrs['class'] = 'form-select'
        self.fields['text_align_vertical'].widget.attrs['class'] = 'form-select'
        self.fields['secondary_text_align_horizontal'].widget.attrs['class'] = 'form-select'
        self.fields['secondary_text_align_vertical'].widget.attrs['class'] = 'form-select'
        for field_name in [
            'text_align_horizontal',
            'text_align_vertical',
            'secondary_text_align_horizontal',
            'secondary_text_align_vertical',
        ]:
            self.fields[field_name].required = False

    def clean(self):
        cleaned = super().clean()
        cleaned['text_align_horizontal'] = cleaned.get('text_align_horizontal') or SocialBaseImage.TextAlignHorizontal.CENTER
        cleaned['text_align_vertical'] = cleaned.get('text_align_vertical') or SocialBaseImage.TextAlignVertical.MIDDLE
        cleaned['secondary_text_align_horizontal'] = cleaned.get('secondary_text_align_horizontal') or SocialBaseImage.TextAlignHorizontal.CENTER
        cleaned['secondary_text_align_vertical'] = cleaned.get('secondary_text_align_vertical') or SocialBaseImage.TextAlignVertical.MIDDLE
        preset = cleaned.get('text_box_preset')
        primary_values = [
            cleaned.get('primary_text_box_x'),
            cleaned.get('primary_text_box_y'),
            cleaned.get('primary_text_box_width'),
            cleaned.get('primary_text_box_height'),
        ]
        if preset and not any(value is not None for value in primary_values):
            x, y, width, height = self.PRESET_BOXES[preset]
            cleaned['primary_text_box_x'] = x
            cleaned['primary_text_box_y'] = y
            cleaned['primary_text_box_width'] = width
            cleaned['primary_text_box_height'] = height

        self._validate_box(cleaned, 'primary_text_box', required=False)
        self._validate_box(cleaned, 'secondary_text_box', required=False)
        return cleaned

    def _validate_box(self, cleaned, prefix, required=False):
        keys = [f'{prefix}_x', f'{prefix}_y', f'{prefix}_width', f'{prefix}_height']
        values = [cleaned.get(key) for key in keys]
        if not any(value is not None for value in values):
            return
        if required or not all(value is not None for value in values):
            raise forms.ValidationError('Informe X, Y, largura e altura da caixa de texto.')
        x, y, width, height = [float(value) for value in values]
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise forms.ValidationError('A caixa de texto precisa ter valores positivos.')
        if x + width > 100 or y + height > 100:
            raise forms.ValidationError('A caixa de texto nao pode ultrapassar os limites da imagem.')


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


class SocialGenerateForm(BootstrapMixin, forms.Form):
    quantidade = forms.IntegerField(label='Quantidade', min_value=1)
    tema = forms.CharField(
        label='Tema opcional',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ex.: rotina de obra, bastidores, seguranca, equipe'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        limite = settings.OPENAI_SOCIAL_MAX_BATCH
        self.fields['quantidade'].max_value = limite
        self.fields['quantidade'].initial = min(10, limite)
        self.fields['quantidade'].help_text = f'Maximo configurado: {limite}.'
        self._apply_bootstrap()

    def clean_quantidade(self):
        quantidade = self.cleaned_data['quantidade']
        limite = settings.OPENAI_SOCIAL_MAX_BATCH
        if quantidade > limite:
            raise forms.ValidationError(f'Informe no maximo {limite} conteudos por lote.')
        return quantidade
