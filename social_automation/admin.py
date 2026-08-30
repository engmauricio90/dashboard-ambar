from django.contrib import admin

from .models import (
    SocialBaseImage,
    SocialBaseImageProtectedRegion,
    SocialAIUsage,
    SocialCarouselSlide,
    SocialCarouselTemplate,
    SocialCarouselTemplateVariant,
    SocialContent,
    SocialContentEvent,
    SocialInstagramConnection,
    SocialProfile,
    SocialVisualIdentity,
)


class SocialBaseImageInline(admin.TabularInline):
    model = SocialBaseImage
    extra = 0
    fields = ['nome', 'ativa', 'source', 'text_position', 'text_box_preset', 'tags', 'vezes_usada', 'ultima_utilizacao']
    readonly_fields = ['vezes_usada', 'ultima_utilizacao']


class SocialBaseImageProtectedRegionInline(admin.TabularInline):
    model = SocialBaseImageProtectedRegion
    extra = 0
    fields = ['region_type', 'source', 'confidence', 'x', 'y', 'width', 'height', 'active', 'note']


class SocialVisualIdentityInline(admin.StackedInline):
    model = SocialVisualIdentity
    extra = 0
    fields = ['name', 'active', 'is_default', 'brand_name', 'primary_color', 'secondary_color', 'accent_color']


class SocialCarouselTemplateInline(admin.TabularInline):
    model = SocialCarouselTemplate
    extra = 0
    fields = ['name', 'active', 'is_default', 'aspect_ratio', 'background_type']


class SocialInstagramConnectionInline(admin.StackedInline):
    model = SocialInstagramConnection
    extra = 0
    fields = [
        'instagram_user_id',
        'username',
        'account_type',
        'is_active',
        'connected_at',
        'last_validated_at',
        'last_validation_status',
        'last_validation_error',
        'token_expires_at',
    ]
    readonly_fields = ['connected_at', 'last_validated_at', 'last_validation_status', 'last_validation_error']
    can_delete = False


@admin.register(SocialProfile)
class SocialProfileAdmin(admin.ModelAdmin):
    list_display = ['nome', 'username', 'plataforma', 'modo_operacao', 'ativo', 'ai_image_mode', 'posts_por_dia', 'reels_por_dia', 'carousels_por_dia', 'updated_at']
    list_filter = ['plataforma', 'modo_operacao', 'ativo', 'ai_image_mode', 'ai_image_generation_enabled']
    search_fields = ['nome', 'username', 'estilo', 'instrucoes_ia']
    inlines = [SocialInstagramConnectionInline, SocialVisualIdentityInline, SocialBaseImageInline, SocialCarouselTemplateInline]


@admin.register(SocialInstagramConnection)
class SocialInstagramConnectionAdmin(admin.ModelAdmin):
    list_display = ['profile', 'username', 'instagram_user_id', 'account_type', 'is_active', 'last_validation_status', 'last_validated_at']
    list_filter = ['is_active', 'account_type', 'last_validation_status']
    search_fields = ['profile__nome', 'profile__username', 'username', 'instagram_user_id']
    readonly_fields = ['connected_at', 'last_validated_at', 'created_at', 'updated_at']
    fields = [
        'profile',
        'instagram_user_id',
        'username',
        'account_type',
        'access_token_encrypted',
        'is_active',
        'connected_at',
        'last_validated_at',
        'last_validation_status',
        'last_validation_error',
        'token_expires_at',
        'created_at',
        'updated_at',
    ]


@admin.register(SocialBaseImage)
class SocialBaseImageAdmin(admin.ModelAdmin):
    list_display = ['nome', 'profile', 'source', 'ativa', 'text_safe_zone', 'subject_position', 'analysis_confidence', 'vezes_usada', 'ultima_utilizacao', 'created_at']
    list_filter = ['ativa', 'source', 'text_position', 'text_box_preset', 'text_safe_zone', 'subject_position', 'profile']
    search_fields = ['nome', 'descricao', 'tags', 'profile__nome', 'profile__username']
    readonly_fields = ['vezes_usada', 'ultima_utilizacao', 'generated_at', 'analysis_model', 'analysis_version', 'analysis_confidence', 'analyzed_at', 'created_at', 'updated_at']
    fieldsets = (
        (None, {'fields': ('profile', 'arquivo', 'nome', 'descricao', 'tags', 'source', 'ativa')}),
        ('Composicao', {'fields': ('subject_position', 'text_safe_zone', 'focal_x', 'focal_y')}),
        ('Texto', {'fields': ('text_position', 'text_box_preset', 'text_align_horizontal', 'text_align_vertical')}),
        ('Caixa principal (%)', {'fields': ('primary_text_box_x', 'primary_text_box_y', 'primary_text_box_width', 'primary_text_box_height')}),
        ('Caixa secundaria (%)', {'fields': ('secondary_text_box_x', 'secondary_text_box_y', 'secondary_text_box_width', 'secondary_text_box_height', 'secondary_text_align_horizontal', 'secondary_text_align_vertical')}),
        ('IA', {'fields': ('ai_model', 'ai_prompt', 'ai_generation_id', 'generation_purpose', 'generated_at', 'analysis_model', 'analysis_version', 'analysis_confidence', 'analyzed_at')}),
        ('Uso', {'fields': ('vezes_usada', 'ultima_utilizacao', 'created_at', 'updated_at')}),
    )
    inlines = [SocialBaseImageProtectedRegionInline]


class SocialContentEventInline(admin.TabularInline):
    model = SocialContentEvent
    extra = 0
    fields = ['acao', 'usuario', 'detalhe', 'created_at']
    readonly_fields = ['acao', 'usuario', 'detalhe', 'created_at']
    can_delete = False


class SocialCarouselSlideInline(admin.TabularInline):
    model = SocialCarouselSlide
    extra = 0
    fields = ['order', 'slide_type', 'visual_intent', 'semantic_visual_intent', 'media_intent', 'media_required', 'variant', 'source_base_image', 'title', 'is_active', 'rendered_image', 'instagram_container_id']
    readonly_fields = ['rendered_image', 'instagram_container_id']


@admin.register(SocialContent)
class SocialContentAdmin(admin.ModelAdmin):
    list_display = ['id', 'profile', 'media_type', 'status', 'scheduled_at', 'published_at', 'created_at']
    list_filter = ['status', 'media_type', 'profile']
    search_fields = ['frase', 'legenda', 'hashtags', 'profile__nome', 'profile__username']
    readonly_fields = [
        'created_at',
        'updated_at',
        'published_at',
        'external_post_id',
        'external_permalink',
        'instagram_container_id',
        'instagram_container_fingerprint',
        'tentativas',
        'ultima_tentativa',
    ]
    inlines = [SocialCarouselSlideInline, SocialContentEventInline]


@admin.register(SocialCarouselTemplate)
class SocialCarouselTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'profile', 'aspect_ratio', 'background_type', 'is_default', 'active', 'updated_at']
    list_filter = ['active', 'is_default', 'aspect_ratio', 'background_type', 'profile']
    search_fields = ['name', 'profile__nome', 'profile__username']


@admin.register(SocialVisualIdentity)
class SocialVisualIdentityAdmin(admin.ModelAdmin):
    list_display = ['name', 'profile', 'active', 'is_default', 'accent_color', 'updated_at']
    list_filter = ['active', 'is_default', 'profile']
    search_fields = ['name', 'brand_name', 'profile__nome', 'profile__username']


@admin.register(SocialCarouselTemplateVariant)
class SocialCarouselTemplateVariantAdmin(admin.ModelAdmin):
    list_display = ['name', 'template', 'layout_type', 'active', 'sort_order', 'updated_at']
    list_filter = ['active', 'layout_type', 'template__profile']
    search_fields = ['name', 'template__name', 'template__profile__nome']


@admin.register(SocialBaseImageProtectedRegion)
class SocialBaseImageProtectedRegionAdmin(admin.ModelAdmin):
    list_display = ['image', 'region_type', 'source', 'confidence', 'active', 'x', 'y', 'width', 'height']
    list_filter = ['active', 'region_type', 'source', 'image__profile']
    search_fields = ['image__nome', 'note']


@admin.register(SocialCarouselSlide)
class SocialCarouselSlideAdmin(admin.ModelAdmin):
    list_display = ['content', 'order', 'slide_type', 'visual_intent', 'semantic_visual_intent', 'media_required', 'variant', 'is_active', 'updated_at']
    list_filter = ['slide_type', 'visual_intent', 'semantic_visual_intent', 'media_required', 'is_active', 'content__profile']
    search_fields = ['title', 'body', 'media_intent', 'content__frase']


@admin.register(SocialContentEvent)
class SocialContentEventAdmin(admin.ModelAdmin):
    list_display = ['content', 'acao', 'usuario', 'created_at']
    list_filter = ['acao']
    search_fields = ['content__frase', 'detalhe', 'usuario__username']
    readonly_fields = ['content', 'acao', 'usuario', 'detalhe', 'created_at']


@admin.register(SocialAIUsage)
class SocialAIUsageAdmin(admin.ModelAdmin):
    list_display = ['profile', 'operation', 'model', 'success', 'created_at']
    list_filter = ['operation', 'success', 'profile']
    search_fields = ['profile__nome', 'profile__username', 'model', 'error']
    readonly_fields = ['profile', 'content', 'base_image', 'operation', 'provider', 'model', 'success', 'prompt_tokens', 'output_tokens', 'total_tokens', 'error', 'metadata', 'created_at']
