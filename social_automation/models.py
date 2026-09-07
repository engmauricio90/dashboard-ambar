from zoneinfo import available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .typography import FONT_FAMILY_CHOICES, FONT_SCALE_CHOICES, LINE_SPACING_CHOICES, TEXT_OUTLINE_CHOICES, TEXT_SHADOW_CHOICES

from .token_crypto import decrypt_instagram_token, encrypt_instagram_token
from .media_paths import social_upload_to


def social_base_image_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return social_upload_to(profile_id, 'base', filename)


def social_final_image_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return social_upload_to(profile_id, 'posts', filename)


def social_final_video_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return social_upload_to(profile_id, 'reels', filename, default_extension='.mp4')


def social_carousel_template_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return social_upload_to(profile_id, 'carousel_templates', filename)


def social_visual_identity_logo_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return social_upload_to(profile_id, 'identity', filename)


def social_carousel_slide_source_upload_to(instance, filename):
    profile_id = instance.content.profile_id if instance.content_id else 'sem-perfil'
    content_id = instance.content_id or 'sem-conteudo'
    return social_upload_to(profile_id, f'carousels/{content_id}/sources', filename)


def social_carousel_slide_rendered_upload_to(instance, filename):
    profile_id = instance.content.profile_id if instance.content_id else 'sem-perfil'
    content_id = instance.content_id or 'sem-conteudo'
    return social_upload_to(profile_id, f'carousels/{content_id}/slides', filename)


def social_carousel_slide_composed_upload_to(instance, filename):
    profile_id = instance.content.profile_id if instance.content_id else 'sem-perfil'
    content_id = instance.content_id or 'sem-conteudo'
    return social_upload_to(profile_id, f'carousels/{content_id}/composed', filename)


def social_creative_reference_upload_to(instance, filename):
    profile_id = instance.profile_id or 'global'
    return social_upload_to(profile_id, 'creative_references', filename)


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

    class AIImagePolicy(models.TextChoices):
        NONE = 'NONE', 'Sem IA visual'
        BANK_ONLY = 'BANK_ONLY', 'Somente banco de midia'
        AI_WHEN_NEEDED = 'AI_WHEN_NEEDED', 'IA quando necessario'
        AI_ALWAYS = 'AI_ALWAYS', 'IA sempre'

    class CarouselVisualMode(models.TextChoices):
        STANDARD = 'STANDARD', 'Padrao'
        VISUAL_RICH = 'VISUAL_RICH', 'Visual premium'
        IMAGE_DRIVEN = 'IMAGE_DRIVEN', 'Imagem em todos os slides'

    class CarouselEditorialMode(models.TextChoices):
        STANDARD = 'STANDARD', 'Padrao'
        SOCIAL_PREMIUM = 'SOCIAL_PREMIUM', 'Social premium'

    class CarouselImageDensity(models.TextChoices):
        AUTO = 'AUTO', 'Automatica'
        LOW = 'LOW', 'Baixa'
        MEDIUM = 'MEDIUM', 'Media'
        HIGH = 'HIGH', 'Alta'
        EVERY_SLIDE = 'EVERY_SLIDE', 'Todos os slides'

    class CarouselGenerationMode(models.TextChoices):
        SYSTEM_COMPOSED = 'SYSTEM_COMPOSED', 'Sistema'
        AI_DIRECTED = 'AI_DIRECTED', 'IA dirigida'
        AI_FINISHED = 'AI_FINISHED', 'IA - arte final'

    class CarouselCreativeVariation(models.TextChoices):
        LOW = 'LOW', 'Baixa'
        MEDIUM = 'MEDIUM', 'Media'
        HIGH = 'HIGH', 'Alta'

    class CarouselFallbackPolicy(models.TextChoices):
        STRICT = 'STRICT', 'Estrito'
        ALLOW_SYSTEM_FALLBACK = 'ALLOW_SYSTEM_FALLBACK', 'Permitir compositor do sistema'

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
    carousel_generation_mode = models.CharField(max_length=30, choices=CarouselGenerationMode.choices, default=CarouselGenerationMode.SYSTEM_COMPOSED)
    carousel_creative_variation = models.CharField(max_length=20, choices=CarouselCreativeVariation.choices, default=CarouselCreativeVariation.MEDIUM)
    carousel_fallback_policy = models.CharField(max_length=30, choices=CarouselFallbackPolicy.choices, default=CarouselFallbackPolicy.STRICT)
    carousel_editorial_mode = models.CharField(max_length=30, choices=CarouselEditorialMode.choices, default=CarouselEditorialMode.STANDARD)
    carousel_visual_mode = models.CharField(max_length=30, choices=CarouselVisualMode.choices, default=CarouselVisualMode.STANDARD)
    carousel_image_density = models.CharField(max_length=30, choices=CarouselImageDensity.choices, default=CarouselImageDensity.AUTO)
    carousel_allow_same_image = models.BooleanField(default=True)
    carousel_max_same_image_uses = models.PositiveSmallIntegerField(default=0)
    ai_image_generation_enabled = models.BooleanField(default=False)
    ai_image_mode = models.CharField(max_length=30, choices=AIImagePolicy.choices, default=AIImagePolicy.NONE)
    ai_image_daily_limit = models.PositiveSmallIntegerField(default=0)
    ai_generated_images_reusable = models.BooleanField(default=True)
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

    @property
    def ai_image_policy(self):
        return self.ai_image_mode or self.AIImagePolicy.NONE

    @ai_image_policy.setter
    def ai_image_policy(self, value):
        self.ai_image_mode = value or self.AIImagePolicy.NONE

    def clean(self):
        super().clean()
        if self.carousel_default_slide_count < 2 or self.carousel_default_slide_count > 10:
            raise ValidationError('Slides padrao do carrossel deve ficar entre 2 e 10.')
        if self.reels_por_dia + self.carousels_por_dia > self.posts_por_dia:
            raise ValidationError('Reels e carrosseis por dia nao podem superar posts por dia.')

    @property
    def effective_carousel_max_same_image_uses(self):
        if self.carousel_max_same_image_uses:
            return self.carousel_max_same_image_uses
        if self.carousel_visual_mode == self.CarouselVisualMode.STANDARD and self.carousel_allow_same_image:
            return 10
        return 1


class SocialVisualIdentity(models.Model):
    FONT_CHOICES = FONT_FAMILY_CHOICES

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
    font_scale = models.CharField(max_length=20, choices=FONT_SCALE_CHOICES, default='NORMAL')
    line_spacing = models.CharField(max_length=20, choices=LINE_SPACING_CHOICES, default='NORMAL')
    text_outline = models.CharField(max_length=20, choices=TEXT_OUTLINE_CHOICES, default='AUTO')
    text_shadow = models.CharField(max_length=20, choices=TEXT_SHADOW_CHOICES, default='AUTO')
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
    descricao = models.TextField(blank=True)
    tags = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    ai_model = models.CharField(max_length=120, blank=True)
    ai_prompt = models.TextField(blank=True)
    ai_generation_id = models.CharField(max_length=120, blank=True)
    generation_purpose = models.CharField(max_length=40, blank=True)
    generated_at = models.DateTimeField(blank=True, null=True)
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
    analysis_metadata = models.JSONField(default=dict, blank=True)
    analysis_model = models.CharField(max_length=120, blank=True)
    analysis_version = models.CharField(max_length=40, blank=True)
    analysis_confidence = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    analyzed_at = models.DateTimeField(blank=True, null=True)
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
    class Source(models.TextChoices):
        MANUAL = 'MANUAL', 'Manual'
        AI_ANALYSIS = 'AI_ANALYSIS', 'Analise IA'

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
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    confidence = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
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
        COVER_HERO_RIGHT = 'COVER_HERO_RIGHT', 'Capa hero direita'
        TEXT_TOP = 'TEXT_TOP', 'Texto superior'
        TEXT_BOTTOM = 'TEXT_BOTTOM', 'Texto inferior'
        CENTER_CARD = 'CENTER_CARD', 'Card central'
        SPLIT_LEFT = 'SPLIT_LEFT', 'Dividido esquerda'
        SPLIT_RIGHT = 'SPLIT_RIGHT', 'Dividido direita'
        MINIMAL = 'MINIMAL', 'Minimal'
        FULL_TEXT = 'FULL_TEXT', 'Texto completo'
        EDITORIAL_CARD = 'EDITORIAL_CARD', 'Card editorial'
        IMAGE_BACKGROUND = 'IMAGE_BACKGROUND', 'Imagem de fundo'
        IMAGE_BLUR_TEXT = 'IMAGE_BLUR_TEXT', 'Imagem desfocada com texto'
        QUOTE_VISUAL = 'QUOTE_VISUAL', 'Frase visual'
        GRAPHIC_DARK = 'GRAPHIC_DARK', 'Grafico escuro'
        GRAPHIC_LIGHT = 'GRAPHIC_LIGHT', 'Grafico claro'
        CTA_VISUAL = 'CTA_VISUAL', 'CTA visual'
        COVER_HERO_LEFT = 'COVER_HERO_LEFT', 'Capa hero esquerda'
        COVER_HERO_CENTER = 'COVER_HERO_CENTER', 'Capa hero central'
        QUOTE_BIG = 'QUOTE_BIG', 'Frase grande'
        EDITORIAL_SPLIT = 'EDITORIAL_SPLIT', 'Editorial dividido'
        IMAGE_PUNCH_MINIMAL = 'IMAGE_PUNCH_MINIMAL', 'Imagem impacto minimal'
        DARK_MINIMAL_TEXT = 'DARK_MINIMAL_TEXT', 'Texto minimal escuro'
        CTA_CLEAN = 'CTA_CLEAN', 'CTA limpo'

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
        PUBLISH_CONFIRMATION_PENDING = 'publish_confirmation_pending', 'Publicacao pendente de confirmacao'
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
            if not (2 <= len(slides) <= 10 and all(bool(slide.get_final_image()) for slide in slides)):
                return False
            from .carousel_quality import evaluate_carousel_quality

            return evaluate_carousel_quality(self).valid
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

    class SlideRole(models.TextChoices):
        HOOK_COVER = 'HOOK_COVER', 'Hook de capa'
        BELIEF_BREAK = 'BELIEF_BREAK', 'Quebra de crenca'
        CONTEXT = 'CONTEXT', 'Contexto'
        EXPLANATION = 'EXPLANATION', 'Explicacao'
        INSIGHT = 'INSIGHT', 'Insight'
        VISUAL_PUNCH = 'VISUAL_PUNCH', 'Impacto visual'
        ACTION_STEP = 'ACTION_STEP', 'Acao pratica'
        PROOF = 'PROOF', 'Prova'
        CONCLUSION = 'CONCLUSION', 'Conclusao'
        CTA = 'CTA', 'CTA'

    class VisualTreatment(models.TextChoices):
        AUTO = 'AUTO', 'Automatico'
        IMAGE_HERO = 'IMAGE_HERO', 'Imagem destaque'
        IMAGE_BACKGROUND = 'IMAGE_BACKGROUND', 'Imagem de fundo'
        IMAGE_SPLIT = 'IMAGE_SPLIT', 'Imagem dividida'
        EDITORIAL_CARD = 'EDITORIAL_CARD', 'Card editorial'
        GRAPHIC_BACKGROUND = 'GRAPHIC_BACKGROUND', 'Background grafico'
        MINIMAL_VISUAL = 'MINIMAL_VISUAL', 'Minimal visual'
        TEXT_ONLY = 'TEXT_ONLY', 'Somente texto'

    class RenderMode(models.TextChoices):
        SYSTEM = 'SYSTEM', 'Sistema'
        AI_FINISHED = 'AI_FINISHED', 'IA - arte final'
        HYBRID = 'HYBRID', 'Hibrido'

    class CompositionStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pendente'
        COMPOSING = 'COMPOSING', 'Compondo'
        REVIEWING = 'REVIEWING', 'Revisando'
        READY = 'READY', 'Pronto'
        ERROR = 'ERROR', 'Erro'
        NEEDS_RECOMPOSE = 'NEEDS_RECOMPOSE', 'Recompor'

    class CompositionType(models.TextChoices):
        AUTO = 'AUTO', 'Automatico'
        TYPOGRAPHIC_HERO = 'TYPOGRAPHIC_HERO', 'Tipografia hero'
        PHOTO_EDITORIAL = 'PHOTO_EDITORIAL', 'Foto editorial'
        PHOTO_WITH_TYPE = 'PHOTO_WITH_TYPE', 'Foto com tipografia'
        SOCIAL_POST_CARD = 'SOCIAL_POST_CARD', 'Card social'
        EDITORIAL_CARD = 'EDITORIAL_CARD', 'Card editorial'
        SPLIT_COMPOSITION = 'SPLIT_COMPOSITION', 'Composicao dividida'
        QUOTE_ART = 'QUOTE_ART', 'Frase visual'
        INFOGRAPHIC_LIGHT = 'INFOGRAPHIC_LIGHT', 'Infografico leve'
        NUMBER_STATEMENT = 'NUMBER_STATEMENT', 'Numero/frase'
        MINIMAL_STATEMENT = 'MINIMAL_STATEMENT', 'Minimal'
        COLLAGE = 'COLLAGE', 'Colagem'
        ILLUSTRATIVE = 'ILLUSTRATIVE', 'Ilustrativo'
        CTA_EDITORIAL = 'CTA_EDITORIAL', 'CTA editorial'

    content = models.ForeignKey(SocialContent, on_delete=models.CASCADE, related_name='carousel_slides')
    variant = models.ForeignKey(SocialCarouselTemplateVariant, on_delete=models.SET_NULL, blank=True, null=True, related_name='slides')
    source_base_image = models.ForeignKey(SocialBaseImage, on_delete=models.SET_NULL, blank=True, null=True, related_name='carousel_slides')
    order = models.PositiveSmallIntegerField(default=1)
    slide_type = models.CharField(max_length=20, choices=SlideType.choices, default=SlideType.CONTENT)
    slide_role = models.CharField(max_length=30, choices=SlideRole.choices, default=SlideRole.EXPLANATION)
    visual_intent = models.CharField(max_length=30, choices=SocialCarouselTemplateVariant.LayoutType.choices, default=SocialCarouselTemplateVariant.LayoutType.AUTO)
    visual_treatment = models.CharField(max_length=30, choices=VisualTreatment.choices, default=VisualTreatment.AUTO)
    semantic_visual_intent = models.CharField(max_length=40, blank=True)
    media_intent = models.CharField(max_length=255, blank=True)
    media_required = models.BooleanField(default=False)
    title = models.CharField(max_length=180, blank=True)
    body = models.TextField(blank=True)
    source_image = models.ImageField(upload_to=social_carousel_slide_source_upload_to, blank=True, null=True)
    rendered_image = models.ImageField(upload_to=social_carousel_slide_rendered_upload_to, blank=True, null=True)
    render_mode = models.CharField(max_length=30, choices=RenderMode.choices, default=RenderMode.SYSTEM)
    composition_type = models.CharField(max_length=30, choices=CompositionType.choices, default=CompositionType.AUTO)
    ai_composed_image = models.ImageField(upload_to=social_carousel_slide_composed_upload_to, blank=True, null=True)
    ai_composition_id = models.CharField(max_length=120, blank=True)
    ai_composition_fingerprint = models.CharField(max_length=64, blank=True, default='')
    ai_composition_status = models.CharField(max_length=30, choices=CompositionStatus.choices, default=CompositionStatus.PENDING)
    ai_composition_attempts = models.PositiveSmallIntegerField(default=0)
    rendered_text_snapshot = models.JSONField(default=dict, blank=True)
    creative_plan_metadata = models.JSONField(default=dict, blank=True)
    ai_composition_metadata = models.JSONField(default=dict, blank=True)
    ai_review_metadata = models.JSONField(default=dict, blank=True)
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

    def get_final_image(self):
        if self.render_mode == self.RenderMode.AI_FINISHED:
            if self.ai_composition_status == self.CompositionStatus.READY and self.ai_composed_image:
                return self.ai_composed_image
            return None
        return self.rendered_image if self.rendered_image else None

    @property
    def final_image_ready(self):
        return bool(self.get_final_image())

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
        PUBLISH_PREPARED = 'publish_prepared', 'Publicacao preparada'
        PUBLISH_PROVIDER_CALLED = 'publish_provider_called', 'Meta acionada'
        PUBLISH_CONFIRMED = 'publish_confirmed', 'Publicacao confirmada'
        PUBLISH_AMBIGUOUS = 'publish_ambiguous', 'Publicacao ambigua'
        PUBLISH_RECONCILIATION = 'publish_reconciliation', 'Reconciliacao de publicacao'
        PUBLISH_RETRY_RELEASED = 'publish_retry_released', 'Nova tentativa liberada'

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


class SocialPublishAttempt(models.Model):
    class Provider(models.TextChoices):
        INSTAGRAM = 'instagram', 'Instagram'

    class Status(models.TextChoices):
        PREPARED = 'PREPARED', 'Preparada'
        PROVIDER_CALLED = 'PROVIDER_CALLED', 'Meta acionada'
        CONFIRMED = 'CONFIRMED', 'Confirmada'
        AMBIGUOUS = 'AMBIGUOUS', 'Pendente de confirmacao'
        FAILED_SAFE = 'FAILED_SAFE', 'Falha segura'

    content = models.ForeignKey(SocialContent, on_delete=models.CASCADE, related_name='publish_attempts')
    provider = models.CharField(max_length=30, choices=Provider.choices, default=Provider.INSTAGRAM)
    container_id = models.CharField(max_length=120, blank=True)
    fingerprint = models.CharField(max_length=64, blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    provider_called_at = models.DateTimeField(blank=True, null=True)
    provider_response_at = models.DateTimeField(blank=True, null=True)
    external_post_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PREPARED)
    error_class = models.CharField(max_length=120, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-started_at', '-id']
        indexes = [
            models.Index(fields=['content', 'provider', 'status']),
            models.Index(fields=['status', '-started_at']),
            models.Index(fields=['external_post_id']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['content', 'provider'],
                condition=Q(status__in=['PREPARED', 'PROVIDER_CALLED', 'AMBIGUOUS']),
                name='unique_active_social_publish_attempt',
            ),
        ]

    def __str__(self):
        return f'{self.content_id} - {self.provider} - {self.status}'


class SocialAutomationTick(models.Model):
    class Status(models.TextChoices):
        OK = 'ok', 'OK'
        ALREADY_RUNNING = 'already_running', 'Ja em execucao'
        ERROR = 'error', 'Erro'

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.OK)
    duration_ms = models.PositiveIntegerField(default=0)
    profiles_processed = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    scheduled_count = models.PositiveIntegerField(default=0)
    published_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-started_at', '-id']
        indexes = [
            models.Index(fields=['status', '-started_at']),
            models.Index(fields=['-started_at']),
        ]

    def __str__(self):
        return f'{self.started_at:%d/%m/%Y %H:%M} - {self.status}'


class SocialCreativeReference(models.Model):
    class ReferenceType(models.TextChoices):
        VISUAL_STYLE = 'VISUAL_STYLE', 'Estilo visual'
        CAROUSEL_STYLE = 'CAROUSEL_STYLE', 'Estilo de carrossel'
        COPY_STRUCTURE = 'COPY_STRUCTURE', 'Estrutura de copy'
        HOOK = 'HOOK', 'Hook'
        CTA = 'CTA', 'CTA'
        COMPOSITION = 'COMPOSITION', 'Composicao'

    class OwnershipType(models.TextChoices):
        OWNED = 'OWNED', 'Propria'
        THIRD_PARTY_INSPIRATION = 'THIRD_PARTY_INSPIRATION', 'Inspiracao de terceiro'
        LICENSED = 'LICENSED', 'Licenciada'

    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, blank=True, null=True, related_name='creative_references')
    reference_type = models.CharField(max_length=30, choices=ReferenceType.choices)
    image = models.ImageField(upload_to=social_creative_reference_upload_to, blank=True, null=True)
    text_reference = models.TextField(blank=True)
    style_tags = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    ownership_type = models.CharField(max_length=40, choices=OwnershipType.choices, default=OwnershipType.OWNED)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['profile__nome', 'reference_type', '-created_at']
        indexes = [
            models.Index(fields=['profile', 'active', 'reference_type']),
        ]

    def __str__(self):
        owner = self.profile.username if self.profile_id else 'global'
        return f'{owner} - {self.reference_type}'


class SocialCarouselGenerationRun(models.Model):
    class Status(models.TextChoices):
        IDEATING = 'IDEATING', 'Gerando ideias'
        IDEA_SELECTED = 'IDEA_SELECTED', 'Ideia selecionada'
        BLUEPRINT_READY = 'BLUEPRINT_READY', 'Blueprint pronto'
        EDITORIAL_APPROVED = 'EDITORIAL_APPROVED', 'Editorial aprovado'
        COMPOSING = 'COMPOSING', 'Compondo'
        REVIEWING = 'REVIEWING', 'Revisando'
        READY = 'READY', 'Pronto'
        PARTIAL = 'PARTIAL', 'Parcial'
        ERROR = 'ERROR', 'Erro'

    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='carousel_generation_runs')
    content = models.ForeignKey(SocialContent, on_delete=models.SET_NULL, blank=True, null=True, related_name='carousel_generation_runs')
    generation_mode = models.CharField(max_length=30, default=SocialProfile.CarouselGenerationMode.SYSTEM_COMPOSED)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.IDEATING)
    selected_idea = models.JSONField(default=dict, blank=True)
    selection_metadata = models.JSONField(default=dict, blank=True)
    creative_blueprint = models.JSONField(default=dict, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-started_at', '-id']
        indexes = [
            models.Index(fields=['profile', 'status', '-started_at']),
            models.Index(fields=['content', '-started_at']),
        ]

    def __str__(self):
        return f'{self.profile.username} - {self.generation_mode} - {self.status}'


class SocialAIUsage(models.Model):
    class Operation(models.TextChoices):
        TEXT_GENERATION = 'TEXT_GENERATION', 'Geracao de texto'
        IMAGE_GENERATION = 'IMAGE_GENERATION', 'Geracao de imagem'
        IMAGE_ANALYSIS = 'IMAGE_ANALYSIS', 'Analise de imagem'
        IDEATION = 'IDEATION', 'Ideacao'
        CREATIVE_BLUEPRINT = 'CREATIVE_BLUEPRINT', 'Blueprint criativo'
        COMPOSED_SLIDE = 'COMPOSED_SLIDE', 'Composicao de slide'
        COMPOSED_SLIDE_REVIEW = 'COMPOSED_SLIDE_REVIEW', 'Review de slide composto'

    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='ai_usages')
    content = models.ForeignKey(SocialContent, on_delete=models.SET_NULL, blank=True, null=True, related_name='ai_usages')
    slide = models.ForeignKey(SocialCarouselSlide, on_delete=models.SET_NULL, blank=True, null=True, related_name='ai_usages')
    base_image = models.ForeignKey(SocialBaseImage, on_delete=models.SET_NULL, blank=True, null=True, related_name='ai_usages')
    operation = models.CharField(max_length=30, choices=Operation.choices)
    provider = models.CharField(max_length=40, default='openai')
    model = models.CharField(max_length=120, blank=True)
    success = models.BooleanField(default=True)
    prompt_tokens = models.PositiveIntegerField(blank=True, null=True)
    output_tokens = models.PositiveIntegerField(blank=True, null=True)
    total_tokens = models.PositiveIntegerField(blank=True, null=True)
    error = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['profile', 'operation', '-created_at']),
            models.Index(fields=['success', '-created_at']),
        ]

    def __str__(self):
        return f'{self.profile.username} - {self.operation} - {self.created_at:%d/%m/%Y %H:%M}'
