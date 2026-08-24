from dataclasses import dataclass, field
from datetime import timedelta
import logging
import random
import time

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .generation import gerar_lote_conteudos
from .instagram import InstagramAPIError, InstagramConfigurationError, InstagramPublishError, auditar_imagem_final, publicar_conteudo_instagram
from .models import SocialContent, SocialProfile
from .scheduler import estoque_pronto, preencher_agenda, proxima_publicacao, reagendar_vencidos
from .services import registrar_evento


logger = logging.getLogger(__name__)

TICK_LOCK_KEY = 'social_automation_tick_lock'
AUTO_THEMES = [
    'trabalho',
    'salario',
    'boletos',
    'preguica',
    'sono',
    'fome',
    'comida',
    'relacionamento',
    'ciumes',
    'amizade',
    'academia',
    'banho',
    'visitas',
    'frio e calor',
    'barulho',
    'vida adulta',
    'ranco',
    'falta de paciencia',
    'situacoes cotidianas',
]


class AutoEvent:
    GERADO = 'gerado_auto'
    APROVADO = 'aprovado_auto'
    PUBLICADO = 'publicado_auto'
    ERRO = 'erro_auto'
    RETRY = 'retry_auto'
    CAP = 'cap_24h'


@dataclass
class ProfileTickSummary:
    profile: str
    profile_id: int
    published: int = 0
    scheduled: int = 0
    rescheduled: int = 0
    generated: int = 0
    approved: int = 0
    retries: int = 0
    errors: int = 0
    inventory: int = 0
    next_post: str | None = None
    status: str = 'ok'
    message: str = ''


@dataclass
class TickSummary:
    status: str = 'ok'
    started_at: str = ''
    duration_ms: int = 0
    profiles: list[ProfileTickSummary] = field(default_factory=list)

    def as_dict(self):
        return {
            'status': self.status,
            'started_at': self.started_at,
            'duration_ms': self.duration_ms,
            'profiles': [profile.__dict__ for profile in self.profiles],
        }


def executar_tick_social(*, use_lock=True, now=None):
    if use_lock and not cache.add(TICK_LOCK_KEY, timezone.now().isoformat(), settings.SOCIAL_AUTOMATION_TICK_LOCK_SECONDS):
        return TickSummary(status='already_running', started_at=timezone.now().isoformat()).as_dict()

    started = timezone.now()
    started_monotonic = time.monotonic()
    summary = TickSummary(started_at=started.isoformat())
    logger.info('social_automation.tick_start')
    try:
        profiles = SocialProfile.objects.filter(
            ativo=True,
            plataforma=SocialProfile.Plataforma.INSTAGRAM,
            modo_operacao=SocialProfile.ModoOperacao.AUTOMATICO,
        ).order_by('id')
        for profile in profiles:
            summary.profiles.append(_process_profile(profile, now=now or timezone.now()))
    finally:
        summary.duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        logger.info('social_automation.tick_end duration_ms=%s', summary.duration_ms)
        if use_lock:
            cache.delete(TICK_LOCK_KEY)
    return summary.as_dict()


def _process_profile(profile, *, now):
    profile_summary = ProfileTickSummary(profile=profile.username, profile_id=profile.id)
    logger.info('social_automation.profile_start profile_id=%s username=%s', profile.id, profile.username)
    try:
        _validar_profile_automatico(profile)
        published = _publicar_devido(profile, now=now)
        profile_summary.published = 1 if published else 0
        reagendados = reagendar_vencidos(profile, now=now)
        profile_summary.rescheduled = reagendados.rescheduled
        schedule = preencher_agenda(profile, now=now)
        profile_summary.scheduled = schedule.scheduled
        current_inventory = estoque_pronto(profile)
        profile_summary.inventory = current_inventory
        logger.info(
            'social_automation.inventory profile_id=%s current=%s minimum=%s target=%s',
            profile.id,
            current_inventory,
            settings.SOCIAL_AUTOMATION_QUEUE_MIN,
            settings.SOCIAL_AUTOMATION_QUEUE_TARGET,
        )
        if not published and current_inventory < settings.SOCIAL_AUTOMATION_QUEUE_TARGET:
            generated, approved, errors = _gerar_e_aprovar(profile, current_inventory)
            profile_summary.generated = generated
            profile_summary.approved = approved
            profile_summary.errors += errors
            schedule_after = preencher_agenda(profile, now=now)
            profile_summary.scheduled += schedule_after.scheduled
            current_inventory = estoque_pronto(profile)
        next_content = proxima_publicacao(profile, now=now)
        profile_summary.inventory = current_inventory
        profile_summary.next_post = next_content.scheduled_at.isoformat() if next_content and next_content.scheduled_at else None
    except Exception as exc:
        profile_summary.errors += 1
        profile_summary.status = 'erro'
        profile_summary.message = str(exc)[:160]
        logger.warning('social_automation.profile_error profile_id=%s error=%s', profile.id, type(exc).__name__)
    return profile_summary


def _validar_profile_automatico(profile):
    expected = (settings.INSTAGRAM_EXPECTED_USERNAME or '').strip().lstrip('@').lower()
    username = (profile.username or '').strip().lstrip('@').lower()
    if expected and username != expected:
        raise InstagramConfigurationError('Perfil automatico nao corresponde ao username configurado para a credencial Meta.')
    if not profile.horarios_publicacao:
        raise ValidationError('Perfil automatico sem horarios de publicacao.')


def _publicar_devido(profile, *, now):
    due = (
        profile.contents.select_related('profile')
        .filter(status=SocialContent.Status.AGENDADO, scheduled_at__lte=now)
        .order_by('scheduled_at', 'id')
        .first()
    )
    if not due:
        return False
    if not _pode_publicar_agora(profile, now=now):
        return False
    if _published_24h(profile, now) >= settings.SOCIAL_AUTOMATION_HARD_24H_CAP:
        registrar_evento(due, AutoEvent.CAP, None, 'Limite interno de 24h atingido; conteudo mantido para proximo slot.')
        due.status = SocialContent.Status.APROVADO
        due.scheduled_at = None
        due.save(update_fields=['status', 'scheduled_at', 'updated_at'])
        preencher_agenda(profile, now=now)
        logger.warning('social_automation.hard_cap profile_id=%s cap=%s', profile.id, settings.SOCIAL_AUTOMATION_HARD_24H_CAP)
        return False
    logger.info('social_automation.auto_publish_start content_id=%s', due.id)
    try:
        publicar_conteudo_instagram(due)
        due.refresh_from_db()
        registrar_evento(due, AutoEvent.PUBLICADO, None, 'Publicacao automatica concluida.')
        logger.info('social_automation.auto_publish_success content_id=%s external_post_id=%s', due.id, _mask(due.external_post_id))
        return True
    except (InstagramConfigurationError, InstagramPublishError) as exc:
        _registrar_erro_auto(due.id, exc, retry=False)
    except InstagramAPIError as exc:
        retry = bool(exc.is_transient) and due.tentativas < settings.SOCIAL_AUTOMATION_MAX_RETRIES
        _registrar_erro_auto(due.id, exc, retry=retry)
    return False


def _pode_publicar_agora(profile, *, now):
    last = (
        profile.contents.filter(status=SocialContent.Status.PUBLICADO, published_at__isnull=False)
        .order_by('-published_at')
        .first()
    )
    if not last or not last.published_at:
        return True
    gap = timedelta(minutes=settings.SOCIAL_AUTOMATION_MIN_POST_GAP_MINUTES)
    return last.published_at <= now - gap


def _published_24h(profile, now):
    return profile.contents.filter(status=SocialContent.Status.PUBLICADO, published_at__gte=now - timedelta(hours=24)).count()


def _registrar_erro_auto(content_id, exc, *, retry):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().get(pk=content_id)
        detail = f'{type(exc).__name__}: {str(exc)[:180]}'
        if retry:
            delay = _retry_delay(content.tentativas)
            content.status = SocialContent.Status.AGENDADO
            content.scheduled_at = timezone.now() + delay
            content.erro = str(exc)[:1000]
            content.save(update_fields=['status', 'scheduled_at', 'erro', 'updated_at'])
            registrar_evento(content, AutoEvent.RETRY, None, f'Retry seguro em {int(delay.total_seconds() / 60)} min. {detail}')
            logger.warning('social_automation.auto_publish_error content_id=%s classification=retry_safe', content.id)
        else:
            registrar_evento(content, AutoEvent.ERRO, None, f'Erro sem retry automatico. {detail}')
            logger.warning('social_automation.auto_publish_error content_id=%s classification=ambiguous', content.id)


def _retry_delay(tentativas):
    if tentativas <= 1:
        return timedelta(minutes=10)
    if tentativas == 2:
        return timedelta(minutes=30)
    return timedelta(minutes=60)


def _gerar_e_aprovar(profile, inventory):
    target_missing = max(0, settings.SOCIAL_AUTOMATION_QUEUE_TARGET - inventory)
    batch = min(settings.SOCIAL_AUTOMATION_GENERATION_BATCH, target_missing)
    if batch <= 0:
        return 0, 0, 0
    tema = random.choice(AUTO_THEMES)
    logger.info('social_automation.auto_generation_start profile_id=%s batch=%s', profile.id, batch)
    result = gerar_lote_conteudos(profile, batch, tema, None)
    approved = 0
    errors = result.falhas + result.bloqueados
    for content in result.conteudos:
        if _quality_gate(content):
            with transaction.atomic():
                locked = SocialContent.objects.select_for_update().get(pk=content.pk)
                if locked.status == SocialContent.Status.RASCUNHO:
                    locked.status = SocialContent.Status.APROVADO
                    locked.save(update_fields=['status', 'updated_at'])
                    registrar_evento(locked, AutoEvent.APROVADO, None, 'Aprovacao automatica do pipeline 8E.')
                    approved += 1
        else:
            errors += 1
    logger.info(
        'social_automation.auto_generation_end generated=%s approved=%s blocked=%s failed=%s',
        result.criados,
        approved,
        result.bloqueados,
        result.falhas,
    )
    return result.criados, approved, errors


def _quality_gate(content):
    if content.status != SocialContent.Status.RASCUNHO:
        return False
    if not content.frase.strip() or not content.legenda.strip():
        return False
    if not content.base_image_id or not content.final_image:
        return False
    try:
        auditar_imagem_final(content)
    except Exception:
        return False
    return True


def automacao_status_profile(profile):
    now = timezone.now()
    inventory = estoque_pronto(profile)
    next_content = proxima_publicacao(profile, now=now)
    last_published = profile.contents.filter(status=SocialContent.Status.PUBLICADO).order_by('-published_at').first()
    last_error = profile.contents.filter(status=SocialContent.Status.ERRO).order_by('-updated_at').first()
    if not profile.ativo or profile.modo_operacao != SocialProfile.ModoOperacao.AUTOMATICO:
        status = 'PARADO'
    elif inventory < settings.SOCIAL_AUTOMATION_QUEUE_MIN or not next_content or last_error:
        status = 'ATENCAO'
    else:
        status = 'SAUDAVEL'
    return {
        'modo': profile.get_modo_operacao_display(),
        'posts_por_dia': profile.posts_por_dia,
        'estoque': inventory,
        'minimo': settings.SOCIAL_AUTOMATION_QUEUE_MIN,
        'alvo': settings.SOCIAL_AUTOMATION_QUEUE_TARGET,
        'agendados_24h': profile.contents.filter(
            status=SocialContent.Status.AGENDADO,
            scheduled_at__gte=now,
            scheduled_at__lt=now + timedelta(hours=24),
        ).count(),
        'proxima_publicacao': next_content.scheduled_at if next_content else None,
        'ultima_publicacao': last_published.published_at if last_published else None,
        'ultimo_erro': last_error.erro[:160] if last_error and last_error.erro else '',
        'status': status,
    }


def _mask(value):
    value = str(value or '')
    if len(value) <= 8:
        return '***'
    return f'{value[:4]}...{value[-4:]}'
