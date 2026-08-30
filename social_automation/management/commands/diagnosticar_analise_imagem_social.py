from django.core.management.base import BaseCommand, CommandError

from social_automation.image_analysis import analyze_social_image, image_analysis_available
from social_automation.models import SocialBaseImage


class Command(BaseCommand):
    help = 'Diagnostica a analise visual de uma imagem-base social.'

    def add_arguments(self, parser):
        parser.add_argument('base_image_id')
        parser.add_argument('--persist', action='store_true', help='Grava resultado e regioes protegidas automaticas.')

    def handle(self, *args, **options):
        image = SocialBaseImage.objects.select_related('profile').filter(pk=options['base_image_id']).first()
        if not image:
            raise CommandError('Imagem-base nao encontrada.')
        self.stdout.write(f'Imagem: {image.id} - {image.nome}')
        self.stdout.write(f'Perfil: {image.profile.nome} ({image.profile.username})')
        self.stdout.write(f'Disponivel: {image_analysis_available()}')
        result = analyze_social_image(image.profile, image, persist=options['persist'])
        self.stdout.write(f'Assunto: {result.subject_position}')
        self.stdout.write(f'Foco: {result.focal_x}, {result.focal_y}')
        self.stdout.write(f'Zonas seguras: {", ".join(result.safe_zones) or "-"}')
        self.stdout.write(f'Regioes protegidas: {len(result.protected_regions)}')
        self.stdout.write(f'Confianca: {result.confidence}')
        if result.error:
            self.stdout.write(self.style.WARNING(result.error))
        if options['persist']:
            self.stdout.write(self.style.SUCCESS('Analise persistida quando atingiu confianca minima.'))
        else:
            self.stdout.write(self.style.WARNING('DRY RUN: nenhum dado foi alterado.'))
