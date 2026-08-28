from django.core.management.base import BaseCommand

from social_automation.models import SocialInstagramConnection


class Command(BaseCommand):
    help = 'Lista conexoes Instagram por perfil sem exibir tokens.'

    def handle(self, *args, **options):
        conexoes = SocialInstagramConnection.objects.select_related('profile').order_by('profile__nome')
        if not conexoes.exists():
            self.stdout.write('Nenhuma conexao Instagram cadastrada.')
            return
        for connection in conexoes:
            self.stdout.write(
                f'Perfil: {connection.profile.nome} | '
                f'Username: @{connection.username} | '
                f'Instagram User ID: {connection.masked_instagram_user_id} | '
                f'Ativa: {"SIM" if connection.is_active else "NAO"} | '
                f'Ultima validacao: {connection.last_validated_at or "-"} | '
                f'Status: {connection.get_last_validation_status_display()}'
            )
