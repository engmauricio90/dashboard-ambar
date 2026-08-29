from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from social_automation.models import SocialContent, SocialProfile
from social_automation.scheduler import build_daily_media_plan, parse_horarios, profile_zone


class Command(BaseCommand):
    help = 'Diagnostica o plano diario Foto/Reel/Carrossel de um perfil social, sem alterar agenda.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('data')

    def handle(self, *args, **options):
        username = (options['username'] or '').strip().lstrip('@')
        try:
            data = datetime.strptime(options['data'], '%Y-%m-%d').date()
        except ValueError as exc:
            raise CommandError('Informe a data no formato YYYY-MM-DD.') from exc

        profile = SocialProfile.objects.filter(username__iexact=username).first() or SocialProfile.objects.filter(username__iexact=f'@{username}').first()
        if not profile:
            raise CommandError('Perfil social nao encontrado.')

        zone = profile_zone(profile)
        horarios = parse_horarios(profile)
        total_slots = max(len(horarios), profile.posts_por_dia or 0)
        plan = build_daily_media_plan(total_slots, profile.reels_por_dia, profile.carousels_por_dia)
        planned_counts = self._counts(plan)

        self.stdout.write(f'Perfil: {profile.nome}')
        self.stdout.write(f'Data: {data.strftime("%d/%m/%Y")}')
        self.stdout.write('')
        self.stdout.write(f'Posts/dia: {profile.posts_por_dia}')
        self.stdout.write(f'Fotos planejadas: {planned_counts[SocialContent.MediaType.IMAGE]}')
        self.stdout.write(f'Reels planejados: {planned_counts[SocialContent.MediaType.REEL]}')
        self.stdout.write(f'Carrosseis planejados: {planned_counts[SocialContent.MediaType.CAROUSEL]}')
        self.stdout.write('')

        scheduled = self._scheduled_by_local_time(profile, data, zone)
        planned_for_horarios = []
        self.stdout.write('Planejamento:')
        for index, horario in enumerate(horarios):
            media_type = plan[index % len(plan)] if plan else SocialContent.MediaType.IMAGE
            planned_for_horarios.append(media_type)
            self.stdout.write(f'{horario.strftime("%H:%M")} {media_type.upper()}')

        self.stdout.write('')
        self.stdout.write('Agendado:')
        desvios = 0
        scheduled_counts = {
            SocialContent.MediaType.IMAGE: 0,
            SocialContent.MediaType.REEL: 0,
            SocialContent.MediaType.CAROUSEL: 0,
        }
        for index, horario in enumerate(horarios):
            content = scheduled.get(horario)
            expected = planned_for_horarios[index]
            if content:
                scheduled_counts[content.media_type] += 1
                status = 'OK' if content.media_type == expected else 'DESVIO'
                if status == 'DESVIO':
                    desvios += 1
                self.stdout.write(f'{horario.strftime("%H:%M")} {content.media_type.upper()} #{content.id} {status}')
            else:
                self.stdout.write(f'{horario.strftime("%H:%M")} - pendente')

        self.stdout.write('')
        self.stdout.write('Resumo:')
        self.stdout.write(
            f'Planejado: {planned_counts[SocialContent.MediaType.IMAGE]} IMAGE / '
            f'{planned_counts[SocialContent.MediaType.REEL]} REEL / '
            f'{planned_counts[SocialContent.MediaType.CAROUSEL]} CAROUSEL'
        )
        self.stdout.write(
            f'Agendado: {scheduled_counts[SocialContent.MediaType.IMAGE]} IMAGE / '
            f'{scheduled_counts[SocialContent.MediaType.REEL]} REEL / '
            f'{scheduled_counts[SocialContent.MediaType.CAROUSEL]} CAROUSEL'
        )
        self.stdout.write(f'Desvios: {desvios}')

    def _scheduled_by_local_time(self, profile, data, zone):
        start = datetime.combine(data, time.min, tzinfo=zone).astimezone(timezone.get_current_timezone())
        end = datetime.combine(data, time.max, tzinfo=zone).astimezone(timezone.get_current_timezone())
        contents = profile.contents.filter(status=SocialContent.Status.AGENDADO, scheduled_at__range=(start, end)).order_by('scheduled_at', 'id')
        return {content.scheduled_at.astimezone(zone).time().replace(second=0, microsecond=0): content for content in contents}

    def _counts(self, plan):
        return {
            SocialContent.MediaType.IMAGE: plan.count(SocialContent.MediaType.IMAGE),
            SocialContent.MediaType.REEL: plan.count(SocialContent.MediaType.REEL),
            SocialContent.MediaType.CAROUSEL: plan.count(SocialContent.MediaType.CAROUSEL),
        }
