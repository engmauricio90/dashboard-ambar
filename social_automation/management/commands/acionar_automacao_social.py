import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Aciona o tick de automacao social pelo Web Service, sem acessar media local.'

    def handle(self, *args, **options):
        base_url = (settings.PLATFORM_BASE_URL or '').rstrip('/')
        secret = settings.SOCIAL_AUTOMATION_CRON_SECRET
        if not base_url.startswith('https://'):
            raise CommandError('Configure PLATFORM_BASE_URL com HTTPS publico.')
        if not secret:
            raise CommandError('Configure SOCIAL_AUTOMATION_CRON_SECRET.')

        url = f'{base_url}/internal/social-automation/tick/'
        request = urllib.request.Request(
            url,
            data=b'',
            method='POST',
            headers={'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            raise CommandError(f'Tick falhou com HTTP {exc.code}: {body[:300]}') from exc
        except Exception as exc:
            raise CommandError(f'Nao foi possivel acionar o tick: {type(exc).__name__}') from exc

        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {'raw': body[:300]}
        self.stdout.write(json.dumps(payload, ensure_ascii=False))
