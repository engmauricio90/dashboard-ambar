from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q

from .models import SocialCarouselGenerationRun, SocialCarouselSlide, SocialContent, SocialContentEvent, SocialProfile, SocialPublishAttempt
from .scheduler import estoque_alvo_profile, estoque_minimo_profile, estoque_reservado_por_tipo


KEEP = 'KEEP'
LIKELY_RUNAWAY = 'LIKELY_RUNAWAY'
REVIEW_REQUIRED = 'REVIEW_REQUIRED'
UNSAFE_TO_DELETE = 'UNSAFE_TO_DELETE'

PROTECTED_CONTENT_STATUSES = {
    SocialContent.Status.PUBLICADO,
    SocialContent.Status.AGENDADO,
    SocialContent.Status.PUBLICANDO,
    SocialContent.Status.PUBLISH_CONFIRMATION_PENDING,
}
PROTECTED_ATTEMPT_STATUSES = {
    SocialPublishAttempt.Status.PROVIDER_CALLED,
    SocialPublishAttempt.Status.AMBIGUOUS,
    SocialPublishAttempt.Status.CONFIRMED,
}


@dataclass
class BacklogItem:
    content: SocialContent
    classification: str
    reasons: list[str] = field(default_factory=list)


def filtered_profiles(profile_id=None, username=''):
    profiles = SocialProfile.objects.order_by('username', 'id')
    if profile_id:
        profiles = profiles.filter(id=profile_id)
    if username:
        username = username.lstrip('@')
        profiles = profiles.filter(Q(username__iexact=username) | Q(username__iexact=f'@{username}'))
    return profiles


def audit_backlog(profile_id=None, username='', content_type=''):
    profiles = list(filtered_profiles(profile_id=profile_id, username=username))
    profile_ids = [profile.id for profile in profiles]
    contents = (
        SocialContent.objects.filter(profile_id__in=profile_ids)
        .select_related('profile')
        .prefetch_related('events', 'publish_attempts', 'carousel_generation_runs', 'carousel_slides')
        .order_by('profile_id', 'created_at', 'id')
    )
    if content_type:
        contents = contents.filter(media_type=content_type)
    contents = list(contents)
    cluster_sizes = _cluster_sizes(contents)
    by_profile = {}
    for profile in profiles:
        profile_contents = [content for content in contents if content.profile_id == profile.id]
        items = [classify_content(content, cluster_sizes=cluster_sizes, target=estoque_alvo_profile(profile)) for content in profile_contents]
        by_profile[profile.id] = {
            'profile': profile,
            'items': items,
            'summary': summarize_items(profile, items),
        }
    return by_profile


def summarize_items(profile, items):
    classifications = Counter(item.classification for item in items)
    by_status = Counter(item.content.status for item in items)
    by_type = Counter(item.content.media_type for item in items)
    by_origin = Counter(_origin(item.content) for item in items)
    by_slot = Counter('scheduled' if item.content.scheduled_at else 'unscheduled' for item in items)
    reserved_by_type = estoque_reservado_por_tipo(profile)
    return {
        'total': len(items),
        'classifications': classifications,
        'by_status': by_status,
        'by_type': by_type,
        'by_origin': by_origin,
        'by_slot': by_slot,
        'reserved_by_type': reserved_by_type,
        'reserved_total': sum(reserved_by_type.values()),
        'target': estoque_alvo_profile(profile),
        'minimum': estoque_minimo_profile(profile),
    }


def classify_content(content, *, cluster_sizes=None, target=0):
    cluster_sizes = cluster_sizes or {}
    reasons = []
    attempt_statuses = {attempt.status for attempt in content.publish_attempts.all()}
    if content.status in PROTECTED_CONTENT_STATUSES:
        reasons.append('status_protegido')
        return BacklogItem(content, UNSAFE_TO_DELETE if content.status in {SocialContent.Status.PUBLICANDO, SocialContent.Status.PUBLISH_CONFIRMATION_PENDING} else KEEP, reasons)
    if content.external_post_id:
        reasons.append('external_post_id')
        return BacklogItem(content, UNSAFE_TO_DELETE, reasons)
    if attempt_statuses & PROTECTED_ATTEMPT_STATUSES:
        reasons.append('publish_attempt_relevante')
        return BacklogItem(content, UNSAFE_TO_DELETE, reasons)
    if content.status == SocialContent.Status.APROVADO:
        reasons.append('aprovado')
        return BacklogItem(content, KEEP, reasons)
    if _has_useful_work(content):
        reasons.append('trabalho_util')
        return BacklogItem(content, REVIEW_REQUIRED, reasons)
    if _is_likely_runaway_candidate(content, cluster_sizes=cluster_sizes, target=target):
        reasons.append('padrao_temporal_ou_excedente')
        return BacklogItem(content, LIKELY_RUNAWAY, reasons)
    return BacklogItem(content, REVIEW_REQUIRED, ['revisao_manual'])


def cleanup_runaway(profile, *, execute=False, content_type=''):
    audit = audit_backlog(profile_id=profile.id, content_type=content_type)[profile.id]
    candidates = [item.content for item in audit['items'] if item.classification == LIKELY_RUNAWAY]
    before_reserved = audit['summary']['reserved_total']
    hypothetical_deleted = len(candidates)
    after_reserved = max(0, before_reserved - hypothetical_deleted)
    result = {
        'profile': profile,
        'execute': execute,
        'before_reserved': before_reserved,
        'hypothetical_deleted': hypothetical_deleted,
        'after_reserved': after_reserved,
        'target': audit['summary']['target'],
        'minimum': audit['summary']['minimum'],
        'deleted': 0,
        'files_deleted': 0,
        'protected_skipped': len(audit['items']) - hypothetical_deleted,
        'candidate_ids': [content.id for content in candidates],
    }
    if not execute:
        return result
    with transaction.atomic():
        for content in candidates:
            locked = SocialContent.objects.select_for_update().prefetch_related('publish_attempts').get(pk=content.pk)
            if _has_delete_protection(locked) or _has_useful_work(locked):
                continue
            locked.delete()
            result['deleted'] += 1
    return result


def _cluster_sizes(contents):
    sizes = {}
    for content in contents:
        if content.status != SocialContent.Status.RASCUNHO:
            continue
        start = content.created_at - timedelta(minutes=5)
        end = content.created_at + timedelta(minutes=5)
        sizes[content.id] = sum(
            1
            for other in contents
            if other.profile_id == content.profile_id
            and other.media_type == content.media_type
            and other.status == SocialContent.Status.RASCUNHO
            and start <= other.created_at <= end
        )
    return sizes


def _is_likely_runaway_candidate(content, *, cluster_sizes, target):
    if content.status != SocialContent.Status.RASCUNHO:
        return False
    if content.scheduled_at or content.published_at:
        return False
    if not _has_auto_signal(content):
        return False
    if _has_useful_work(content):
        return False
    cluster_size = cluster_sizes.get(content.id, 0)
    return cluster_size >= 5 or bool(target and cluster_size > target)


def _has_useful_work(content):
    if content.final_image or content.final_video:
        return True
    slides = list(content.carousel_slides.all())
    if any(slide.rendered_image or slide.ai_composed_image for slide in slides):
        return True
    if any(slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.READY for slide in slides):
        return True
    if any(run.status == SocialCarouselGenerationRun.Status.READY for run in content.carousel_generation_runs.all()):
        return True
    return False


def _has_delete_protection(content):
    if content.status in PROTECTED_CONTENT_STATUSES:
        return True
    if content.external_post_id:
        return True
    return content.publish_attempts.filter(status__in=PROTECTED_ATTEMPT_STATUSES).exists()


def _has_auto_signal(content):
    if content.carousel_generation_runs.all():
        return True
    if content.events.filter(acao='gerado_ia').exists():
        return True
    return False


def _origin(content):
    if content.events.filter(acao='gerado_ia').exists() or content.carousel_generation_runs.all():
        return 'auto'
    return 'manual'
