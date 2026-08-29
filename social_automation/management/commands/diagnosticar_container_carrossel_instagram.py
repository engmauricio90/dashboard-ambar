from django.core.management.base import BaseCommand, CommandError

from social_automation.instagram import (
    InstagramAPIError,
    InstagramConfigurationError,
    InstagramPublishError,
    criar_container_carousel_child,
    criar_container_carousel_parent,
    get_instagram_credentials,
    montar_caption,
    url_carousel_slide_meta_compat,
)
from social_automation.models import SocialContent


class Command(BaseCommand):
    help = 'Cria containers de carrossel no Instagram para diagnostico, sem publicar.'

    def add_arguments(self, parser):
        parser.add_argument('content_id', type=int)

    def handle(self, *args, **options):
        content = SocialContent.objects.select_related('profile').filter(pk=options['content_id']).first()
        if not content:
            raise CommandError('Conteudo nao encontrado.')
        if not content.is_carousel:
            raise CommandError('O conteudo informado nao e carrossel.')
        if not content.final_media_ready:
            raise CommandError('Renderize o carrossel antes do diagnostico.')
        try:
            credentials = get_instagram_credentials(content.profile)
            child_ids = []
            for slide in content.carousel_slides.filter(is_active=True).order_by('order', 'id'):
                child_id = criar_container_carousel_child(url_carousel_slide_meta_compat(slide), credentials=credentials)
                child_ids.append(child_id)
            parent_id = criar_container_carousel_parent(child_ids, montar_caption(content), credentials=credentials)
        except (InstagramConfigurationError, InstagramAPIError, InstagramPublishError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write('Containers criados sem publicar.')
        self.stdout.write(f'Filhos: {len(child_ids)}')
        self.stdout.write(f'Pai: {parent_id}')
