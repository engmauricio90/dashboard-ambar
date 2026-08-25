from django.core.management.base import BaseCommand, CommandError

from social_automation.container_versioning import calculate_instagram_container_fingerprint
from social_automation.instagram import criar_container_reel, montar_caption, url_video_meta_compat
from social_automation.models import SocialContent
from social_automation.video_rendering import auditar_video_reel


class Command(BaseCommand):
    help = 'Cria container de Reel na Meta para diagnostico, sem executar media_publish.'

    def add_arguments(self, parser):
        parser.add_argument('content_id', type=int)

    def handle(self, *args, **options):
        content = SocialContent.objects.select_related('profile').filter(pk=options['content_id']).first()
        if not content:
            raise CommandError('Conteudo nao encontrado.')
        if not content.is_reel:
            raise CommandError('Este conteudo nao esta marcado como Reel.')
        auditar_video_reel(content)
        video_url = url_video_meta_compat(content)
        container_id = criar_container_reel(video_url, montar_caption(content))
        fingerprint = calculate_instagram_container_fingerprint(content)
        content.instagram_container_id = container_id
        content.instagram_container_fingerprint = fingerprint
        content.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
        self.stdout.write(f'Container criado: {container_id}')
        self.stdout.write(f'Fingerprint: {fingerprint[:12]}...')
        self.stdout.write('media_publish: NAO executado')
