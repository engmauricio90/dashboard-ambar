from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from social_automation.models import SocialProfile


class Command(BaseCommand):
    help = 'Configura o mix de fotos e Reels de um perfil social.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--reels', type=int, required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        username = options['username'].strip().lstrip('@').lower()
        profile = SocialProfile.objects.filter(Q(username__iexact=username) | Q(username__iexact=f'@{username}')).first()
        if not profile:
            raise CommandError('Perfil social nao encontrado.')
        reels = options['reels']
        if reels < 0 or reels > profile.posts_por_dia:
            raise CommandError('Reels por dia precisa ficar entre 0 e posts_por_dia.')
        fotos = profile.posts_por_dia - reels
        total = max(profile.posts_por_dia, 1)

        self.stdout.write(f'Perfil: {profile.username.lstrip("@")}')
        self.stdout.write(f'Posts/dia: {profile.posts_por_dia}')
        self.stdout.write(f'Reels/dia: {reels}')
        self.stdout.write(f'Fotos/dia: {fotos}')
        self.stdout.write(f'Reels: {round(reels / total * 100)}%')
        self.stdout.write(f'Fotos: {round(fotos / total * 100)}%')

        if options['apply']:
            with transaction.atomic():
                profile.reels_por_dia = reels
                profile.full_clean()
                profile.save(update_fields=['reels_por_dia', 'updated_at'])
            self.stdout.write(self.style.SUCCESS('Mix social atualizado.'))
        else:
            self.stdout.write('Dry-run: nenhuma alteracao aplicada.')
