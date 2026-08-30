from django.core.management.base import BaseCommand, CommandError

from social_automation.autonomous_carousel import gerar_carrossel_autonomo
from social_automation.models import SocialProfile


class Command(BaseCommand):
    help = 'Gera um carrossel IA como rascunho. Nunca publica.'

    def add_arguments(self, parser):
        parser.add_argument('perfil')
        parser.add_argument('--tema', default='')
        parser.add_argument('--slides', type=int, default=None)

    def handle(self, *args, **options):
        profile = SocialProfile.objects.filter(username=options['perfil']).first() or SocialProfile.objects.filter(pk=options['perfil']).first()
        if not profile:
            raise CommandError('Perfil nao encontrado.')
        result = gerar_carrossel_autonomo(profile, tema=options['tema'], slides=options['slides'])
        content = result.content
        self.stdout.write(self.style.SUCCESS(f'Carrossel criado como rascunho: #{content.id}'))
        self.stdout.write(f'Slides: {content.carousel_slides.filter(is_active=True).count()}')
        self.stdout.write(f'Imagens IA: {result.generated_images}')
        self.stdout.write(f'Imagens banco: {result.selected_bank_images}')
        self.stdout.write(f'Slides texto: {result.full_text_slides}')
        for message in result.messages:
            self.stdout.write(self.style.WARNING(message))
