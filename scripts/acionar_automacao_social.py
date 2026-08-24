#!/usr/bin/env python
import json
import os
import sys
import urllib.error
import urllib.request


TIMEOUT_SECONDS = 120


def build_url(base_url):
    return f'{base_url.rstrip("/")}/internal/social-automation/tick/'


def trigger(env=None, opener=None, stdout=None, stderr=None):
    env = env or os.environ
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    base_url = (env.get('PLATFORM_BASE_URL') or '').strip()
    secret = env.get('SOCIAL_AUTOMATION_CRON_SECRET') or ''

    if not base_url.startswith('https://'):
        stderr.write('PLATFORM_BASE_URL precisa ser uma URL HTTPS publica.\n')
        return 1
    if not secret:
        stderr.write('SOCIAL_AUTOMATION_CRON_SECRET nao configurado.\n')
        return 1

    url = build_url(base_url)
    request = urllib.request.Request(
        url,
        data=b'{}',
        method='POST',
        headers={
            'Authorization': f'Bearer {secret}',
            'Content-Type': 'application/json',
        },
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode('utf-8', errors='replace')
            status = getattr(response, 'status', 200)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        stderr.write(f'Tick falhou com HTTP {exc.code}: {_sanitize(body, secret)}\n')
        return 1
    except Exception as exc:
        stderr.write(f'Nao foi possivel acionar o tick em {url}: {type(exc).__name__}\n')
        return 1

    if status < 200 or status >= 300:
        stderr.write(f'Tick falhou com HTTP {status}: {_sanitize(body, secret)}\n')
        return 1
    stdout.write(_sanitize(body or json.dumps({'status': 'ok'}), secret) + '\n')
    return 0


def _sanitize(text, secret=''):
    sanitized = str(text or '')
    if secret:
        sanitized = sanitized.replace(secret, '[secret]')
    return sanitized[:1000]


def main():
    return trigger()


if __name__ == '__main__':
    raise SystemExit(main())
