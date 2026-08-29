from zoneinfo import available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .token_crypto import decrypt_instagram_token, encrypt_instagram_token


def social_base_image_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return f'social/{profile_id}/base/{filename}'


def social_final_image_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return f'social/{profile_id}/posts/{filename}'


def social_final_video_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return f'social/{profile_id}/reels/{filename}'


def social_carousel_template_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return f'social/{profile_id}/carousel_templates/{filename}'


def social_visual_identity_logo_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return f'social/{profile_id}/identity/{filename}'


def social_carousel_slide_source_upload_to(instance, filename):
    profile_id = instance.content.profile_id if instance.content_id else 'sem-perfil'
    content_id = instance.content_id or 'sem-conteudo'
    return f'social/{profile_id}/carousels/{content_id}/sources/{filename}'


def social_carousel_slide_rendered_upload_to(instance, filename):
    profile_id = instance.content.profile_id if instance.content_id else 'sem-perfil'
    content_id = instance.content_id or 'sem-conteudo'
    return f'social/{profile_id}/carousels/{content_id}/slides/{filename}'


def validate_timezone_name(value):
    if value not in available_timezones():
        raise ValidationError('Timezone invalido.')


def validate_horarios_publicacao(value):
    if not isinstance(value, list):
        raise ValidationError('Informe uma lista de horarios.')
    for horario in value:
        if not isinstance(horario, str):
            raise ValidationError('Cada horario deve ser texto no formato HH:MM.')
        partes = horario.split(':')
        if len(partes) != 2 or not all(parte.isdigit() for parte in partes):
            raise ValidationError('Use horarios no formato HH:MM.')
        hora, minuto = [int(parte) for parte in partes]
        if hora > 23 or minuto > 59:
            raise ValidationError('Use horarios validos no formato HH:MM.')


class SocialProfile(models.Model):
    class Plataforma(models.TextChoices):
        INSTAGRAM = 'instagram', 'Instagram'

    class ModoOperacao(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        SEMIAUTOMATICO = 'semiautomatico', 'Semiautomatico'
        AUTOMATICO = 'automatico', 'Automatico'

    nome = models.CharField(max_length=120)
    username = models.CharField(max_length=120)
    plataforma = models.CharField(max_length=30, choices=Plataforma.choices, default=Plataforma.INSTAGRAM)
    ativo = models.BooleanField(default=True)
    timezone = models.CharField(max_length=80, default='America/Sao_Paulo', validators=[validate_timezone_name])
    modo_operacao = models.CharField(max_length=30, choices=ModoOperacao.choices, default=ModoOperacao.SEMIAUTOMATICO)
    posts_por_dia = models.PositiveSmallIntegerField(default=2)
    reels_por_dia = models.PositiveSmallIntegerField(default=0)
    carousels_por_dia = models.PositiveSmallIntegerField(default=0)
    carousel_default_slide_count = models.PositiveSmallIntegerField(default=6)
    carousel_ai_instructions = models.TextField(blank=True)
    carousel_cta_enabled = models.BooleanField(default=True)
    carousel_default_cta = models.CharField(max_length=255, blank=True)
    ai_image_generation_enabled = models.BooleanField(default=False)
    ai_image_mode = models.CharField(max_length=30, default='NONE')
    image_ai_instructions = models.TextField(blank=True)
    horarios_publicacao = models.JSONField(default=list, validators=[validate_horarios_publicacao])
    estilo = models.TextField(blank=True)
    instrucoes_ia = models.TextField(blank=True)
    responder_comentarios = models.BooleanField(default=False)
    limite_respostas = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']
        indexes = [
            models.Index(fields=['ativo', 'plataforma']),
        ]

    def __str__(self):
        return f'{self.nome} ({self.username})'

    @property
    def fotos_por_dia(self):
        return max(0, self.posts_por_dia - self.reels_por_dia - self.carousels_por_dia)

    def clean(self):
        super().clean()
        if self.carousel_default_slide_count < 2 or self.carousel_default_slide_count > 10:
            raise ValidationError('Slides padrao do carrossel deve ficar entre 2 e 10.')
        if self.reels_por_dia + self.carousels_por_dia > self.posts_por_dia:
            raise ValidationError('Reels e carrosseis por dia nao podem superar posts por dia.')


class SocialVisualIdentity(models.Model):
    FONT_CHOICES = [
        ('SYSTEM_BOLD', 'Sistema negrito'),
        ('SYSTEM_REGULAR', 'Sistema regular'),
        ('SANS_BOLD', 'Sans negrito'),
    ]

    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='visual_identities')
    name = models.CharField(max_length=120, default='Identidade padrao')
    active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=True)
    primary_color = models.CharField(max_length=20, default='#111827')
    secondary_color = models.CharField(max_length=20, default='#334155')
    accent_color = models.CharField(max_length=20, default='#22c55e')
    light_text_color = models.CharField(max_length=20, default='#ffffff')
    dark_text_color = models.CharField(max_length=20, default='#111827')
    font_primary = models.CharField(max_length=40, choices=FONT_CHOICES, default='SYSTEM_BOLD')
    font_secondary = models.CharField(max_length=40, choices=FONT_CHOICES, default='SYSTEM_REGULAR')
    font_weight_title = models.PositiveSmallIntegerField(default=700)
    font_weight_body = models.PositiveSmallIntegerField(default=500)
    brand_name = models.CharField(max_length=120, blank=True)
    brand_logo = models.ImageField(upload_to=social_visual_identity_logo_upload_to, blank=True, null=True)
    show_brand_name = models.BooleanField(default=True)
    show_slide_number = models.BooleanField(default=True)
    default_overlay_strength = models.PositiveSmallIntegerField(default=42)
    default_margin = models.PositiveSmallIntegerField(default=76)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['profile__nome', '-is_default', 'name']
        indexes = [
            models.Index(fields=['profile', 'active', 'is_default']),
        ]

    def __str__(self):
        return f'{self.profile.username} - {self.name}'

    @property
    def display_brand_name(self):
        return self.brand_name or self.profile.nome

    def clean(self):
        super().clean()
        if self.default_overlay_strength > 90:
            raise ValidationError('Overlay padrao deve ficar entre 0 e 90.')
        if self.default_margin < 24 or self.default_margin > 180:
            raise ValidationError('Margem padrao deve ficar entre 24 e 180.')
        if self.is_default:
            queryset = SocialVisualIdentity.objects.filter(profile=self.profile, is_default=True)
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            if queryset.exists():
                raise ValidationError('Este perfil ja possui uma identidade visual padrao.')


class SocialBaseImage(models.Model):
    class Source(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        AI = 'ai', 'IA'

    class TextPosition(models.TextChoices):
        AUTO = 'auto', 'Automatica'
        AUTO_SMART = 'auto_smart', 'Automatica inteligente'
        LEFT = 'left', 'Esquerda'
        RIGHT = 'right', 'Direita'
        TOP = 'top', 'Superior'
        BOTTOM = 'bottom', 'Inferior'

    class TextBoxPreset(models.TextChoices):
        TOP_LEFT = 'top_left', 'Superior esquerda'
        TOP_RIGHT = 'top_right', 'Superior direita'
        MIDDLE_LEFT = 'middle_left', 'Meio esquerda'
        MIDDLE_RIGHT = 'middle_right', 'Meio direita'
        BOTTOM_LEFT = 'bottom_left', 'Inferior esquerda'
        BOTTOM_RIGHT = 'bottom_right', 'Inferior direita'

    class ReelTextBoxPreset(models.TextChoices):
        TOP_LEFT = 'top_left', 'Superior esquerda'
        TOP_CENTER = 'top_center', 'Superior centro'
        TOP_RIGHT = 'top_right', 'Superior direita'
        CENTER_LEFT = 'center_left', 'Centro esquerda'
        CENTER_RIGHT = 'center_right', 'Centro direita'
        BOTTOM_LEFT = 'bottom_left', 'Inferior esquerda'
        BOTTOM_CENTER = 'bottom_center', 'Inferior centro'
        BOTTOM_RIGHT = 'bottom_right', 'Inferior direita'

    class TextAlignHorizontal(models.TextChoices):
        LEFT = 'left', 'Esquerda'
        CENTER = 'center', 'Centro'
        RIGHT = 'right', 'Direita'

    class TextAlignVertical(models.TextChoices):
        TOP = 'top', 'Topo'
        MIDDLE = 'middle', 'Meio'
        BOTTOM = 'bottom', 'Base'

    class SubjectPosition(models.TextChoices):
        NONE = 'none', 'Sem assunto dominante'
        LEFT = 'left', 'Esquerda'
        CENTER = 'center', 'Centro'
        RIGHT = 'right', 'Direita'
        BOTTOM_LEFT = 'bottom_left', 'Inferior esquerda'
        BOTTOM_CENTER = 'bottom_center', 'Inferior centro'
        BOTTOM_RIGHT = 'bottom_right', 'Inferior direita'

    class TextSafeZone(models.TextChoices):
        AUTO = 'auto', 'Automatica'
        LEFT = 'left', 'Esquerda'
        RIGHT = 'right', 'Direita'
        TOP = 'top', 'Superior'
        BOTTOM = 'bottom', 'Inferior'
        FULL = 'full', 'Imagem toda'

    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='base_images')
    arquivo = models.ImageField(upload_to=social_base_image_upload_to)
    nome = models.CharField(max_length=120)
    tags = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    ai_model = models.CharField(max_length=120, blank=True)
    ai_prompt = models.TextField(blank=True)
    text_position = models.CharField(max_length=10, choices=TextPosition.choices, default=TextPosition.AUTO)
    text_box_preset = models.CharField(max_length=20, choices=TextBoxPreset.choices, blank=True)
    primary_text_box_x = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    primary_text_box_y = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    primary_text_box_width = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    primary_text_box_height = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    text_align_horizontal = models.CharField(max_length=10, choices=TextAlignHorizontal.choices, default=TextAlignHorizontal.CENTER)
    text_align_vertical = models.CharField(max_length=10, choices=TextAlignVertical.choices, default=TextAlignVertical.MIDDLE)
    secondary_text_box_x = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    secondary_text_box_y = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    secondary_text_box_width = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    secondary_text_box_height = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    secondary_text_align_horizontal = models.CharField(max_length=10, choices=TextAlignHorizontal.choices, default=TextAlignHorizontal.CENTER)
    secondary_text_align_vertical = models.CharField(max_length=10, choices=TextAlignVertical.choices, default=TextAlignVertical.MIDDLE)
    reel_text_position = models.CharField(max_length=10, choices=TextPosition.choices, default=TextPosition.AUTO)
    reel_text_box_preset = models.CharField(max_length=20, choices=ReelTextBoxPreset.choices, blank=True)
    reel_primary_text_box_x = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reel_primary_text_box_y = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reel_primary_text_box_width = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reel_primary_text_box_height = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reel_text_align_horizontal = models.CharField(max_length=10, choices=TextAlignHorizontal.choices, default=TextAlignHorizontal.CENTER)
    reel_text_align_vertical = models.CharField(max_length=10, choices=TextAlignVertical.choices, default=TextAlignVertical.MIDDLE)
    reel_secondary_text_box_x = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reel_secondary_text_box_y = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reel_secondary_text_box_width = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reel_secondary_text_box_height = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reel_secondary_text_align_horizontal = models.CharField(max_length=10, choices=TextAlignHorizontal.choices, default=TextAlignHorizontal.CENTER)
    reel_secondary_text_align_vertical = models.CharField(max_length=10, choices=TextAlignVertical.choices, default=TextAlignVertical.MIDDLE)
    subject_position = models.CharField(max_length=20, choices=SubjectPosition.choices, default=SubjectPosition.NONE)
    text_safe_zone = models.CharField(max_length=20, choices=TextSafeZone.choices, default=TextSafeZone.AUTO)
    focal_x = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    focal_y = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    ativa = models.BooleanField(default=True)
    vezes_usada = models.PositiveIntegerField(default=0)
    ultima_utilizacao = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['profile', 'ativa']),
        ]

    def __str__(self):
        return f'{self.profile.username} - {self.nome}'

    @property
    def primary_text_box_configured(self):
        return all(
            value is not None
            for value in [
                self.primary_text_box_x,
                self.primary_text_box_y,
                self.primary_text_box_width,
                self.primary_text_box_height,
            ]
        )

    @property
    def secondary_text_box_configured(self):
        return all(
            value is not None
            for value in [
                self.secondary_text_box_x,
                self.secondary_text_box_y,
                self.secondary_text_box_width,
                self.secondary_text_box_height,
            ]
        )

    @property
    def primary_text_box_area_percent(self):
        if not self.primary_text_box_configured:
            return None
        return float(self.primary_text_box_width) * float(self.primary_text_box_height) / 100

    @property
    def reel_primary_text_box_configured(self):
        return all(
            value is not None
            for value in [
                self.reel_primary_text_box_x,
                self.reel_primary_text_box_y,
                self.reel_primary_text_box_width,
                self.reel_primary_text_box_height,
            ]
        )

    @property
    def reel_secondary_text_box_configured(self):
        return all(
            value is not None
            for value in [
                self.reel_secondary_text_box_x,
                self.reel_secondary_text_box_y,
                self.reel_secondary_text_box_width,
                self.reel_secondary_text_box_height,
            ]
        )

    @property
    def reel_layout_configured(self):
        return self.reel_primary_text_box_configured or self.reel_secondary_text_box_configured

    @property
    def reel_primary_text_box_area_percent(self):
        if not self.reel_primary_text_box_configured:
            return None
        return float(self.reel_primary_text_box_width) * float(self.reel_primary_text_box_height) / 100

    def clean(self):
        super().clean()
        for field_name in ['focal_x', 'focal_y']:
            value = getattr(self, field_name)
            if value is not None and (value < 0 or value > 1):
                raise ValidationError(f'{field_name} deve ficar entre 0 e 1.')


class SocialBaseImageProtectedRegion(models.Model):
    class RegionType(models.TextChoices):
        SUBJECT = 'subject', 'Assunto'
        FACE = 'face', 'Rosto'
        LOGO = 'logo', 'Logo'
        PRODUCT = 'product', 'Produto'
        CUSTOM = 'custom', 'Personalizada'

    image = models.ForeignKey(SocialBaseImage, on_delete=models.CASCADE, related_name='protected_regions')
    x = models.DecimalField(max_digits=4, decimal_places=2)
    y = models.DecimalField(max_digits=4, decimal_places=2)
    width = models.DecimalField(max_digits=4, decimal_places=2)
    height = models.DecimalField(max_digits=4, decimal_places=2)
    region_type = models.CharField(max_length=20, choices=RegionType.choices, default=RegionType.SUBJECT)
    active = models.BooleanField(default=True)
    note = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['image', 'id']
        indexes = [
            models.Index(fields=['image', 'active']),
        ]

    def __str__(self):
        return f'{self.image_id} - {self.region_type}'

    def clean(self):
        super().clean()
        for field_name in ['x', 'y', 'width', 'height']:
            value = getattr(self, field_name)
            if value < 0 or value > 1:
                raise ValidationError('Regioes protegidas usam valores normalizados entre 0 e 1.')
        if self.width <= 0 or self.height <= 0:
            raise ValidationError('A regiao protegida precisa ter largura e altura positivas.')
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValidationError('A regiao protegida nao pode ultrapassar os limites da imagem.')


class SocialInstagramConnection(models.Model):
    class ValidationStatus(models.TextChoices):
        NAO_VALIDADO = 'nao_validado', 'Nao validado'
        OK = 'ok', 'OK'
        ERRO = 'erro', 'Erro'

    class AccountType(models.TextChoices):
        BUSINESS = 'BUSINESS', 'Business'
        CREATOR = 'CREATOR', 'Creator'
        DESCONHECIDO = 'DESCONHECIDO', 'Desconhecido'

    profile = models.OneToOneField(SocialProfile, on_delete=models.CASCADE, related_name='instagram_connection')
    instagram_user_id = models.CharField(max_length=80)
    username = models.CharField(max_length=120)
    account_type = models.CharField(max_length=30, choices=AccountType.choices, default=AccountType.DESCONHECIDO)
    access_token_encrypted = models.TextField()
    is_active = models.BooleanField(default=True)
    connected_at = models.DateTimeField(default=timezone.now)
    last_validated_at = models.DateTimeField(blank=True, null=True)
    last_validation_status = models.CharField(max_length=30, choices=ValidationStatus.choices, default=ValidationStatus.NAO_VALIDADO)
    last_validation_error = models.CharField(max_length=500, blank=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['profile__nome']
        indexes = [
            models.Index(fields=['is_active', 'username']),
            models.Index(fields=['instagram_user_id']),
        ]

    def __str__(self):
        return f'{self.profile.username} -> @{self.username}'

    @property
    def normalized_username(self):
        return (self.username or '').strip().lstrip('@').lower()

    @property
    def masked_instagram_user_id(self):
        value = str(self.instagram_user_id or '')
        if len(value) <= 6:
            return value or '-'
        return f'{value[:3]}...{value[-3:]}'

    def set_access_token(self, token):
        self.access_token_encrypted = encrypt_instagram_token(token)

    def get_access_token(self):
        return decrypt_instagram_token(self.access_token_encrypted)

    def mark_validation(self, *, ok, error=''):
        self.last_validated_at = timezone.now()
        self.last_validation_status = self.ValidationStatus.OK if ok else self.ValidationStatus.ERRO
        self.last_validation_error = '' if ok else str(error or '')[:500]
        self.save(update_fields=['last_validated_at', 'last_validation_status', 'last_validation_error', 'updated_at'])

    def save(self, *args, **kwargs):
        old_identity = None
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).only('instagram_user_id', 'username', 'is_active').first()
            if old:
                old_identity = (old.instagram_user_id, old.normalized_username, old.is_active)
        super().save(*args, **kwargs)
        new_identity = (self.instagram_user_id, self.normalized_username, self.is_active)
        if old_identity and old_identity != new_identity:
            SocialContent.objects.filter(profile=self.profile).exclude(instagram_container_id='').update(
                instagram_container_id='',
                instagram_container_fingerprint='',
                updated_at=timezone.now(),
            )


class SocialCarouselTemplate(models.Model):
    class AspectRatio(models.TextChoices):
        SQUARE = 'SQUARE', 'Quadrado 1:1'
        PORTRAIT = 'PORTRAIT', 'Retrato 4:5'

    class BackgroundType(models.TextChoices):
        SOLID = 'SOLID', 'Cor solida'
        GRADIENT = 'GRADIENT', 'Gradiente'
        IMAGE = 'IMAGE', 'Imagem'

    class TextAlignment(models.TextChoices):
        LEFT = 'left', 'Esquerda'
        CENTER = 'center', 'Centro'
        RIGHT = 'right', 'Direita'

    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='carousel_templates')
    name = models.CharField(max_length=120)
    active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    aspect_ratio = models.CharField(max_length=20, choices=AspectRatio.choices, default=AspectRatio.SQUARE)
    background_type = models.CharField(max_length=20, choices=BackgroundType.choices, default=BackgroundType.GRADIENT)
    background_image = models.ImageField(upload_to=social_carousel_template_upload_to, blank=True, null=True)
    background_color = models.CharField(max_length=20, default='#111827')
    secondary_background_color = models.CharField(max_length=20, default='#334155')
    text_color = models.CharField(max_length=20, default='#ffffff')
    accent_color = models.CharField(max_length=20, default='#22c55e')
    font_family = models.CharField(max_length=80, blank=True)
    title_alignment = models.CharField(max_length=10, choices=TextAlignment.choices, default=TextAlignment.LEFT)
    body_alignment = models.CharField(max_length=10, choices=TextAlignment.choices, default=TextAlignment.LEFT)
    show_profile_name = models.BooleanField(default=True)
    show_slide_number = models.BooleanField(default=True)
    show_footer = models.BooleanField(default=True)
    footer_text = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['profile__nome', '-is_default', 'name']
        indexes = [
            models.Index(fields=['profile', 'active']),
        ]

    def __str__(self):
        return f'{self.profile.username} - {self.name}'

    @property
    def canvas_size(self):
        if self.aspect_ratio == self.AspectRatio.PORTRAIT:
            return (1080, 1350)
        return (1080, 1080)

    def clean(self):
        super().clean()
        if self.is_default:
            queryset = SocialCarouselTemplate.objects.filter(profile=self.profile, is_default=True)
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            if queryset.exists():
                raise ValidationError('Este perfil ja possui um template de carrossel padrao.')


class SocialCarouselTemplateVariant(models.Model):
    class LayoutType(models.TextChoices):
        AUTO = 'AUTO', 'Automatico'
        HERO_LEFT = 'HERO_LEFT', 'Hero esquerda'
        HERO_RIGHT = 'HERO_RIGHT', 'Hero direita'
        TEXT_TOP = 'TEXT_TOP', 'Texto superior'
        TEXT_BOTTOM = 'TEXT_BOTTOM', 'Texto inferior'
        CENTER_CARD = 'CENTER_CARD', 'Card central'
        SPLIT_LEFT = 'SPLIT_LEFT', 'Dividido esquerda'
        SPLIT_RIGHT = 'SPLIT_RIGHT', 'Dividido direita'
        MINIMAL = 'MINIMAL', 'Minimal'
        FULL_TEXT = 'FULL_TEXT', 'Texto completo'

    class OverlayType(models.TextChoices):
        AUTO = 'AUTO', 'Automatico'
        NONE = 'NONE', 'Sem overlay'
        DARK = 'DARK', 'Escuro'
        LIGHT = 'LIGHT', 'Claro'
        GRADIENT_LEFT = 'GRADIENT_LEFT', 'Gradiente esquerda'
        GRADIENT_RIGHT = 'GRADIENT_RIGHT', 'Gradiente direita'
        GRADIENT_TOP = 'GRADIENT_TOP', 'Gradiente superior'
        GRADIENT_BOTTOM = 'GRADIENT_BOTTOM', 'Gradiente inferior'

    template = models.ForeignKey(SocialCarouselTemplate, on_delete=models.CASCADE, related_name='variants')
    name = models.CharField(max_length=120)
    active = models.BooleanField(default=True)
    allowed_slide_types = models.JSONField(default=list, blank=True)
    aspect_ratio = models.CharField(max_length=20, choices=SocialCarouselTemplate.AspectRatio.choices, blank=True)
    layout_type = models.CharField(max_length=30, choices=LayoutType.choices, default=LayoutType.AUTO)
    title_alignment = models.CharField(max_length=10, choices=SocialCarouselTemplate.TextAlignment.choices, default=SocialCarouselTemplate.TextAlignment.LEFT)
    body_alignment = models.CharField(max_length=10, choices=SocialCarouselTemplate.TextAlignment.choices, default=SocialCarouselTemplate.TextAlignment.LEFT)
    title_max_lines = models.PositiveSmallIntegerField(default=3)
    body_max_lines = models.PositiveSmallIntegerField(default=5)
    overlay_enabled = models.BooleanField(default=True)
    overlay_type = models.CharField(max_length=30, choices=OverlayType.choices, default=OverlayType.AUTO)
    overlay_strength = models.PositiveSmallIntegerField(default=42)
    show_footer = models.BooleanField(default=True)
    show_slide_number = models.BooleanField(default=True)
    show_brand = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['template', 'sort_order', 'name']
        indexes = [
            models.Index(fields=['template', 'active', 'layout_type']),
        ]

    def __str__(self):
        return f'{self.template.name} - {self.name}'

    @property
    def effective_aspect_ratio(self):
        return self.aspect_ratio or self.template.aspect_ratio

    def allows_slide_type(self, slide_type):
        return not self.allowed_slide_types or slide_type in self.allowed_slide_types

    def clean(self):
        super().clean()
        valid_types = {choice[0] for choice in SocialCarouselSlide.SlideType.choices} if 'SocialCarouselSlide' in globals() else {'COVER', 'CONTENT', 'CTA'}
        invalid = [item for item in self.allowed_slide_types if item not in valid_types]
        if invalid:
            raise ValidationError('Tipos de slide invalidos na variante.')
        if self.overlay_strength > 90:
            raise ValidationError('Overlay da variante deve ficar entre 0 e 90.')


class SocialContent(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = 'image', 'Foto'
        REEL = 'reel', 'Reel'
        CAROUSEL = 'carousel', 'Carrossel'

    class Status(models.TextChoices):
        RASCUNHO = 'rascunho', 'Rascunho'
        APROVADO = 'aprovado', 'Aprovado'
        AGENDADO = 'agendado', 'Agendado'
        PUBLICANDO = 'publicando', 'Publicando'
        PUBLICADO = 'publicado', 'Publicado'
        ERRO = 'erro', 'Erro'
        REJEITADO = 'rejeitado', 'Rejeitado'

    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='contents')
    base_image = models.ForeignKey(SocialBaseImage, on_delete=models.SET_NULL, blank=True, null=True, related_name='contents')
    carousel_template = models.ForeignKey(SocialCarouselTemplate, on_delete=models.SET_NULL, blank=True, null=True, related_name='contents')
    media_type = models.CharField(max_length=10, choices=MediaType.choices, default=MediaType.IMAGE)
    final_image = models.ImageField(upload_to=social_final_image_upload_to, blank=True, null=True)
    final_video = models.FileField(upload_to=social_final_video_upload_to, blank=True, null=True)
    frase = models.CharField(max_length=500)
    legenda = models.TextField(blank=True)
    hashtags = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.RASCUNHO)
    scheduled_at = models.DateTimeField(blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True)
    external_post_id = models.CharField(max_length=120, blank=True)
    external_permalink = models.URLField(blank=True)
    instagram_container_id = models.CharField(max_length=120, blank=True)
    instagram_container_fingerprint = models.CharField(max_length=64, blank=True, default='')
    erro = models.TextField(blank=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    ultima_tentativa = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['profile', 'status']),
            models.Index(fields=['status', 'scheduled_at']),
        ]

    def __str__(self):
        return f'{self.profile.username} - {self.frase[:60]}'

    @property
    def pode_editar_operacionalmente(self):
        return self.status in {
            self.Status.RASCUNHO,
            self.Status.APROVADO,
            self.Status.AGENDADO,
            self.Status.ERRO,
        }

    @property
    def pode_excluir_operacionalmente(self):
        return self.status in {self.Status.RASCUNHO, self.Status.REJEITADO, self.Status.APROVADO}

    @property
    def is_reel(self):
        return self.media_type == self.MediaType.REEL

    @property
    def is_carousel(self):
        return self.media_type == self.MediaType.CAROUSEL

    @property
    def final_media_ready(self):
        if self.is_carousel:
            slides = list(self.carousel_slides.filter(is_active=True))
            return 2 <= len(slides) <= 10 and all(bool(slide.rendered_image) for slide in slides)
        if self.is_reel:
            return bool(self.final_video)
        return bool(self.final_image)

    def clean(self):
        super().clean()
        if self.carousel_template and self.carousel_template.profile_id != self.profile_id:
            raise ValidationError('O template de carrossel precisa pertencer ao perfil do conteudo.')


class SocialCarouselSlide(models.Model):
    class SlideType(models.TextChoices):
        COVER = 'COVER', 'Capa'
        CONTENT = 'CONTENT', 'Conteudo'
        CTA = 'CTA', 'CTA'

    content = models.ForeignKey(SocialContent, on_delete=models.CASCADE, related_name='carousel_slides')
    variant = models.ForeignKey(SocialCarouselTemplateVariant, on_delete=models.SET_NULL, blank=True, null=True, related_name='slides')
    source_base_image = models.ForeignKey(SocialBaseImage, on_delete=models.SET_NULL, blank=True, null=True, related_name='carousel_slides')
    order = models.PositiveSmallIntegerField(default=1)
    slide_type = models.CharField(max_length=20, choices=SlideType.choices, default=SlideType.CONTENT)
    visual_intent = models.CharField(max_length=30, choices=SocialCarouselTemplateVariant.LayoutType.choices, default=SocialCarouselTemplateVariant.LayoutType.AUTO)
    title = models.CharField(max_length=180, blank=True)
    body = models.TextField(blank=True)
    source_image = models.ImageField(upload_to=social_carousel_slide_source_upload_to, blank=True, null=True)
    rendered_image = models.ImageField(upload_to=social_carousel_slide_rendered_upload_to, blank=True, null=True)
    text_color_override = models.CharField(max_length=20, blank=True)
    overlay_override = models.CharField(max_length=30, choices=SocialCarouselTemplateVariant.OverlayType.choices, blank=True)
    render_metadata = models.JSONField(default=dict, blank=True)
    instagram_container_id = models.CharField(max_length=120, blank=True)
    instagram_container_fingerprint = models.CharField(max_length=64, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['content', 'order', 'id']
        indexes = [
            models.Index(fields=['content', 'order']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['content', 'order'], name='unique_social_carousel_slide_order'),
        ]

    def __str__(self):
        return f'{self.content_id} - slide {self.order}'

    def clean(self):
        super().clean()
        if self.content and self.content.media_type != SocialContent.MediaType.CAROUSEL:
            raise ValidationError('Slides so podem ser vinculados a conteudos do tipo carrossel.')
        if self.variant and self.content and self.variant.template.profile_id != self.content.profile_id:
            raise ValidationError('A variante precisa pertencer ao perfil do conteudo.')
        if self.variant and not self.variant.allows_slide_type(self.slide_type):
            raise ValidationError('A variante selecionada nao aceita este tipo de slide.')
        if self.source_base_image and self.content and self.source_base_image.profile_id != self.content.profile_id:
            raise ValidationError('A imagem-base do slide precisa pertencer ao perfil do conteudo.')
        if not self.title and not self.body and not self.source_image:
            raise ValidationError('Informe titulo, texto ou imagem para o slide.')


class SocialContentEvent(models.Model):
    class Acao(models.TextChoices):
        CRIADO = 'criado', 'Criado'
        EDITADO = 'editado', 'Editado'
        APROVADO = 'aprovado', 'Aprovado'
        REJEITADO = 'rejeitado', 'Rejeitado'
        AGENDADO = 'agendado', 'Agendado'
        DESAGENDADO = 'desagendado', 'Desagendado'
        RESTAURADO = 'restaurado', 'Restaurado'
        EXCLUIDO = 'excluido', 'Excluido'

    content = models.ForeignKey(SocialContent, on_delete=models.CASCADE, related_name='events')
    acao = models.CharField(max_length=30, choices=Acao.choices)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
    detalhe = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['content', '-created_at']),
        ]

    def __str__(self):
        return f'{self.content_id} - {self.get_acao_display()}'
