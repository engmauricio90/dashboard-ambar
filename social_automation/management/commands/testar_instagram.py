from django.core.management.base import BaseCommand, CommandError

from social_automation.instagram import (
    InstagramAPIError,
    InstagramConfigurationError,
    obter_conta_instagram,
    obter_permissoes_instagram,
    verificar_configuracao_instagram,
)


class Command(BaseCommand):
    help = 'Executa smoke read-only seguro da integracao Instagram.'

    def handle(self, *args, **options):
        try:
            verificar_configuracao_instagram()
            conta = obter_conta_instagram()
            permissoes = obter_permissoes_instagram()
        except (InstagramConfigurationError, InstagramAPIError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS('Instagram API: OK'))
        self.stdout.write('User ID: configurado')
        self.stdout.write(f'Username: {conta.get("username") or "-"}')
        self.stdout.write(f'Conta: {conta.get("account_type") or "acessivel"}')
        self.stdout.write('Token: aceito')
        if permissoes is not None:
            scopes = [item.get('permission') for item in permissoes.get('data', [])]
            self.stdout.write(f'Permissoes consultadas: {", ".join(filter(None, scopes)) or "-"}')
        self.stdout.write('Publicacao: nao executada')
