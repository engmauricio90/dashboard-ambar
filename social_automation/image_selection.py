from django.db.models import Q

from .models import SocialBaseImage, SocialContent


def _tags(texto):
    return {tag.strip().lower() for tag in (texto or '').replace(';', ',').split(',') if tag.strip()}


def selecionar_imagem_base(profile, tags_sugeridas=None, excluir_ids=None):
    excluir_ids = set(excluir_ids or [])
    queryset = SocialBaseImage.objects.filter(profile=profile, ativa=True).exclude(id__in=excluir_ids)
    if not queryset.exists():
        return None

    ultima = (
        SocialContent.objects.filter(profile=profile, base_image__isnull=False)
        .order_by('-created_at', '-id')
        .values_list('base_image_id', flat=True)
        .first()
    )
    if ultima and queryset.exclude(id=ultima).exists():
        queryset = queryset.exclude(id=ultima)

    sugeridas = {str(tag).strip().lower() for tag in tags_sugeridas or [] if str(tag).strip()}
    imagens = list(queryset)
    imagens.sort(
        key=lambda imagem: (
            -len(_tags(imagem.tags) & sugeridas),
            imagem.vezes_usada,
            imagem.ultima_utilizacao or imagem.created_at,
            imagem.id,
        )
    )
    return imagens[0]
