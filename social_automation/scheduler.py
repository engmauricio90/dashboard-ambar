from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from django.db.models import Q

from .models import SocialContent, SocialProfile
from .services import registrar_evento


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


def estoque_pronto(profile: SocialProfile):
    return profile.contents.filter(
        status__in=[SocialContent.Status.APROVADO, SocialContent.Status.AGENDADO],
    ).filter(_ready_media_q()).count()


def estoque_pronto_por_tipo(profile: SocialProfile):
    ready = profile.contents.filter(status__in=[SocialContent.Status.APROVADO, SocialContent.Status.AGENDADO]).filter(_ready_media_q())
    return {
        SocialContent.MediaType.IMAGE: ready.filter(media_type=SocialContent.MediaType.IMAGE).count(),
        SocialContent.MediaType.REEL: ready.filter(media_type=SocialContent.MediaType.REEL).count(),
    }


def _ready_media_q():
    return Q(media_type=SocialContent.MediaType.IMAGE, final_image__isnull=False) & ~Q(final_image='') | Q(
        media_type=SocialContent.MediaType.REEL,
        final_video__isnull=False,
    ) & ~Q(final_video='')


def _target_counts(profile, target_total):
    posts = max(1, profile.posts_por_dia or 1)
    reels = min(profile.reels_por_dia or 0, posts)
    reel_target = round(target_total * reels / posts)
    return {
        SocialContent.MediaType.REEL: reel_target,
        SocialContent.MediaType.IMAGE: target_total - reel_target,
    }


def plano_geracao_por_deficit(profile, target_total, batch_limit):
    current = estoque_pronto_por_tipo(profile)
    target = _target_counts(profile, target_total)
    missing = {
        SocialContent.MediaType.REEL: max(0, target[SocialContent.MediaType.REEL] - current[SocialContent.MediaType.REEL]),
        SocialContent.MediaType.IMAGE: max(0, target[SocialContent.MediaType.IMAGE] - current[SocialContent.MediaType.IMAGE]),
    }
    plan = []
    for _ in range(min(batch_limit, sum(missing.values()))):
        media_type = max(
            [SocialContent.MediaType.REEL, SocialContent.MediaType.IMAGE],
            key=lambda item: (missing[item], item == SocialContent.MediaType.REEL),
        )
        if missing[media_type] <= 0:
            break
        plan.append(media_type)
        missing[media_type] -= 1
    return plan


def media_type_for_slot(index, total_slots, reels_por_dia):
    if reels_por_dia <= 0 or total_slots <= 0:
        return SocialContent.MediaType.IMAGE
    reels = min(reels_por_dia, total_slots)
    interval = total_slots / reels
    reel_positions = {min(total_slots - 1, round((item + 1) * interval) - 1) for item in range(reels)}
    return SocialContent.MediaType.REEL if index in reel_positions else SocialContent.MediaType.IMAGE


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
        .order_by('created_at', 'id')
    )
    if not aprovados:
        result.next_post = proxima_publicacao(profile, now)
        return result

    remaining = list(aprovados)
    slot_index = 0
    total_slots_day = max(len(parse_horarios(profile)), profile.posts_por_dia or 0)
    for slot in iter_slots(profile, now=now, days=days):
        if slot in slots_ocupados:
            continue
        preferred_type = media_type_for_slot(slot_index % max(total_slots_day, 1), max(total_slots_day, 1), profile.reels_por_dia)
        content = next((item for item in remaining if item.media_type == preferred_type), None) or (remaining[0] if remaining else None)
        if not content:
            break
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
        slot_index += 1

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
