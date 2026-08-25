from django.contrib import admin

from .models import SocialBaseImage, SocialContent, SocialContentEvent, SocialProfile


class SocialBaseImageInline(admin.TabularInline):
    model = SocialBaseImage
    extra = 0
    fields = ['nome', 'ativa', 'text_position', 'text_box_preset', 'tags', 'vezes_usada', 'ultima_utilizacao']
    readonly_fields = ['vezes_usada', 'ultima_utilizacao']


@admin.register(SocialProfile)
class SocialProfileAdmin(admin.ModelAdmin):
    list_display = ['nome', 'username', 'plataforma', 'modo_operacao', 'ativo', 'posts_por_dia', 'reels_por_dia', 'updated_at']
    list_filter = ['plataforma', 'modo_operacao', 'ativo']
    search_fields = ['nome', 'username', 'estilo', 'instrucoes_ia']
    inlines = [SocialBaseImageInline]


@admin.register(SocialBaseImage)
class SocialBaseImageAdmin(admin.ModelAdmin):
    list_display = ['nome', 'profile', 'ativa', 'text_position', 'text_box_preset', 'vezes_usada', 'ultima_utilizacao', 'created_at']
    list_filter = ['ativa', 'text_position', 'text_box_preset', 'profile']
    search_fields = ['nome', 'tags', 'profile__nome', 'profile__username']
    readonly_fields = ['vezes_usada', 'ultima_utilizacao', 'created_at', 'updated_at']
    fieldsets = (
        (None, {'fields': ('profile', 'arquivo', 'nome', 'tags', 'ativa')}),
        ('Texto', {'fields': ('text_position', 'text_box_preset', 'text_align_horizontal', 'text_align_vertical')}),
        ('Caixa principal (%)', {'fields': ('primary_text_box_x', 'primary_text_box_y', 'primary_text_box_width', 'primary_text_box_height')}),
        ('Caixa secundaria (%)', {'fields': ('secondary_text_box_x', 'secondary_text_box_y', 'secondary_text_box_width', 'secondary_text_box_height', 'secondary_text_align_horizontal', 'secondary_text_align_vertical')}),
        ('Uso', {'fields': ('vezes_usada', 'ultima_utilizacao', 'created_at', 'updated_at')}),
    )


class SocialContentEventInline(admin.TabularInline):
    model = SocialContentEvent
    extra = 0
    fields = ['acao', 'usuario', 'detalhe', 'created_at']
    readonly_fields = ['acao', 'usuario', 'detalhe', 'created_at']
    can_delete = False


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
    inlines = [SocialContentEventInline]


@admin.register(SocialContentEvent)
class SocialContentEventAdmin(admin.ModelAdmin):
    list_display = ['content', 'acao', 'usuario', 'created_at']
    list_filter = ['acao']
    search_fields = ['content__frase', 'detalhe', 'usuario__username']
    readonly_fields = ['content', 'acao', 'usuario', 'detalhe', 'created_at']
