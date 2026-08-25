import urllib.error
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from social_automation.instagram import resumir_video_url, url_video_meta_compat
from social_automation.models import SocialContent
from social_automation.video_rendering import auditar_video_reel


class Command(BaseCommand):
    help = 'Diagnostica um Reel local e sua URL assinada, sem publicar.'

    def add_arguments(self, parser):
        parser.add_argument('content_id', type=int)

    def handle(self, *args, **options):
        content = SocialContent.objects.select_related('profile').filter(pk=options['content_id']).first()
        if not content:
            raise CommandError('Conteudo nao encontrado.')
        if not content.is_reel:
            raise CommandError('Este conteudo nao esta marcado como Reel.')

        audit = auditar_video_reel(content)
        video_url = url_video_meta_compat(content)
        resumo = resumir_video_url(video_url)
        self.stdout.write(f'Arquivo: {audit["format"]}')
        self.stdout.write(f'Tamanho: {audit["bytes"]} bytes')
        self.stdout.write(f'Duracao: {audit["duration"]}s')
        self.stdout.write(f'Resolucao: {audit["width"]}x{audit["height"]}')
        self.stdout.write(f'Codec: {audit["codec"]}')
        self.stdout.write(f'URL HTTPS: {resumo["scheme"] == "https"}')
        self.stdout.write(f'URL: {resumo["path_structure"]}')

        request = urllib.request.Request(video_url, method='HEAD', headers={'User-Agent': 'facebookexternalhit/1.1'})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                self.stdout.write(f'HTTP: {response.status}')
                self.stdout.write(f'Content-Type: {response.headers.get("Content-Type")}')
                self.stdout.write(f'Content-Length: {response.headers.get("Content-Length")}')
                self.stdout.write('Meta-UA: facebookexternalhit/1.1')
                self.stdout.write(f'Meta-ready: {response.status == 200}')
        except urllib.error.HTTPError as exc:
            self.stdout.write(f'HTTP: {exc.code}')
            self.stdout.write('Meta-ready: False')
