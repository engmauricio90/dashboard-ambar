from django.core.management.base import BaseCommand, CommandError

from social_automation.models import SocialProfile


PRESET_20_DIA = [
    '07:00',
    '07:50',
    '08:40',
    '09:30',
    '10:20',
    '11:10',
    '12:00',
    '12:50',
    '13:40',
    '14:30',
    '15:20',
    '16:10',
    '17:00',
    '17:50',
    '18:40',
    '19:30',
    '20:20',
    '21:10',
    '22:00',
    '22:50',
]


class Command(BaseCommand):
    help = 'Configura um perfil social para automacao usando preset seguro.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--preset', choices=['20-dia'], required=True)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if options['dry_run'] == options['apply']:
            raise CommandError('Use exatamente uma opcao: --dry-run ou --apply.')
        username = options['username'].strip().lstrip('@')
        profile = SocialProfile.objects.filter(username__iexact=f'@{username}').first() or SocialProfile.objects.filter(username__iexact=username).first()
        if not profile:
            raise CommandError('Perfil social nao encontrado.')

        horarios = PRESET_20_DIA
        self.stdout.write(f'perfil={profile.nome} ({profile.username})')
        self.stdout.write(f'modo atual={profile.modo_operacao}')
        self.stdout.write(f'modo novo={SocialProfile.ModoOperacao.AUTOMATICO}')
        self.stdout.write('timezone=America/Sao_Paulo')
        self.stdout.write('posts_por_dia=20')
        self.stdout.write('horarios=' + ', '.join(horarios))

        if options['apply']:
            profile.modo_operacao = SocialProfile.ModoOperacao.AUTOMATICO
            profile.posts_por_dia = 20
            profile.timezone = 'America/Sao_Paulo'
            profile.horarios_publicacao = horarios
            profile.save(update_fields=['modo_operacao', 'posts_por_dia', 'timezone', 'horarios_publicacao', 'updated_at'])
            self.stdout.write(self.style.SUCCESS('Automacao aplicada.'))
        else:
            self.stdout.write('dry-run: nenhuma alteracao aplicada.')
