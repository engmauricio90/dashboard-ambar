from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import SocialBaseImage, SocialContent, SocialProfile


@dataclass(frozen=True)
class MediaResolutionResult:
    status: str
    image: SocialBaseImage | None = None
    score: float = 0
    reason: str = ''


STATUS_SELECTED = 'SELECTED'
STATUS_NEEDS_GENERATION = 'NEEDS_GENERATION'
STATUS_FULL_TEXT = 'FULL_TEXT'
STATUS_UNAVAILABLE = 'UNAVAILABLE'


def _terms(*texts):
    values = set()
    for text in texts:
        normalized = ''.join(ch.lower() if ch.isalnum() else ' ' for ch in str(text or ''))
        values.update(item for item in normalized.split() if len(item) > 2)
    return values


def _preferred_safe_zone(preferred_layout):
    layout = (preferred_layout or '').upper()
    if 'LEFT' in layout:
        return SocialBaseImage.TextSafeZone.LEFT
    if 'RIGHT' in layout:
        return SocialBaseImage.TextSafeZone.RIGHT
    if 'TOP' in layout:
        return SocialBaseImage.TextSafeZone.TOP
    if 'BOTTOM' in layout:
        return SocialBaseImage.TextSafeZone.BOTTOM
    if layout in {'FULL_TEXT', 'CENTER_CARD', 'MINIMAL'}:
        return SocialBaseImage.TextSafeZone.FULL
    return SocialBaseImage.TextSafeZone.AUTO


def _score_image(image, *, media_intent, visual_intent, preferred_layout, aspect_ratio):
    wanted_terms = _terms(media_intent, visual_intent, preferred_layout)
    image_terms = _terms(image.nome, image.tags, image.descricao, image.source, image.text_safe_zone, image.subject_position)
    score = 20
    score += min(30, len(wanted_terms & image_terms) * 10)

    safe_zone = _preferred_safe_zone(preferred_layout)
    if image.text_safe_zone == safe_zone:
        score += 20
    elif image.text_safe_zone in {SocialBaseImage.TextSafeZone.FULL, SocialBaseImage.TextSafeZone.AUTO}:
        score += 8

    subject = image.subject_position
    layout = (preferred_layout or '').upper()
    if 'LEFT' in layout and subject in {SocialBaseImage.SubjectPosition.RIGHT, SocialBaseImage.SubjectPosition.BOTTOM_RIGHT}:
        score += 12
    if 'RIGHT' in layout and subject in {SocialBaseImage.SubjectPosition.LEFT, SocialBaseImage.SubjectPosition.BOTTOM_LEFT}:
        score += 12

    if image.primary_text_box_configured:
        score += 8
    if image.protected_regions.filter(active=True).exists():
        score += 5
    if image.source == SocialBaseImage.Source.MANUAL:
        score += 4
    if aspect_ratio and aspect_ratio.upper() in _terms(image.tags, image.descricao):
        score += 6

    score -= min(18, image.vezes_usada * 2)
    if image.ultima_utilizacao and image.ultima_utilizacao >= timezone.now() - timedelta(days=7):
        score -= 18
    return max(0, min(100, float(score)))


def resolve_slide_media(profile, *, media_intent='', visual_intent='', preferred_layout='AUTO', aspect_ratio='SQUARE', media_required=False, exclude_image_ids=None):
    policy = profile.ai_image_policy
    if not media_required and not media_intent:
        return MediaResolutionResult(status=STATUS_FULL_TEXT, reason='Slide textual sem necessidade de midia.')

    queryset = SocialBaseImage.objects.filter(profile=profile, ativa=True)
    if exclude_image_ids:
        queryset = queryset.exclude(id__in=exclude_image_ids)
    candidates = list(
        queryset
        .prefetch_related('protected_regions')
        .order_by('vezes_usada', 'ultima_utilizacao', 'id')[:80]
    )
    scored = [
        (image, _score_image(image, media_intent=media_intent, visual_intent=visual_intent, preferred_layout=preferred_layout, aspect_ratio=aspect_ratio))
        for image in candidates
    ]
    scored.sort(key=lambda item: (-item[1], item[0].vezes_usada, item[0].id))
    best_image, best_score = scored[0] if scored else (None, 0)

    if not media_required:
        if best_image and best_score >= settings.SOCIAL_MEDIA_MATCH_MIN_SCORE:
            return MediaResolutionResult(status=STATUS_SELECTED, image=best_image, score=best_score, reason='Midia opcional atendida pelo banco.')
        return MediaResolutionResult(status=STATUS_FULL_TEXT, score=best_score, reason='Midia opcional sem gasto de IA.')

    if policy == SocialProfile.AIImagePolicy.NONE:
        if best_image and best_score >= settings.SOCIAL_MEDIA_MATCH_MIN_SCORE:
            return MediaResolutionResult(status=STATUS_SELECTED, image=best_image, score=best_score, reason='Politica sem geracao; usando melhor midia do banco.')
        return MediaResolutionResult(status=STATUS_FULL_TEXT if not media_required else STATUS_UNAVAILABLE, score=best_score, reason='Sem geracao de IA habilitada.')

    if policy == SocialProfile.AIImagePolicy.BANK_ONLY:
        if best_image:
            return MediaResolutionResult(status=STATUS_SELECTED, image=best_image, score=best_score, reason='Politica BANK_ONLY.')
        return MediaResolutionResult(status=STATUS_FULL_TEXT if not media_required else STATUS_UNAVAILABLE, reason='Banco de midia vazio.')

    if policy == SocialProfile.AIImagePolicy.AI_ALWAYS and profile.ai_image_generation_enabled:
        return MediaResolutionResult(status=STATUS_NEEDS_GENERATION, score=best_score, reason='Politica AI_ALWAYS.')

    if best_image and best_score >= settings.SOCIAL_MEDIA_MATCH_MIN_SCORE:
        return MediaResolutionResult(status=STATUS_SELECTED, image=best_image, score=best_score, reason='Midia do banco atingiu score minimo.')

    if profile.ai_image_generation_enabled and policy == SocialProfile.AIImagePolicy.AI_WHEN_NEEDED:
        return MediaResolutionResult(status=STATUS_NEEDS_GENERATION, score=best_score, reason='Midia do banco abaixo do score minimo.')

    return MediaResolutionResult(status=STATUS_FULL_TEXT if not media_required else STATUS_UNAVAILABLE, score=best_score, reason='Nenhuma midia adequada encontrada.')


def recent_media_ids(profile, days=7):
    since = timezone.now() - timedelta(days=days)
    return set(
        SocialContent.objects.filter(profile=profile, created_at__gte=since, base_image__isnull=False)
        .values_list('base_image_id', flat=True)
    )
