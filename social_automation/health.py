from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from .models import SocialAIUsage, SocialAutomationTick, SocialCarouselGenerationRun, SocialCarouselSlide, SocialContent, SocialInstagramConnection, SocialProfile, SocialPublishAttempt
from .scheduler import estoque_alvo_profile, estoque_em_andamento_por_tipo, estoque_minimo_profile, estoque_pronto_por_tipo, estoque_reservado_por_tipo, proxima_publicacao


HEALTHY = 'SAUDAVEL'
ATTENTION = 'ATENCAO'
BLOCKED = 'BLOQUEADO'
INACTIVE = 'INATIVO'

TICK_ATTENTION_AFTER = timedelta(minutes=10)
TICK_BLOCKED_AFTER = timedelta(minutes=20)
RUN_STALE_AFTER = timedelta(minutes=45)
CONTENT_STALE_AFTER = timedelta(minutes=20)
NEAR_LIMIT_RATIO = 0.8


@dataclass
class ProfileHealth:
    profile: SocialProfile
    status: str
    reasons: list[str] = field(default_factory=list)
    mode: str = ''
    instagram: str = ''
    next_posts: list[SocialContent] = field(default_factory=list)
    next_post_local: str = ''
    ready_stock: int = 0
    reserved_stock: int = 0
    in_progress_stock: int = 0
    target_stock: int = 0
    minimum_stock: int = 0
    ready_by_type: dict = field(default_factory=dict)
    reserved_by_type: dict = field(default_factory=dict)
    in_progress_by_type: dict = field(default_factory=dict)
    ai_used_today: int = 0
    ai_effective_limit: int = 0
    ai_remaining_today: int = 0
    ai_near_limit: bool = False
    content_counts: dict = field(default_factory=dict)
    run_counts: dict = field(default_factory=dict)
    slide_counts: dict = field(default_factory=dict)
    latest_error: str = ''
    latest_attempt: SocialPublishAttempt | None = None


@dataclass
class SystemHealth:
    status: str
    reasons: list[str]
    last_tick: SocialAutomationTick | None
    tick_age_minutes: int | None
    active_runs: int
    ambiguous_publications: int
    content_errors: int
    ai_usage_global: dict


def build_social_health(now=None):
    now = now or timezone.now()
    profiles = list(
        SocialProfile.objects.select_related('instagram_connection')
        .order_by('nome', 'id')
    )
    usage_by_profile, usage_global = _ai_usage_maps(now)
    content_counts = _content_count_map()
    run_counts = _run_count_map()
    slide_counts = _slide_count_map()
    latest_attempts = _latest_attempt_map()
    profile_cards = [
        build_profile_health(
            profile,
            now=now,
            usage=usage_by_profile.get(profile.id, {}),
            content_counts=content_counts.get(profile.id, {}),
            run_counts=run_counts.get(profile.id, {}),
            slide_counts=slide_counts.get(profile.id, {}),
            latest_attempt=latest_attempts.get(profile.id),
        )
        for profile in profiles
    ]
    system = build_system_health(now=now, usage_global=usage_global)
    summary = {
        'active_profiles': sum(1 for item in profile_cards if item.profile.ativo),
        'healthy_profiles': sum(1 for item in profile_cards if item.status == HEALTHY),
        'attention_profiles': sum(1 for item in profile_cards if item.status == ATTENTION),
        'blocked_profiles': sum(1 for item in profile_cards if item.status == BLOCKED),
        'inactive_profiles': sum(1 for item in profile_cards if item.status == INACTIVE),
        'scheduled_contents': SocialContent.objects.filter(status=SocialContent.Status.AGENDADO).count(),
        'error_contents': SocialContent.objects.filter(status=SocialContent.Status.ERRO).count(),
        'active_runs': system.active_runs,
        'stale_runs': _stale_runs(now).count(),
        'pending_confirmations': system.ambiguous_publications,
        'next_content': SocialContent.objects.select_related('profile').filter(status=SocialContent.Status.AGENDADO, scheduled_at__gte=now).order_by('scheduled_at', 'id').first(),
    }
    return {'summary': summary, 'profiles': profile_cards, 'system': system}


def build_profile_health(profile, *, now=None, usage=None, content_counts=None, run_counts=None, slide_counts=None, latest_attempt=None):
    now = now or timezone.now()
    if usage is None:
        usage = _ai_usage_maps(now)[0].get(profile.id, {})
    if content_counts is None:
        content_counts = _content_count_map().get(profile.id, {})
    if run_counts is None:
        run_counts = _run_count_map().get(profile.id, {})
    if slide_counts is None:
        slide_counts = _slide_count_map().get(profile.id, {})
    if latest_attempt is None:
        latest_attempt = _latest_attempt_map().get(profile.id)
    usage = usage or {}
    content_counts = defaultdict(int, content_counts or {})
    run_counts = defaultdict(int, run_counts or {})
    slide_counts = defaultdict(int, slide_counts or {})
    reasons = []

    if not profile.ativo:
        return ProfileHealth(profile=profile, status=INACTIVE, reasons=['Perfil inativo.'], mode=profile.get_modo_operacao_display(), instagram=_instagram_status(profile))

    timezone_ok = _profile_timezone_ok(profile)
    if not timezone_ok:
        reasons.append('Timezone do perfil invalido.')

    instagram_status = _instagram_status(profile)
    if profile.plataforma == SocialProfile.Plataforma.INSTAGRAM and profile.modo_operacao == SocialProfile.ModoOperacao.AUTOMATICO and instagram_status != 'Conectado':
        reasons.append('Instagram necessario e nao conectado.')

    ready_by_type = estoque_pronto_por_tipo(profile)
    reserved_by_type = estoque_reservado_por_tipo(profile, now=now)
    in_progress_by_type = estoque_em_andamento_por_tipo(profile, now=now)
    ready_stock = sum(ready_by_type.values())
    reserved_stock = sum(reserved_by_type.values())
    in_progress_stock = sum(in_progress_by_type.values())
    minimum_stock = estoque_minimo_profile(profile)
    target_stock = estoque_alvo_profile(profile)

    if profile.modo_operacao == SocialProfile.ModoOperacao.AUTOMATICO:
        if reserved_stock < minimum_stock:
            reasons.append('Estoque reservado abaixo do minimo.')
        elif reserved_stock < target_stock:
            reasons.append('Estoque reservado abaixo da meta.')
        if not proxima_publicacao(profile, now=now):
            reasons.append('Nenhum conteudo futuro agendado.')
    elif profile.modo_operacao == SocialProfile.ModoOperacao.MANUAL:
        reasons.append('Perfil em modo manual.')

    pending_confirmations = content_counts[SocialContent.Status.PUBLISH_CONFIRMATION_PENDING]
    if pending_confirmations:
        reasons.append(f'{pending_confirmations} publicacao pendente de confirmacao.')

    stale_content = _stale_contents(now).filter(profile=profile).count()
    if stale_content:
        reasons.append(f'{stale_content} conteudo em publicacao ha tempo excessivo.')

    max_retries = getattr(settings, 'SOCIAL_AUTOMATION_MAX_RETRIES', 3)
    terminal_errors = profile.contents.filter(status=SocialContent.Status.ERRO, tentativas__gte=max_retries).count()
    recoverable_errors = max(0, content_counts[SocialContent.Status.ERRO] - terminal_errors)
    if terminal_errors:
        reasons.append(f'{terminal_errors} erro de publicacao sem retry automatico.')
    elif recoverable_errors:
        reasons.append(f'{recoverable_errors} erro recuperavel.')

    partial_runs = run_counts[SocialCarouselGenerationRun.Status.PARTIAL]
    error_runs = run_counts[SocialCarouselGenerationRun.Status.ERROR]
    stale_runs = _stale_runs(now).filter(profile=profile).count()
    if stale_runs:
        reasons.append(f'{stale_runs} run AI_FINISHED travada.')
    elif error_runs:
        reasons.append(f'{error_runs} run AI_FINISHED com erro.')
    elif partial_runs:
        reasons.append(f'{partial_runs} run AI_FINISHED parcial.')

    ai_limit = _effective_ai_limit(profile)
    ai_used = sum(usage.values())
    ai_remaining = max(0, ai_limit - ai_used)
    ai_near_limit = bool(ai_limit and ai_used >= ai_limit * NEAR_LIMIT_RATIO)
    if _profile_uses_ai_images(profile) and ai_limit and ai_remaining <= 0:
        reasons.append('Limite diario de IA visual atingido.')
    elif ai_near_limit:
        reasons.append('Uso de IA visual proximo do limite.')

    next_posts = list(profile.contents.filter(status=SocialContent.Status.AGENDADO, scheduled_at__gte=now).order_by('scheduled_at', 'id')[:2])
    next_post_local = _format_profile_datetime(profile, next_posts[0].scheduled_at) if next_posts else ''
    latest_error = _latest_error(profile)

    blocked_terms = ['pendente de confirmacao', 'nao conectado', 'travada', 'tempo excessivo', 'sem retry', 'atingido', 'Timezone']
    status = BLOCKED if any(any(term in reason for term in blocked_terms) for reason in reasons) else (ATTENTION if reasons else HEALTHY)

    return ProfileHealth(
        profile=profile,
        status=status,
        reasons=reasons,
        mode=profile.get_modo_operacao_display(),
        instagram=instagram_status,
        next_posts=next_posts,
        next_post_local=next_post_local,
        ready_stock=ready_stock,
        reserved_stock=reserved_stock,
        in_progress_stock=in_progress_stock,
        target_stock=target_stock,
        minimum_stock=minimum_stock,
        ready_by_type=ready_by_type,
        reserved_by_type=reserved_by_type,
        in_progress_by_type=in_progress_by_type,
        ai_used_today=ai_used,
        ai_effective_limit=ai_limit,
        ai_remaining_today=ai_remaining,
        ai_near_limit=ai_near_limit,
        content_counts=dict(content_counts),
        run_counts=dict(run_counts),
        slide_counts=dict(slide_counts),
        latest_error=latest_error,
        latest_attempt=latest_attempt,
    )


def build_system_health(*, now=None, usage_global=None):
    now = now or timezone.now()
    usage_global = usage_global or {}
    last_tick = SocialAutomationTick.objects.order_by('-started_at', '-id').first()
    reasons = []
    tick_age_minutes = None
    if not last_tick:
        reasons.append('Nenhum tick registrado.')
    else:
        base = last_tick.finished_at or last_tick.started_at
        tick_age = now - base
        tick_age_minutes = max(0, int(tick_age.total_seconds() // 60))
        if last_tick.status == SocialAutomationTick.Status.ERROR:
            reasons.append('Ultimo tick terminou com erro.')
        if tick_age > TICK_BLOCKED_AFTER:
            reasons.append('Cron muito atrasado.')
        elif tick_age > TICK_ATTENTION_AFTER:
            reasons.append('Cron atrasado.')
    active_runs = SocialCarouselGenerationRun.objects.filter(status__in=_active_run_statuses()).count()
    ambiguous = SocialContent.objects.filter(status=SocialContent.Status.PUBLISH_CONFIRMATION_PENDING).count()
    errors = SocialContent.objects.filter(status=SocialContent.Status.ERRO).count()
    if ambiguous:
        reasons.append(f'{ambiguous} publicacao pendente de confirmacao.')
    if _stale_runs(now).exists():
        reasons.append('Existem runs em andamento ha tempo excessivo.')
    status = BLOCKED if any(term in ' '.join(reasons) for term in ['muito atrasado', 'pendente de confirmacao', 'erro', 'tempo excessivo']) else (ATTENTION if reasons else HEALTHY)
    return SystemHealth(status=status, reasons=reasons, last_tick=last_tick, tick_age_minutes=tick_age_minutes, active_runs=active_runs, ambiguous_publications=ambiguous, content_errors=errors, ai_usage_global=usage_global)


def _ai_usage_maps(now):
    today = timezone.localdate(now)
    rows = (
        SocialAIUsage.objects.filter(success=True, created_at__date=today)
        .values('profile_id', 'operation')
        .annotate(total=Count('id'))
    )
    by_profile = defaultdict(dict)
    global_usage = defaultdict(int)
    for row in rows:
        by_profile[row['profile_id']][row['operation']] = row['total']
        global_usage[row['operation']] += row['total']
    return by_profile, dict(global_usage)


def _content_count_map():
    rows = SocialContent.objects.values('profile_id', 'status').annotate(total=Count('id'))
    data = defaultdict(dict)
    for row in rows:
        data[row['profile_id']][row['status']] = row['total']
    return data


def _run_count_map():
    rows = SocialCarouselGenerationRun.objects.values('profile_id', 'status').annotate(total=Count('id'))
    data = defaultdict(dict)
    for row in rows:
        data[row['profile_id']][row['status']] = row['total']
    return data


def _slide_count_map():
    rows = SocialCarouselSlide.objects.filter(is_active=True).values('content__profile_id', 'ai_composition_status').annotate(total=Count('id'))
    data = defaultdict(dict)
    for row in rows:
        data[row['content__profile_id']][row['ai_composition_status']] = row['total']
    return data


def _latest_attempt_map():
    attempts = SocialPublishAttempt.objects.select_related('content', 'content__profile').order_by('content__profile_id', '-started_at', '-id')
    data = {}
    for attempt in attempts:
        data.setdefault(attempt.content.profile_id, attempt)
    return data


def _instagram_status(profile):
    try:
        connection = profile.instagram_connection
    except SocialInstagramConnection.DoesNotExist:
        return 'Nao conectado'
    if not connection.is_active:
        return 'Nao conectado'
    if connection.last_validation_status == SocialInstagramConnection.ValidationStatus.ERRO:
        return 'Erro de validacao'
    return 'Conectado'


def _effective_ai_limit(profile):
    profile_limit = profile.ai_image_daily_limit or getattr(settings, 'SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY', 0)
    global_limit = getattr(settings, 'SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY', profile_limit)
    return min(profile_limit, global_limit) if global_limit else profile_limit


def _profile_uses_ai_images(profile):
    return bool(profile.ai_image_generation_enabled and profile.ai_image_policy not in {SocialProfile.AIImagePolicy.NONE, SocialProfile.AIImagePolicy.BANK_ONLY})


def _active_run_statuses():
    return [
        SocialCarouselGenerationRun.Status.IDEATING,
        SocialCarouselGenerationRun.Status.IDEA_SELECTED,
        SocialCarouselGenerationRun.Status.BLUEPRINT_READY,
        SocialCarouselGenerationRun.Status.EDITORIAL_APPROVED,
        SocialCarouselGenerationRun.Status.COMPOSING,
        SocialCarouselGenerationRun.Status.REVIEWING,
    ]


def _stale_runs(now):
    return SocialCarouselGenerationRun.objects.filter(status__in=_active_run_statuses(), started_at__lt=now - RUN_STALE_AFTER, finished_at__isnull=True)


def _stale_contents(now):
    return SocialContent.objects.filter(status=SocialContent.Status.PUBLICANDO, updated_at__lt=now - CONTENT_STALE_AFTER)


def _latest_error(profile):
    content = profile.contents.filter(Q(status=SocialContent.Status.ERRO) | Q(erro__gt='')).order_by('-updated_at', '-id').first()
    if content and content.erro:
        return str(content.erro)[:180]
    run = profile.carousel_generation_runs.exclude(error='').order_by('-started_at', '-id').first()
    if run and run.error:
        return str(run.error)[:180]
    return ''


def _profile_timezone_ok(profile):
    try:
        ZoneInfo(profile.timezone)
        return True
    except ZoneInfoNotFoundError:
        return False


def _format_profile_datetime(profile, value):
    if not value:
        return ''
    try:
        zone = ZoneInfo(profile.timezone)
    except ZoneInfoNotFoundError:
        zone = timezone.get_current_timezone()
    return timezone.localtime(value, zone).strftime('%d/%m %H:%M')
