from io import BytesIO
from hashlib import sha256
import urllib.error
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from social_automation.instagram import InstagramConfigurationError, auditar_imagem_final, resumir_image_url, url_midia_temporaria
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

        normal = self._fetch(url)
        meta = self._fetch(url, user_agent='facebookexternalhit/1.1')
        head = self._fetch(url, method='HEAD')
        robots = self._fetch_robots(url)
        status = normal['status']
        redirected = normal['redirected']
        content_type = normal['content_type']
        body = normal['body']
        with content.final_image.storage.open(content.final_image.name, 'rb') as arquivo:
            storage_body = arquivo.read()
        storage_sha = sha256(storage_body).hexdigest()
        http_sha = sha256(body).hexdigest()
        resumo = resumir_image_url(url)

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
        self.stdout.write('URL type: META_COMPAT')
        self.stdout.write(f'URL length: {resumo["length"]}')
        self.stdout.write(f'HTTP: {status}')
        self.stdout.write(f'HTTP normal: {normal["status"]}')
        self.stdout.write(f'HTTP Meta-UA: {meta["status"]}')
        self.stdout.write(f'GET status: {normal["status"]}')
        self.stdout.write(f'HEAD status: {head["status"]}')
        self.stdout.write(f'Redirect: {"SIM" if redirected else "NAO"}')
        self.stdout.write(f'Content-Type: {content_type or "-"}')
        self.stdout.write(f'Content-Length: {normal["headers"].get("Content-Length") or "-"}')
        self.stdout.write(f'Transfer-Encoding: {normal["headers"].get("Transfer-Encoding") or "-"}')
        self.stdout.write(f'Content-Encoding: {normal["headers"].get("Content-Encoding") or "-"}')
        self.stdout.write(f'Content-Disposition: {normal["headers"].get("Content-Disposition") or "-"}')
        self.stdout.write(f'Content-Type normal: {normal["content_type"] or "-"}')
        self.stdout.write(f'Content-Type Meta-UA: {meta["content_type"] or "-"}')
        self.stdout.write(f'HEAD Content-Type: {head["content_type"] or "-"}')
        self.stdout.write(f'HEAD Content-Length: {head["headers"].get("Content-Length") or "-"}')
        self.stdout.write(f'Bytes: {len(body)}')
        self.stdout.write(f'Bytes normal: {len(normal["body"])}')
        self.stdout.write(f'Bytes Meta-UA: {len(meta["body"])}')
        self.stdout.write(f'robots HTTP: {robots["status"]}')
        self.stdout.write(f'signed-media bloqueada: {robots["blocked"]}')
        self.stdout.write(f'JPEG signature: {"OK" if jpeg_signature else "ERRO"}')
        self.stdout.write(f'Pillow format: {pillow_format}')
        self.stdout.write(f'Dimensoes: {dimensions}')
        self.stdout.write(f'Arquivo local: {auditoria["format"]} {auditoria["width"]}x{auditoria["height"]} {auditoria["bytes"]} bytes')
        self.stdout.write(f'SHA256 storage: {storage_sha}')
        self.stdout.write(f'SHA256 HTTP: {http_sha}')
        self.stdout.write(f'Bytes identicos: {"SIM" if storage_body == body else "NAO"}')
        self.stdout.write(f'Meta-ready: {"SIM" if ok else "NAO"}')
        if not ok:
            raise CommandError('A midia ainda nao esta pronta para a Meta.')

    def _fetch(self, url, *, method='GET', user_agent='sistema-obras-instagram-media-check/1.0'):
        request = urllib.request.Request(url, headers={'User-Agent': user_agent}, method=method)
        try:
            opener = urllib.request.build_opener(NoRedirectHandler)
            response = opener.open(request, timeout=30)
            return {
                'status': response.status,
                'redirected': False,
                'content_type': response.headers.get('Content-Type', ''),
                'headers': dict(response.headers.items()),
                'body': response.read() if method != 'HEAD' else b'',
            }
        except urllib.error.HTTPError as exc:
            return {
                'status': exc.code,
                'redirected': exc.code in {301, 302, 303, 307, 308},
                'content_type': exc.headers.get('Content-Type', ''),
                'headers': dict(exc.headers.items()),
                'body': exc.read() if method != 'HEAD' else b'',
            }

    def _fetch_robots(self, url):
        parsed = urllib.parse.urlparse(url)
        robots_url = f'{parsed.scheme}://{parsed.netloc}/robots.txt'
        result = self._fetch(robots_url)
        text = result['body'].decode('utf-8', errors='ignore').lower()
        blocked = 'INDETERMINADO'
        if result['status'] == 200:
            if 'disallow: /social-media/public' in text or 'disallow: /' in text:
                blocked = 'SIM'
            else:
                blocked = 'NAO'
        return {'status': result['status'], 'blocked': blocked}


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
