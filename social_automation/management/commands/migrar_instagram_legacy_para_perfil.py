from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from social_automation.instagram import InstagramAPIError, InstagramConfigurationError, criar_ou_atualizar_conexao_instagram
from social_automation.models import SocialProfile


class Command(BaseCommand):
    help = 'Migra as credenciais Instagram legacy das envs para um SocialProfile, sem exibir token.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        username = (options['username'] or '').strip().lstrip('@')
        if not username:
            raise CommandError('Informe o username do perfil.')
        if options['apply'] and options['dry_run']:
            raise CommandError('Use --apply ou --dry-run, nao ambos.')

        token = settings.INSTAGRAM_ACCESS_TOKEN
        user_id = settings.INSTAGRAM_USER_ID
        expected = (settings.INSTAGRAM_EXPECTED_USERNAME or username).strip().lstrip('@')
        if not token or not user_id:
            raise CommandError('INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_USER_ID precisam estar configurados.')
        if expected.lower() != username.lower():
            raise CommandError('Username informado nao corresponde ao INSTAGRAM_EXPECTED_USERNAME.')

        profile = SocialProfile.objects.filter(username__iexact=username).first() or SocialProfile.objects.filter(username__iexact=f'@{username}').first()
        if not profile:
            raise CommandError('SocialProfile nao encontrado.')

        self.stdout.write(f'Perfil: {profile.nome} ({profile.username})')
        self.stdout.write(f'Instagram User ID: {self._mask(user_id)}')
        self.stdout.write(f'Username esperado: @{expected}')
        self.stdout.write('Token: presente, nao exibido')

        if not options['apply']:
            self.stdout.write(self.style.WARNING('Dry-run: nenhuma conexao foi criada ou atualizada.'))
            return

        try:
            connection = criar_ou_atualizar_conexao_instagram(
                profile,
                access_token=token,
                instagram_user_id=user_id,
                username=expected,
                token_expires_at=timezone.now() + timedelta(days=60),
            )
        except (InstagramConfigurationError, InstagramAPIError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f'Conexao Instagram migrada para @{connection.username}.'))

    def _mask(self, value):
        value = str(value or '')
        if len(value) <= 8:
            return '***'
        return f'{value[:4]}...{value[-4:]}'
