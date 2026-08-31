from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils import timezone

from .models import (
    SocialBaseImage,
    SocialCarouselSlide,
    SocialCarouselTemplate,
    SocialCarouselTemplateVariant,
    SocialContent,
    SocialProfile,
    SocialVisualIdentity,
    validate_horarios_publicacao,
)


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
            'reels_por_dia',
            'carousels_por_dia',
            'carousel_default_slide_count',
            'carousel_ai_instructions',
            'carousel_cta_enabled',
            'carousel_default_cta',
            'carousel_visual_mode',
            'carousel_image_density',
            'carousel_allow_same_image',
            'carousel_max_same_image_uses',
            'ai_image_generation_enabled',
            'ai_image_mode',
            'ai_image_daily_limit',
            'ai_generated_images_reusable',
            'image_ai_instructions',
            'estilo',
            'instrucoes_ia',
            'responder_comentarios',
            'limite_respostas',
        ]
        widgets = {
            'estilo': forms.Textarea(attrs={'rows': 3}),
            'instrucoes_ia': forms.Textarea(attrs={'rows': 5}),
            'carousel_ai_instructions': forms.Textarea(attrs={'rows': 3}),
            'image_ai_instructions': forms.Textarea(attrs={'rows': 3}),
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
        self.fields['reels_por_dia'].required = False
        self.fields['reels_por_dia'].initial = self.instance.reels_por_dia if self.instance and self.instance.pk else 0
        self.fields['carousels_por_dia'].required = False
        self.fields['carousels_por_dia'].initial = self.instance.carousels_por_dia if self.instance and self.instance.pk else 0
        self.fields['carousel_default_slide_count'].required = False
        self.fields['carousel_default_slide_count'].initial = self.instance.carousel_default_slide_count if self.instance and self.instance.pk else 6
        self.fields['carousel_ai_instructions'].required = False
        self.fields['carousel_default_cta'].required = False
        self.fields['carousel_visual_mode'].required = False
        self.fields['carousel_visual_mode'].initial = self.instance.carousel_visual_mode if self.instance and self.instance.pk else 'STANDARD'
        self.fields['carousel_visual_mode'].label = 'Modo visual do carrossel'
        self.fields['carousel_visual_mode'].widget.attrs['class'] = 'form-select'
        self.fields['carousel_image_density'].required = False
        self.fields['carousel_image_density'].initial = self.instance.carousel_image_density if self.instance and self.instance.pk else 'AUTO'
        self.fields['carousel_image_density'].label = 'Densidade de imagens'
        self.fields['carousel_image_density'].widget.attrs['class'] = 'form-select'
        self.fields['carousel_allow_same_image'].required = False
        self.fields['carousel_allow_same_image'].label = 'Permitir repetir a mesma imagem'
        self.fields['carousel_max_same_image_uses'].required = False
        self.fields['carousel_max_same_image_uses'].help_text = '0 usa o padrao do modo visual.'
        self.fields['ai_image_mode'].required = False
        self.fields['ai_image_mode'].initial = self.instance.ai_image_mode if self.instance and self.instance.pk else 'NONE'
        self.fields['ai_image_mode'].label = 'Politica de IA visual'
        self.fields['ai_image_daily_limit'].required = False
        self.fields['ai_image_daily_limit'].help_text = '0 usa o limite padrao do sistema.'
        self.fields['ai_generated_images_reusable'].required = False
        self.fields['image_ai_instructions'].required = False

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

    def clean_reels_por_dia(self):
        return self.cleaned_data.get('reels_por_dia') or 0

    def clean_carousels_por_dia(self):
        return self.cleaned_data.get('carousels_por_dia') or 0

    def clean_carousel_default_slide_count(self):
        return self.cleaned_data.get('carousel_default_slide_count') or 6

    def clean_carousel_visual_mode(self):
        return self.cleaned_data.get('carousel_visual_mode') or 'STANDARD'

    def clean_carousel_image_density(self):
        return self.cleaned_data.get('carousel_image_density') or 'AUTO'

    def clean_carousel_max_same_image_uses(self):
        return self.cleaned_data.get('carousel_max_same_image_uses') or 0

    def clean_ai_image_mode(self):
        return self.cleaned_data.get('ai_image_mode') or 'NONE'

    def clean(self):
        cleaned = super().clean()
        posts = cleaned.get('posts_por_dia') or 0
        reels = cleaned.get('reels_por_dia') or 0
        carousels = cleaned.get('carousels_por_dia') or 0
        if reels + carousels > posts:
            raise forms.ValidationError('Reels e carrosseis por dia nao podem superar posts por dia.')
        return cleaned

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
    REEL_PRESET_BOXES = {
        SocialBaseImage.ReelTextBoxPreset.TOP_LEFT: (7, 10, 40, 20),
        SocialBaseImage.ReelTextBoxPreset.TOP_CENTER: (18, 10, 64, 18),
        SocialBaseImage.ReelTextBoxPreset.TOP_RIGHT: (53, 10, 38, 20),
        SocialBaseImage.ReelTextBoxPreset.CENTER_LEFT: (7, 38, 40, 22),
        SocialBaseImage.ReelTextBoxPreset.CENTER_RIGHT: (53, 38, 38, 22),
        SocialBaseImage.ReelTextBoxPreset.BOTTOM_LEFT: (7, 66, 44, 20),
        SocialBaseImage.ReelTextBoxPreset.BOTTOM_CENTER: (15, 66, 70, 20),
        SocialBaseImage.ReelTextBoxPreset.BOTTOM_RIGHT: (51, 66, 40, 20),
    }

    class Meta:
        model = SocialBaseImage
        fields = [
            'arquivo',
            'nome',
            'descricao',
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
            'reel_text_position',
            'reel_text_box_preset',
            'reel_primary_text_box_x',
            'reel_primary_text_box_y',
            'reel_primary_text_box_width',
            'reel_primary_text_box_height',
            'reel_text_align_horizontal',
            'reel_text_align_vertical',
            'reel_secondary_text_box_x',
            'reel_secondary_text_box_y',
            'reel_secondary_text_box_width',
            'reel_secondary_text_box_height',
            'reel_secondary_text_align_horizontal',
            'reel_secondary_text_align_vertical',
            'subject_position',
            'text_safe_zone',
            'focal_x',
            'focal_y',
            'ativa',
        ]
        labels = {
            'text_position': 'Posicao foto',
            'text_box_preset': 'Preset foto',
            'primary_text_box_x': 'X (%)',
            'primary_text_box_y': 'Y (%)',
            'primary_text_box_width': 'Largura (%)',
            'primary_text_box_height': 'Altura (%)',
            'text_align_horizontal': 'Alinhamento horizontal',
            'text_align_vertical': 'Alinhamento vertical',
            'secondary_text_box_x': 'X (%)',
            'secondary_text_box_y': 'Y (%)',
            'secondary_text_box_width': 'Largura (%)',
            'secondary_text_box_height': 'Altura (%)',
            'secondary_text_align_horizontal': 'Alinh. horizontal',
            'secondary_text_align_vertical': 'Alinh. vertical',
            'reel_text_position': 'Posicao Reel',
            'reel_text_box_preset': 'Preset Reel',
            'reel_primary_text_box_x': 'X (%)',
            'reel_primary_text_box_y': 'Y (%)',
            'reel_primary_text_box_width': 'Largura (%)',
            'reel_primary_text_box_height': 'Altura (%)',
            'reel_text_align_horizontal': 'Alinhamento horizontal',
            'reel_text_align_vertical': 'Alinhamento vertical',
            'reel_secondary_text_box_x': 'X (%)',
            'reel_secondary_text_box_y': 'Y (%)',
            'reel_secondary_text_box_width': 'Largura (%)',
            'reel_secondary_text_box_height': 'Altura (%)',
            'reel_secondary_text_align_horizontal': 'Alinh. horizontal',
            'reel_secondary_text_align_vertical': 'Alinh. vertical',
            'subject_position': 'Posicao do assunto',
            'text_safe_zone': 'Area segura para texto',
            'focal_x': 'Foco X',
            'focal_y': 'Foco Y',
            'descricao': 'Descricao visual',
        }
        help_texts = {
            'text_box_preset': 'Preenche a caixa principal da foto quando os percentuais estiverem vazios.',
            'reel_text_box_preset': 'Preenche a caixa principal do Reel. Depois e possivel ajustar manualmente.',
            'primary_text_box_x': 'Use valores de 0 a 100. Ex.: 7 posiciona a caixa a 7% da esquerda.',
            'reel_primary_text_box_x': 'Use valores de 0 a 100 no canvas vertical 1080 x 1920.',
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
        self.fields['reel_text_position'].widget.attrs['class'] = 'form-select'
        self.fields['reel_text_box_preset'].widget.attrs['class'] = 'form-select'
        self.fields['reel_text_align_horizontal'].widget.attrs['class'] = 'form-select'
        self.fields['reel_text_align_vertical'].widget.attrs['class'] = 'form-select'
        self.fields['reel_secondary_text_align_horizontal'].widget.attrs['class'] = 'form-select'
        self.fields['reel_secondary_text_align_vertical'].widget.attrs['class'] = 'form-select'
        self.fields['subject_position'].widget.attrs['class'] = 'form-select'
        self.fields['text_safe_zone'].widget.attrs['class'] = 'form-select'
        for field_name in [
            'reel_text_position',
            'text_align_horizontal',
            'text_align_vertical',
            'secondary_text_align_horizontal',
            'secondary_text_align_vertical',
            'reel_text_align_horizontal',
            'reel_text_align_vertical',
            'reel_secondary_text_align_horizontal',
            'reel_secondary_text_align_vertical',
            'subject_position',
            'text_safe_zone',
            'focal_x',
            'focal_y',
        ]:
            self.fields[field_name].required = False

    def clean(self):
        cleaned = super().clean()
        cleaned['text_align_horizontal'] = cleaned.get('text_align_horizontal') or SocialBaseImage.TextAlignHorizontal.CENTER
        cleaned['text_align_vertical'] = cleaned.get('text_align_vertical') or SocialBaseImage.TextAlignVertical.MIDDLE
        cleaned['secondary_text_align_horizontal'] = cleaned.get('secondary_text_align_horizontal') or SocialBaseImage.TextAlignHorizontal.CENTER
        cleaned['secondary_text_align_vertical'] = cleaned.get('secondary_text_align_vertical') or SocialBaseImage.TextAlignVertical.MIDDLE
        cleaned['reel_text_position'] = cleaned.get('reel_text_position') or SocialBaseImage.TextPosition.AUTO
        cleaned['reel_text_align_horizontal'] = cleaned.get('reel_text_align_horizontal') or SocialBaseImage.TextAlignHorizontal.CENTER
        cleaned['reel_text_align_vertical'] = cleaned.get('reel_text_align_vertical') or SocialBaseImage.TextAlignVertical.MIDDLE
        cleaned['reel_secondary_text_align_horizontal'] = cleaned.get('reel_secondary_text_align_horizontal') or SocialBaseImage.TextAlignHorizontal.CENTER
        cleaned['reel_secondary_text_align_vertical'] = cleaned.get('reel_secondary_text_align_vertical') or SocialBaseImage.TextAlignVertical.MIDDLE
        cleaned['subject_position'] = cleaned.get('subject_position') or SocialBaseImage.SubjectPosition.NONE
        cleaned['text_safe_zone'] = cleaned.get('text_safe_zone') or SocialBaseImage.TextSafeZone.AUTO
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
        reel_preset = cleaned.get('reel_text_box_preset')
        reel_primary_values = [
            cleaned.get('reel_primary_text_box_x'),
            cleaned.get('reel_primary_text_box_y'),
            cleaned.get('reel_primary_text_box_width'),
            cleaned.get('reel_primary_text_box_height'),
        ]
        if reel_preset and not any(value is not None for value in reel_primary_values):
            x, y, width, height = self.REEL_PRESET_BOXES[reel_preset]
            cleaned['reel_primary_text_box_x'] = x
            cleaned['reel_primary_text_box_y'] = y
            cleaned['reel_primary_text_box_width'] = width
            cleaned['reel_primary_text_box_height'] = height

        self._validate_box(cleaned, 'primary_text_box', required=False)
        self._validate_box(cleaned, 'secondary_text_box', required=False)
        self._validate_box(cleaned, 'reel_primary_text_box', required=False)
        self._validate_box(cleaned, 'reel_secondary_text_box', required=False)
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


class SocialVisualIdentityForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SocialVisualIdentity
        fields = [
            'name',
            'active',
            'is_default',
            'primary_color',
            'secondary_color',
            'accent_color',
            'light_text_color',
            'dark_text_color',
            'font_primary',
            'font_secondary',
            'font_weight_title',
            'font_weight_body',
            'brand_name',
            'brand_logo',
            'show_brand_name',
            'show_slide_number',
            'default_overlay_strength',
            'default_margin',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()
        for field_name in ['font_primary', 'font_secondary']:
            self.fields[field_name].widget.attrs['class'] = 'form-select'
        for field_name in [
            'primary_color',
            'secondary_color',
            'accent_color',
            'light_text_color',
            'dark_text_color',
        ]:
            self.fields[field_name].widget = forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'})


class SocialContentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SocialContent
        fields = ['profile', 'media_type', 'base_image', 'carousel_template', 'frase', 'legenda', 'hashtags']
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
            self.fields['carousel_template'].queryset = SocialCarouselTemplate.objects.filter(profile=profile, active=True)
        else:
            self.fields['profile'].queryset = SocialProfile.objects.order_by('nome')
            self.fields['base_image'].queryset = SocialBaseImage.objects.filter(ativa=True).select_related('profile')
            self.fields['carousel_template'].queryset = SocialCarouselTemplate.objects.filter(active=True).select_related('profile')
        self._apply_bootstrap()
        if not isinstance(self.fields['profile'].widget, forms.HiddenInput):
            self.fields['profile'].widget.attrs['class'] = 'form-select'
        self.fields['media_type'].required = False
        self.fields['media_type'].initial = SocialContent.MediaType.IMAGE
        self.fields['media_type'].widget.attrs['class'] = 'form-select'
        self.fields['base_image'].widget.attrs['class'] = 'form-select'
        self.fields['base_image'].required = False
        self.fields['carousel_template'].required = False
        self.fields['carousel_template'].widget.attrs['class'] = 'form-select'

    def clean(self):
        cleaned = super().clean()
        profile = cleaned.get('profile')
        base_image = cleaned.get('base_image')
        carousel_template = cleaned.get('carousel_template')
        if base_image and profile and base_image.profile_id != profile.id:
            raise forms.ValidationError('A imagem-base precisa pertencer ao perfil selecionado.')
        if carousel_template and profile and carousel_template.profile_id != profile.id:
            raise forms.ValidationError('O template de carrossel precisa pertencer ao perfil selecionado.')
        media_type = cleaned.get('media_type') or SocialContent.MediaType.IMAGE
        if media_type != SocialContent.MediaType.CAROUSEL and not base_image:
            raise forms.ValidationError('Selecione uma imagem-base para foto ou Reel.')
        return cleaned

    def clean_media_type(self):
        return self.cleaned_data.get('media_type') or SocialContent.MediaType.IMAGE


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


class SocialAICarouselForm(BootstrapMixin, forms.Form):
    tema = forms.CharField(
        label='Tema',
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Opcional. Ex.: bastidores, tutorial, lancamento, dica pratica'}),
    )
    slides = forms.IntegerField(label='Quantidade de slides', min_value=2, max_value=10, required=False)

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.fields['slides'].initial = profile.carousel_default_slide_count or 6
        self._apply_bootstrap()


class SocialCarouselTemplateForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SocialCarouselTemplate
        fields = [
            'name',
            'active',
            'is_default',
            'aspect_ratio',
            'background_type',
            'background_image',
            'background_color',
            'secondary_background_color',
            'text_color',
            'accent_color',
            'title_alignment',
            'body_alignment',
            'show_profile_name',
            'show_slide_number',
            'show_footer',
            'footer_text',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()
        for field_name in ['aspect_ratio', 'background_type', 'title_alignment', 'body_alignment']:
            self.fields[field_name].widget.attrs['class'] = 'form-select'


class SocialCarouselSlideForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SocialCarouselSlide
        fields = [
            'order',
            'slide_type',
            'visual_intent',
            'visual_treatment',
            'semantic_visual_intent',
            'media_intent',
            'media_required',
            'variant',
            'source_base_image',
            'title',
            'body',
            'source_image',
            'text_color_override',
            'overlay_override',
            'is_active',
        ]
        widgets = {
            'body': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()
        content = self.instance.content if self.instance and self.instance.content_id else None
        for field_name in ['slide_type', 'visual_intent', 'visual_treatment', 'variant', 'source_base_image', 'overlay_override']:
            self.fields[field_name].widget.attrs['class'] = 'form-select'
        self.fields['visual_intent'].required = False
        self.fields['visual_treatment'].required = False
        self.fields['semantic_visual_intent'].required = False
        self.fields['media_intent'].required = False
        self.fields['media_required'].required = False
        self.fields['variant'].required = False
        self.fields['source_base_image'].required = False
        self.fields['overlay_override'].required = False
        self.fields['text_color_override'].required = False
        if content:
            self.fields['variant'].queryset = SocialCarouselTemplateVariant.objects.none()
            self.fields['source_base_image'].queryset = content.profile.base_images.filter(ativa=True)
            template = content.carousel_template or content.profile.carousel_templates.filter(active=True, is_default=True).first()
            if template:
                self.fields['variant'].queryset = template.variants.filter(active=True)
        else:
            self.fields['variant'].queryset = SocialCarouselTemplateVariant.objects.filter(active=True).select_related('template')
            self.fields['source_base_image'].queryset = SocialBaseImage.objects.filter(ativa=True).select_related('profile')

    def has_real_slide_content(self):
        if self.is_bound:
            title = (self.data.get(f'{self.prefix}-title') or '').strip()
            body = (self.data.get(f'{self.prefix}-body') or '').strip()
            uploaded = bool(self.files.get(f'{self.prefix}-source_image'))
            existing = bool(getattr(self.instance, 'source_image', None))
            return bool(title or body or uploaded or existing)
        return bool(self.instance.pk and (self.instance.title or self.instance.body or self.instance.source_image))

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('DELETE'):
            return cleaned_data
        if self.instance.pk and not self.has_real_slide_content():
            raise forms.ValidationError('Informe titulo, texto ou imagem para o slide.')
        if not self.instance.pk and not self.has_real_slide_content():
            cleaned_data['DELETE'] = True
            self.cleaned_data = cleaned_data
        cleaned_data['visual_intent'] = cleaned_data.get('visual_intent') or SocialCarouselTemplateVariant.LayoutType.AUTO
        cleaned_data['visual_treatment'] = cleaned_data.get('visual_treatment') or SocialCarouselSlide.VisualTreatment.AUTO
        return cleaned_data


class BaseSocialCarouselSlideFormSet(BaseInlineFormSet):
    def clean(self):
        if any(self.errors):
            return

        active_orders = set()
        active_count = 0
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            if not form.has_real_slide_content():
                continue
            if not form.cleaned_data.get('is_active', True):
                continue

            order = form.cleaned_data.get('order')
            if order in active_orders:
                raise forms.ValidationError('Cada slide ativo precisa ter uma ordem unica.')
            active_orders.add(order)
            active_count += 1

        if active_count and active_count < 2:
            raise forms.ValidationError('Carrossel precisa ter no minimo 2 slides ativos.')
        if active_count > 10:
            raise forms.ValidationError('Carrossel permite no maximo 10 slides ativos.')


SocialCarouselSlideFormSet = forms.inlineformset_factory(
    SocialContent,
    SocialCarouselSlide,
    form=SocialCarouselSlideForm,
    formset=BaseSocialCarouselSlideFormSet,
    extra=6,
    can_delete=True,
    min_num=0,
    validate_min=False,
)
