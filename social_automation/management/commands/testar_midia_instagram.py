from io import BytesIO
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from social_automation.instagram import InstagramConfigurationError, auditar_imagem_final, url_midia_temporaria
from social_automation.models import SocialContent


class Command(BaseCommand):
    help = 'Valida, sem publicar, a URL assinada da imagem final que sera enviada para a Instagram API.'

    def add_arguments(self, parser):
        parser.add_argument('content_id', type=int)

    def handle(self, *args, **options):
        content = SocialContent.objects.filter(pk=options['content_id']).first()
        if not content:
            raise CommandError('Conteudo nao encontrado.')

        try:
            auditoria = auditar_imagem_final(content)
            url = url_midia_temporaria(content)
        except InstagramConfigurationError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if not url.startswith('https://'):
            raise CommandError('URL HTTPS: ERRO')

        request = urllib.request.Request(url, headers={'User-Agent': 'sistema-obras-instagram-media-check/1.0'})
        try:
            opener = urllib.request.build_opener(NoRedirectHandler)
            response = opener.open(request, timeout=30)
            status = response.status
            redirected = False
            content_type = response.headers.get('Content-Type', '')
            body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            redirected = exc.code in {301, 302, 303, 307, 308}
            content_type = exc.headers.get('Content-Type', '')
            body = exc.read()

        jpeg_signature = body.startswith(b'\xff\xd8\xff')
        pillow_format = '-'
        dimensions = '-'
        if jpeg_signature:
            image = Image.open(BytesIO(body))
            pillow_format = image.format
            dimensions = f'{image.width}x{image.height}'

        ok = (
            status == 200
            and not redirected
            and content_type.split(';')[0].strip().lower() == 'image/jpeg'
            and len(body) > 0
            and jpeg_signature
            and pillow_format == 'JPEG'
        )

        self.stdout.write('URL HTTPS: OK')
        self.stdout.write(f'HTTP: {status}')
        self.stdout.write(f'Redirect: {"SIM" if redirected else "NAO"}')
        self.stdout.write(f'Content-Type: {content_type or "-"}')
        self.stdout.write(f'Bytes: {len(body)}')
        self.stdout.write(f'JPEG signature: {"OK" if jpeg_signature else "ERRO"}')
        self.stdout.write(f'Pillow format: {pillow_format}')
        self.stdout.write(f'Dimensoes: {dimensions}')
        self.stdout.write(f'Arquivo local: {auditoria["format"]} {auditoria["width"]}x{auditoria["height"]} {auditoria["bytes"]} bytes')
        self.stdout.write(f'Meta-ready: {"SIM" if ok else "NAO"}')
        if not ok:
            raise CommandError('A midia ainda nao esta pronta para a Meta.')


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
