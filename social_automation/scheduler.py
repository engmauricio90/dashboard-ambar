from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from django.db.models import Q

from .models import SocialContent, SocialProfile
from .services import registrar_evento

RESERVED_STOCK_STATUSES = {
    SocialContent.Status.RASCUNHO,
    SocialContent.Status.APROVADO,
    SocialContent.Status.AGENDADO,
    SocialContent.Status.PUBLICANDO,
    SocialContent.Status.ERRO,
}

READY_STOCK_STATUSES = {
    SocialContent.Status.APROVADO,
    SocialContent.Status.AGENDADO,
}

IN_PROGRESS_RUN_STATUSES = {
    'IDEATING',
    'IDEA_SELECTED',
    'BLUEPRINT_READY',
    'EDITORIAL_APPROVED',
    'COMPOSING',
    'REVIEWING',
    'PARTIAL',
}

IN_PROGRESS_SLIDE_STATUSES = {
    'PENDING',
    'COMPOSING',
    'REVIEWING',
    'NEEDS_RECOMPOSE',
}


@dataclass
class ScheduleResult:
    scheduled: int = 0
    rescheduled: int = 0
    skipped: int = 0
    next_post: datetime | None = None


def profile_zone(profile: SocialProfile):
    try:
        return ZoneInfo(profile.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError('Timezone do perfil invalido.') from exc


def parse_horarios(profile: SocialProfile):
    horarios = []
    for raw in profile.horarios_publicacao or []:
        hour, minute = [int(part) for part in raw.split(':')]
        horarios.append(time(hour, minute))
    return sorted(horarios)


def iter_slots(profile: SocialProfile, now=None, days=4):
    now = now or timezone.now()
    zone = profile_zone(profile)
    local_now = now.astimezone(zone)
    horarios = parse_horarios(profile)
    for offset in range(days):
        day = local_now.date() + timedelta(days=offset)
        for horario in horarios:
            slot_local = datetime.combine(day, horario, tzinfo=zone)
            slot = slot_local.astimezone(timezone.get_current_timezone())
            if slot > now:
                yield slot


def build_daily_media_plan(posts_per_day, reels_per_day, carousels_per_day=0):
    total = max(0, int(posts_per_day or 0))
    reels = min(max(0, int(reels_per_day or 0)), total)
    carousels = min(max(0, int(carousels_per_day or 0)), max(0, total - reels))
    if total <= 0:
        return []
    non_images = []
    for index in range(1, total + 1):
        current_quota = (index * reels) // total
        previous_quota = ((index - 1) * reels) // total
        if current_quota > previous_quota:
            non_images.append((index - 1, SocialContent.MediaType.REEL))
    for index in range(1, total + 1):
        current_quota = (index * carousels) // total
        previous_quota = ((index - 1) * carousels) // total
        if current_quota > previous_quota:
            slot = index - 1
            while any(existing_slot == slot for existing_slot, _media in non_images) and slot + 1 < total:
                slot += 1
            if any(existing_slot == slot for existing_slot, _media in non_images):
                slot = next((candidate for candidate in range(total) if not any(existing_slot == candidate for existing_slot, _media in non_images)), index - 1)
            non_images.append((slot, SocialContent.MediaType.CAROUSEL))
    plan = [SocialContent.MediaType.IMAGE] * total
    for slot, media_type in sorted(non_images):
        plan[slot] = media_type
    return plan


def media_type_for_slot(index, total_slots, reels_por_dia, carousels_por_dia=0):
    plan = build_daily_media_plan(total_slots, reels_por_dia, carousels_por_dia)
    if not plan:
        return SocialContent.MediaType.IMAGE
    return plan[index % len(plan)]


def estoque_pronto(profile: SocialProfile):
    by_type = estoque_pronto_por_tipo(profile)
    return sum(by_type.values())


def estoque_pronto_por_tipo(profile: SocialProfile):
    approved_or_scheduled = profile.contents.filter(status__in=READY_STOCK_STATUSES)
    ready = approved_or_scheduled.filter(_ready_media_q()).distinct()
    ready_carousels = sum(
        1
        for content in approved_or_scheduled.filter(media_type=SocialContent.MediaType.CAROUSEL).prefetch_related('carousel_slides')
        if content.final_media_ready
    )
    return {
        SocialContent.MediaType.IMAGE: ready.filter(media_type=SocialContent.MediaType.IMAGE).count(),
        SocialContent.MediaType.REEL: ready.filter(media_type=SocialContent.MediaType.REEL).count(),
        SocialContent.MediaType.CAROUSEL: ready_carousels,
    }


def estoque_reservado(profile: SocialProfile, *, now=None):
    by_type = estoque_reservado_por_tipo(profile, now=now)
    return sum(by_type.values())


def estoque_reservado_por_tipo(profile: SocialProfile, *, now=None):
    now = now or timezone.now()
    contents = (
        profile.contents.filter(status__in=RESERVED_STOCK_STATUSES)
        .prefetch_related('carousel_slides', 'carousel_generation_runs', 'events')
        .order_by('id')
    )
    totals = {
        SocialContent.MediaType.IMAGE: 0,
        SocialContent.MediaType.REEL: 0,
        SocialContent.MediaType.CAROUSEL: 0,
    }
    for content in contents:
        if _content_reserves_stock(content, now=now):
            totals[content.media_type] += 1
    return totals


def estoque_em_andamento_por_tipo(profile: SocialProfile, *, now=None):
    ready = estoque_pronto_por_tipo(profile)
    reserved = estoque_reservado_por_tipo(profile, now=now)
    return {
        media_type: max(0, reserved[media_type] - ready[media_type])
        for media_type in reserved
    }


def tipos_reservados_criados_desde(profile: SocialProfile, since, *, now=None, statuses=None):
    now = now or timezone.now()
    statuses = set(statuses or RESERVED_STOCK_STATUSES)
    contents = (
        profile.contents.filter(status__in=statuses, created_at__gte=since, created_at__lte=now)
        .prefetch_related('carousel_slides', 'carousel_generation_runs', 'events')
        .order_by('id')
    )
    return {
        content.media_type
        for content in contents
        if _content_reserves_stock(content, now=now)
    }


def estoque_minimo_profile(profile: SocialProfile):
    return max(0, (profile.posts_por_dia or 0) * 2)


def estoque_alvo_profile(profile: SocialProfile):
    return max(0, (profile.posts_por_dia or 0) * 3)


def _ready_media_q():
    return (
        Q(media_type=SocialContent.MediaType.IMAGE, final_image__isnull=False)
        & ~Q(final_image='')
        | Q(media_type=SocialContent.MediaType.REEL, final_video__isnull=False)
        & ~Q(final_video='')
        | Q(media_type=SocialContent.MediaType.CAROUSEL, carousel_slides__rendered_image__isnull=False)
        & ~Q(carousel_slides__rendered_image='')
    )


def _target_counts(profile, target_total):
    posts = max(1, profile.posts_por_dia or 1)
    reels = min(profile.reels_por_dia or 0, posts)
    carousels = min(profile.carousels_por_dia or 0, max(0, posts - reels))
    reel_target = round(target_total * reels / posts)
    carousel_target = round(target_total * carousels / posts)
    return {
        SocialContent.MediaType.REEL: reel_target,
        SocialContent.MediaType.CAROUSEL: carousel_target,
        SocialContent.MediaType.IMAGE: max(0, target_total - reel_target - carousel_target),
    }


def plano_geracao_por_deficit(profile, target_total, batch_limit):
    current = estoque_reservado_por_tipo(profile)
    target = _target_counts(profile, target_total)
    missing = {
        SocialContent.MediaType.REEL: max(0, target[SocialContent.MediaType.REEL] - current[SocialContent.MediaType.REEL]),
        SocialContent.MediaType.CAROUSEL: max(0, target[SocialContent.MediaType.CAROUSEL] - current[SocialContent.MediaType.CAROUSEL]),
        SocialContent.MediaType.IMAGE: max(0, target[SocialContent.MediaType.IMAGE] - current[SocialContent.MediaType.IMAGE]),
    }
    plan = []
    for _ in range(min(batch_limit, sum(missing.values()))):
        media_type = max(
            [SocialContent.MediaType.REEL, SocialContent.MediaType.CAROUSEL, SocialContent.MediaType.IMAGE],
            key=lambda item: (missing[item], item == SocialContent.MediaType.REEL),
        )
        if missing[media_type] <= 0:
            break
        plan.append(media_type)
        missing[media_type] -= 1
    return plan


def slot_reservado(profile, slot, media_type=None):
    queryset = profile.contents.filter(status__in=RESERVED_STOCK_STATUSES, scheduled_at=slot)
    if media_type:
        queryset = queryset.filter(media_type=media_type)
    return queryset.exists()


def _content_reserves_stock(content, *, now):
    if content.status in {SocialContent.Status.REJEITADO, SocialContent.Status.PUBLICADO}:
        return False
    if content.status in {SocialContent.Status.APROVADO, SocialContent.Status.AGENDADO, SocialContent.Status.PUBLICANDO}:
        return True
    if content.status == SocialContent.Status.ERRO:
        return _content_error_can_reserve(content, now=now)
    if content.status == SocialContent.Status.RASCUNHO:
        return _content_has_auto_generation_signal(content) and (
            _content_is_recent(content, now=now)
            or _content_has_active_run(content, now=now)
            or _carousel_has_pending_work(content)
            or _content_has_final_media_file(content)
        )
    return False


def _content_error_can_reserve(content, *, now):
    max_retries = getattr(settings, 'SOCIAL_AUTOMATION_MAX_RETRIES', 3)
    if content.tentativas < max_retries:
        return True
    return _content_has_active_run(content, now=now)


def _content_has_active_run(content, *, now):
    stale_before = now - timedelta(hours=_reserved_stock_stale_hours())
    return any(
        run.status in IN_PROGRESS_RUN_STATUSES and run.started_at >= stale_before
        for run in content.carousel_generation_runs.all()
    )


def _carousel_has_pending_work(content):
    if content.media_type != SocialContent.MediaType.CAROUSEL:
        return False
    return any(
        slide.ai_composition_status in IN_PROGRESS_SLIDE_STATUSES
        for slide in content.carousel_slides.all()
    )


def _content_has_auto_generation_signal(content):
    if content.carousel_generation_runs.all():
        return True
    if content.events.all():
        return True
    return _content_has_final_media_file(content)


def _content_has_final_media_file(content):
    if content.media_type == SocialContent.MediaType.REEL:
        return bool(content.final_video)
    if content.media_type == SocialContent.MediaType.CAROUSEL:
        return bool(content.carousel_slides.all())
    return bool(content.final_image)


def _content_is_recent(content, *, now):
    timestamp = content.updated_at or content.created_at
    return bool(timestamp and timestamp >= now - timedelta(hours=_reserved_stock_stale_hours()))


def _reserved_stock_stale_hours():
    return max(1, int(getattr(settings, 'SOCIAL_AUTOMATION_RESERVED_STOCK_STALE_HOURS', 72)))


def proxima_publicacao(profile: SocialProfile, now=None):
    now = now or timezone.now()
    return (
        profile.contents.filter(status=SocialContent.Status.AGENDADO, scheduled_at__gte=now)
        .order_by('scheduled_at')
        .first()
    )


def preencher_agenda(profile: SocialProfile, now=None, days=4):
    now = now or timezone.now()
    result = ScheduleResult()
    slots_ocupados = set(
        profile.contents.filter(status=SocialContent.Status.AGENDADO, scheduled_at__gte=now)
        .exclude(scheduled_at__isnull=True)
        .values_list('scheduled_at', flat=True)
    )
    aprovados = list(
        profile.contents.filter(
            status=SocialContent.Status.APROVADO,
            scheduled_at__isnull=True,
        )
        .filter(_ready_media_q())
        .distinct()
        .order_by('created_at', 'id')
    )
    if not aprovados:
        result.next_post = proxima_publicacao(profile, now)
        return result

    remaining = list(aprovados)
    total_slots_day = max(len(parse_horarios(profile)), profile.posts_por_dia or 0)
    for slot_index, slot in enumerate(iter_slots(profile, now=now, days=days)):
        if slot in slots_ocupados:
            continue
        preferred_type = media_type_for_slot(
            slot_index % max(total_slots_day, 1),
            max(total_slots_day, 1),
            profile.reels_por_dia,
            profile.carousels_por_dia,
        )
        content = next((item for item in remaining if item.media_type == preferred_type), None)
        if not content:
            result.skipped += 1
            continue
        remaining.remove(content)
        with transaction.atomic():
            locked = SocialContent.objects.select_for_update().get(pk=content.pk)
            if locked.status != SocialContent.Status.APROVADO or not locked.final_media_ready:
                result.skipped += 1
                continue
            locked.status = SocialContent.Status.AGENDADO
            locked.scheduled_at = slot
            locked.save(update_fields=['status', 'scheduled_at', 'updated_at'])
            registrar_evento(locked, SocialContentEventAction.AGENDADO_AUTOMATICO, None, f'Agendado automaticamente para {slot.isoformat()}')
        result.scheduled += 1
        slots_ocupados.add(slot)

    result.next_post = proxima_publicacao(profile, now)
    return result


class SocialContentEventAction:
    AGENDADO_AUTOMATICO = 'agendado_auto'
    REAGENDADO_DOWNTIME = 'reagendado_downtime'


def reagendar_vencidos(profile: SocialProfile, now=None, days=4):
    now = now or timezone.now()
    vencidos = list(
        profile.contents.filter(status=SocialContent.Status.AGENDADO, scheduled_at__lt=now)
        .order_by('scheduled_at', 'id')
    )
    if not vencidos:
        return ScheduleResult(next_post=proxima_publicacao(profile, now))

    slots_ocupados = set(
        profile.contents.filter(status=SocialContent.Status.AGENDADO, scheduled_at__gte=now)
        .exclude(scheduled_at__isnull=True)
        .values_list('scheduled_at', flat=True)
    )
    slots = [slot for slot in iter_slots(profile, now=now, days=days) if slot not in slots_ocupados]
    result = ScheduleResult()
    for content, slot in zip(vencidos, slots):
        with transaction.atomic():
            locked = SocialContent.objects.select_for_update().get(pk=content.pk)
            if locked.status != SocialContent.Status.AGENDADO or not locked.scheduled_at or locked.scheduled_at >= now:
                result.skipped += 1
                continue
            locked.scheduled_at = slot
            locked.save(update_fields=['scheduled_at', 'updated_at'])
            registrar_evento(locked, SocialContentEventAction.REAGENDADO_DOWNTIME, None, f'Reagendado por recuperacao para {slot.isoformat()}')
        result.rescheduled += 1
        slots_ocupados.add(slot)
    result.next_post = proxima_publicacao(profile, now)
    return result
