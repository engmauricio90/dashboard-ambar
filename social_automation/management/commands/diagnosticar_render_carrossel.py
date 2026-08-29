from django.core.management.base import BaseCommand, CommandError

from social_automation.models import SocialContent
from social_automation.rendering import SocialRenderError, renderizar_midia_social


class Command(BaseCommand):
    help = 'Renderiza e audita localmente um conteudo de carrossel, sem publicar.'

    def add_arguments(self, parser):
        parser.add_argument('content_id', type=int)

    def handle(self, *args, **options):
        content = SocialContent.objects.filter(pk=options['content_id']).first()
        if not content:
            raise CommandError('Conteudo nao encontrado.')
        if not content.is_carousel:
            raise CommandError('O conteudo informado nao e carrossel.')
        try:
            renderizar_midia_social(content)
        except SocialRenderError as exc:
            raise CommandError(str(exc)) from exc
        slides = content.carousel_slides.filter(is_active=True).order_by('order')
        self.stdout.write(f'Carrossel #{content.id} renderizado.')
        self.stdout.write(f'Slides ativos: {slides.count()}')
        for slide in slides:
            self.stdout.write(f'- slide {slide.order}: {slide.rendered_image.name if slide.rendered_image else "sem imagem"}')
