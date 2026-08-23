from django.core.management.base import BaseCommand
from django.utils import timezone

from social_automation.models import SocialContent


class Command(BaseCommand):
    help = 'Lista conteudos sociais agendados e vencidos. Nao publica nesta fase.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Lista conteudos aptos sem alterar dados.')

    def handle(self, *args, **options):
        if not options['dry_run']:
            self.stdout.write('Integracao de publicacao ainda nao implementada. Use --dry-run para listar a fila vencida.')
            return

        queryset = (
            SocialContent.objects.select_related('profile')
            .filter(status=SocialContent.Status.AGENDADO, scheduled_at__lte=timezone.now(), profile__ativo=True)
            .order_by('scheduled_at', 'id')
        )
        total = queryset.count()
        self.stdout.write(f'{total} conteudo(s) apto(s) para publicacao futura.')
        for content in queryset:
            frase = content.frase.replace('\n', ' ')[:80]
            self.stdout.write(f'#{content.id} | {content.profile.username} | {content.scheduled_at:%d/%m/%Y %H:%M} | {frase}')
