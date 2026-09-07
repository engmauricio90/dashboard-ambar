from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
import logging

from django.db import transaction
from django.db.models import Q

from .models import SocialCarouselGenerationRun, SocialCarouselSlide, SocialContent, SocialProfile, SocialPublishAttempt
from .scheduler import estoque_alvo_profile, estoque_minimo_profile, estoque_reservado_por_tipo


logger = logging.getLogger(__name__)

KEEP = 'KEEP'
LIKELY_RUNAWAY_EMPTY = 'LIKELY_RUNAWAY_EMPTY'
LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL = 'LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL'
LIKELY_RUNAWAY = LIKELY_RUNAWAY_EMPTY
REVIEW_REQUIRED = 'REVIEW_REQUIRED'
UNSAFE_TO_DELETE = 'UNSAFE_TO_DELETE'

RUNAWAY_CLASSIFICATIONS = {LIKELY_RUNAWAY_EMPTY, LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL}
CLEANUP_EXECUTABLE_CLASSIFICATIONS = {LIKELY_RUNAWAY_EMPTY}
SUMMARY_CLASSIFICATIONS = [
    KEEP,
    LIKELY_RUNAWAY_EMPTY,
    LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL,
    REVIEW_REQUIRED,
    UNSAFE_TO_DELETE,
]

PROTECTED_CONTENT_STATUSES = {
    SocialContent.Status.PUBLICADO,
    SocialContent.Status.AGENDADO,
    SocialContent.Status.PUBLICANDO,
    SocialContent.Status.PUBLISH_CONFIRMATION_PENDING,
    SocialContent.Status.RETRY_LIBERADO_MANUAL,
}
UNSAFE_CONTENT_STATUSES = {
    SocialContent.Status.PUBLICANDO,
    SocialContent.Status.PUBLISH_CONFIRMATION_PENDING,
    SocialContent.Status.RETRY_LIBERADO_MANUAL,
}
PROTECTED_ATTEMPT_STATUSES = {
    SocialPublishAttempt.Status.PROVIDER_CALLED,
    SocialPublishAttempt.Status.AMBIGUOUS,
    SocialPublishAttempt.Status.CONFIRMED,
}
BURST_INTERVAL = timedelta(minutes=5)
BURST_TOLERANCE = timedelta(minutes=2)
MIN_BURST_SIZE = 5


@dataclass
class BurstCluster:
    id: int
    profile_id: int
    start: object
    end: object
    content_ids: list[int]
    types: Counter = field(default_factory=Counter)

    @property
    def size(self):
        return len(self.content_ids)


@dataclass
class ContentForensics:
    content_id: int
    origin: str
    status: str
    media_type: str
    scheduled: bool
    generation_mode: str = ''
    run_id: int | None = None
    run_status: str = ''
    total_slides: int = 0
    pending_slides: int = 0
    composing_slides: int = 0
    reviewing_slides: int = 0
    ready_slides: int = 0
    error_slides: int = 0
    needs_recompose_slides: int = 0
    source_assets: int = 0
    raw_assets: int = 0
    ai_composed_assets: int = 0
    rendered_assets: int = 0
    reviewed_slides: int = 0
    useful_asset_count: int = 0
    publish_attempt_count: int = 0
    external_post_id: bool = False
    burst_cluster_id: int | None = None
    burst_size: int = 0
    reserved_excess_ratio: float = 0.0


@dataclass
class BacklogItem:
    content: SocialContent
    classification: str
    reasons: list[str] = field(default_factory=list)
    forensics: ContentForensics | None = None


class CleanupRunawayError(Exception):
    pass


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
    bursts, burst_by_content = detect_bursts(contents)
    by_profile = {}
    for profile in profiles:
        profile_contents = [content for content in contents if content.profile_id == profile.id]
        reserved_total = sum(estoque_reservado_por_tipo(profile).values())
        target = estoque_alvo_profile(profile)
        items = [
            classify_content(
                content,
                burst_by_content=burst_by_content,
                target=target,
                reserved_total=reserved_total,
            )
            for content in profile_contents
        ]
        profile_bursts = [cluster for cluster in bursts if cluster.profile_id == profile.id]
        by_profile[profile.id] = {
            'profile': profile,
            'items': items,
            'bursts': profile_bursts,
            'summary': summarize_items(profile, items, bursts=profile_bursts, reserved_total=reserved_total, target=target),
        }
    return by_profile


def summarize_items(profile, items, *, bursts=None, reserved_total=None, target=None):
    bursts = bursts or []
    classifications = Counter(item.classification for item in items)
    by_status = Counter(item.content.status for item in items)
    by_type = Counter(item.content.media_type for item in items)
    by_origin = Counter(item.forensics.origin if item.forensics else _origin(item.content) for item in items)
    by_slot = Counter('scheduled' if item.content.scheduled_at else 'unscheduled' for item in items)
    reserved_by_type = estoque_reservado_por_tipo(profile)
    reserved_total = sum(reserved_by_type.values()) if reserved_total is None else reserved_total
    target = estoque_alvo_profile(profile) if target is None else target
    empty_candidates = classifications[LIKELY_RUNAWAY_EMPTY]
    shell_candidates = classifications[LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL]
    assets = Counter()
    for item in items:
        forensic = item.forensics
        if not forensic:
            continue
        if forensic.useful_asset_count <= 0:
            assets['zero_useful_assets'] += 1
        if forensic.pending_slides and forensic.ready_slides == 0 and forensic.useful_asset_count == 0:
            assets['only_pending_slides'] += 1
        if forensic.ready_slides:
            assets['at_least_one_ready'] += 1
        if forensic.source_assets or forensic.ai_composed_assets or forensic.rendered_assets:
            assets['at_least_one_final_asset'] += 1
    return {
        'total': len(items),
        'classifications': classifications,
        'by_status': by_status,
        'by_type': by_type,
        'by_origin': by_origin,
        'by_slot': by_slot,
        'reserved_by_type': reserved_by_type,
        'reserved_total': reserved_total,
        'target': target,
        'minimum': estoque_minimo_profile(profile),
        'bursts': bursts,
        'asset_summary': assets,
        'cleanup_empty_after_reserved': max(0, reserved_total - empty_candidates),
        'cleanup_empty_shell_after_reserved': max(0, reserved_total - empty_candidates - shell_candidates),
    }


def classify_content(content, *, burst_by_content=None, target=0, reserved_total=0):
    burst_by_content = burst_by_content or {}
    forensics = build_forensics(content, burst_by_content=burst_by_content, target=target, reserved_total=reserved_total)
    reasons = []
    attempt_statuses = {attempt.status for attempt in content.publish_attempts.all()}
    if content.status in PROTECTED_CONTENT_STATUSES:
        reasons.append('status_protegido')
        classification = UNSAFE_TO_DELETE if content.status in UNSAFE_CONTENT_STATUSES else KEEP
        return BacklogItem(content, classification, reasons, forensics)
    if content.external_post_id:
        reasons.append('external_post_id')
        return BacklogItem(content, UNSAFE_TO_DELETE, reasons, forensics)
    if attempt_statuses & PROTECTED_ATTEMPT_STATUSES:
        reasons.append('publish_attempt_meta_relevante')
        return BacklogItem(content, UNSAFE_TO_DELETE, reasons, forensics)
    if content.status == SocialContent.Status.APROVADO:
        reasons.append('aprovado')
        return BacklogItem(content, KEEP, reasons, forensics)
    if forensics.origin == 'manual':
        reasons.append('origem_manual')
        return BacklogItem(content, REVIEW_REQUIRED, reasons, forensics)
    if forensics.useful_asset_count > 0 or forensics.ready_slides > 0 or forensics.reviewed_slides > 0:
        reasons.extend(_useful_reasons(forensics))
        return BacklogItem(content, REVIEW_REQUIRED, reasons, forensics)
    if _is_burst_runaway(forensics):
        reasons.extend(_runaway_reasons(forensics))
        if _has_technical_shell(forensics):
            return BacklogItem(content, LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL, reasons, forensics)
        return BacklogItem(content, LIKELY_RUNAWAY_EMPTY, reasons, forensics)
    return BacklogItem(content, REVIEW_REQUIRED, ['revisao_manual'], forensics)


def build_forensics(content, *, burst_by_content=None, target=0, reserved_total=0):
    burst_by_content = burst_by_content or {}
    slides = list(content.carousel_slides.all())
    runs = list(content.carousel_generation_runs.all())
    latest_run = sorted(runs, key=lambda run: (run.started_at, run.id), reverse=True)[0] if runs else None
    slide_counts = Counter(slide.ai_composition_status for slide in slides)
    reviewed_slides = sum(1 for slide in slides if slide.ai_review_metadata)
    source_assets = sum(1 for slide in slides if slide.source_image)
    ai_composed_assets = sum(1 for slide in slides if slide.ai_composed_image)
    rendered_assets = sum(1 for slide in slides if slide.rendered_image)
    raw_assets = sum(1 for slide in slides if (slide.ai_composition_metadata or {}).get('composed_raw'))
    useful_asset_count = (
        int(bool(content.final_image))
        + int(bool(content.final_video))
        + source_assets
        + raw_assets
        + ai_composed_assets
        + rendered_assets
    )
    cluster = burst_by_content.get(content.id)
    return ContentForensics(
        content_id=content.id,
        origin=_origin(content),
        status=content.status,
        media_type=content.media_type,
        scheduled=bool(content.scheduled_at),
        generation_mode=latest_run.generation_mode if latest_run else '',
        run_id=latest_run.id if latest_run else None,
        run_status=latest_run.status if latest_run else '',
        total_slides=len(slides),
        pending_slides=slide_counts[SocialCarouselSlide.CompositionStatus.PENDING],
        composing_slides=slide_counts[SocialCarouselSlide.CompositionStatus.COMPOSING],
        reviewing_slides=slide_counts[SocialCarouselSlide.CompositionStatus.REVIEWING],
        ready_slides=slide_counts[SocialCarouselSlide.CompositionStatus.READY],
        error_slides=slide_counts[SocialCarouselSlide.CompositionStatus.ERROR],
        needs_recompose_slides=slide_counts[SocialCarouselSlide.CompositionStatus.NEEDS_RECOMPOSE],
        source_assets=source_assets,
        raw_assets=raw_assets,
        ai_composed_assets=ai_composed_assets,
        rendered_assets=rendered_assets,
        reviewed_slides=reviewed_slides,
        useful_asset_count=useful_asset_count,
        publish_attempt_count=len(content.publish_attempts.all()),
        external_post_id=bool(content.external_post_id),
        burst_cluster_id=cluster.id if cluster else None,
        burst_size=cluster.size if cluster else 0,
        reserved_excess_ratio=(reserved_total / target) if target else 0,
    )


def detect_bursts(contents):
    clusters = []
    burst_by_content = {}
    cluster_id = 1
    grouped = defaultdict(list)
    for content in contents:
        if _origin(content) == 'auto' and content.status in {SocialContent.Status.RASCUNHO, SocialContent.Status.ERRO}:
            grouped[(content.profile_id, content.media_type)].append(content)
    for (profile_id, _media_type), group in grouped.items():
        ordered = sorted(group, key=lambda item: (item.created_at, item.id))
        current = []
        for content in ordered:
            if not current:
                current = [content]
                continue
            previous = current[-1]
            delta = content.created_at - previous.created_at
            if timedelta(0) <= delta <= BURST_INTERVAL + BURST_TOLERANCE:
                current.append(content)
            else:
                cluster_id = _finalize_cluster(current, clusters, burst_by_content, cluster_id, profile_id)
                current = [content]
        cluster_id = _finalize_cluster(current, clusters, burst_by_content, cluster_id, profile_id)
    return clusters, burst_by_content


def cleanup_runaway(profile, *, execute=False, content_type='', include_technical_shell=False, expected_count=None, confirm_profile=''):
    audit = audit_backlog(profile_id=profile.id, content_type=content_type)[profile.id]
    executable_classifications = set(CLEANUP_EXECUTABLE_CLASSIFICATIONS)
    if include_technical_shell:
        executable_classifications.add(LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL)
    candidates_by_classification = Counter(item.classification for item in audit['items'] if item.classification in executable_classifications)
    candidates = [item.content for item in audit['items'] if item.classification in executable_classifications]
    burst_by_content = {
        content_id: cluster
        for cluster in audit.get('bursts', [])
        for content_id in cluster.content_ids
    }
    before_reserved = audit['summary']['reserved_total']
    hypothetical_deleted = len(candidates)
    after_reserved = max(0, before_reserved - hypothetical_deleted)
    technical_shell_eligible = candidates_by_classification[LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL]
    result = {
        'profile': profile,
        'execute': execute,
        'include_technical_shell': include_technical_shell,
        'before_reserved': before_reserved,
        'hypothetical_deleted': hypothetical_deleted,
        'after_reserved': after_reserved,
        'target': audit['summary']['target'],
        'minimum': audit['summary']['minimum'],
        'deleted': 0,
        'files_deleted': 0,
        'protected_skipped': len(audit['items']) - hypothetical_deleted,
        'eligible_empty': candidates_by_classification[LIKELY_RUNAWAY_EMPTY],
        'eligible_technical_shell': technical_shell_eligible,
        'review_required': audit['summary']['classifications'][REVIEW_REQUIRED],
        'protected': audit['summary']['classifications'][KEEP] + audit['summary']['classifications'][UNSAFE_TO_DELETE],
        'candidate_ids': [content.id for content in candidates],
        'burst_count': len(audit.get('bursts', [])),
        'bursts': audit.get('bursts', []),
    }
    if not execute:
        return result
    if include_technical_shell:
        if expected_count is None:
            raise CleanupRunawayError('Cleanup TECHNICAL_SHELL exige --expected-count.')
        if technical_shell_eligible != expected_count:
            raise CleanupRunawayError(
                'Quantidade elegivel mudou desde a auditoria.\n'
                f'Esperado: {expected_count}\n'
                f'Atual: {technical_shell_eligible}\n'
                'Cleanup cancelado.'
            )
        if _normalize_username(confirm_profile) != _normalize_username(profile.username):
            raise CleanupRunawayError('Confirmacao de perfil invalida. Cleanup cancelado.')
    if profile.modo_operacao == SocialProfile.ModoOperacao.AUTOMATICO:
        logger.warning(
            'social_runaway_cleanup_profile_automatic profile_id=%s username=%s',
            profile.id,
            profile.username,
        )
    logger.warning(
        'social_runaway_cleanup_manifest profile_id=%s username=%s execute=%s include_technical_shell=%s '
        'eligible_empty=%s eligible_technical_shell=%s candidate_ids=%s reserved_before=%s reserved_after=%s target=%s minimum=%s',
        profile.id,
        profile.username,
        execute,
        include_technical_shell,
        result['eligible_empty'],
        result['eligible_technical_shell'],
        result['candidate_ids'],
        before_reserved,
        after_reserved,
        result['target'],
        result['minimum'],
    )
    with transaction.atomic():
        for content in candidates:
            locked = SocialContent.objects.select_for_update().prefetch_related('publish_attempts', 'carousel_slides', 'carousel_generation_runs', 'events').get(pk=content.pk)
            checked = classify_content(locked, burst_by_content=burst_by_content, target=estoque_alvo_profile(profile), reserved_total=before_reserved)
            if checked.classification not in executable_classifications or _has_delete_protection(locked) or checked.forensics.useful_asset_count:
                continue
            SocialCarouselGenerationRun.objects.filter(content=locked).delete()
            locked.delete()
            result['deleted'] += 1
    return result


def _normalize_username(username):
    return (username or '').strip().lstrip('@').lower()


def _finalize_cluster(contents, clusters, burst_by_content, cluster_id, profile_id):
    if len(contents) < MIN_BURST_SIZE:
        return cluster_id
    cluster = BurstCluster(
        id=cluster_id,
        profile_id=profile_id,
        start=contents[0].created_at,
        end=contents[-1].created_at,
        content_ids=[content.id for content in contents],
        types=Counter(content.media_type for content in contents),
    )
    clusters.append(cluster)
    for content in contents:
        burst_by_content[content.id] = cluster
    return cluster_id + 1


def _is_burst_runaway(forensics):
    if forensics.origin != 'auto':
        return False
    if forensics.status != SocialContent.Status.RASCUNHO:
        return False
    if forensics.scheduled:
        return False
    if forensics.publish_attempt_count or forensics.external_post_id:
        return False
    if forensics.useful_asset_count or forensics.ready_slides or forensics.reviewed_slides:
        return False
    burst_signal = forensics.burst_size >= MIN_BURST_SIZE
    excess_signal = forensics.reserved_excess_ratio >= 1.5
    return burst_signal and excess_signal


def _has_technical_shell(forensics):
    return bool(forensics.run_id or forensics.total_slides or forensics.generation_mode)


def _has_delete_protection(content):
    if content.status in PROTECTED_CONTENT_STATUSES:
        return True
    if content.external_post_id:
        return True
    return content.publish_attempts.filter(status__in=PROTECTED_ATTEMPT_STATUSES).exists()


def _useful_reasons(forensics):
    reasons = ['trabalho_util']
    if forensics.useful_asset_count:
        reasons.append(f'useful_asset_count={forensics.useful_asset_count}')
    if forensics.ready_slides:
        reasons.append(f'ready_slides={forensics.ready_slides}')
    if forensics.reviewed_slides:
        reasons.append(f'reviewed_slides={forensics.reviewed_slides}')
    return reasons


def _runaway_reasons(forensics):
    reasons = [
        'auto',
        'unscheduled',
        f'burst_cluster={forensics.burst_cluster_id}',
        f'burst_size={forensics.burst_size}',
        f'useful_asset_count={forensics.useful_asset_count}',
    ]
    if forensics.total_slides:
        reasons.append(f'slides={forensics.total_slides}')
    if forensics.pending_slides:
        reasons.append(f'pending_slides={forensics.pending_slides}')
    if forensics.reserved_excess_ratio:
        reasons.append(f'reserved_stock={forensics.reserved_excess_ratio:.2f}x_target')
    return reasons


def _origin(content):
    if content.events.filter(acao='gerado_ia').exists() or content.carousel_generation_runs.all():
        return 'auto'
    return 'manual'
