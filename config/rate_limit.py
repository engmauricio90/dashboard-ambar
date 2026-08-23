import hashlib
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone


def client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for and request.META.get('HTTP_X_FORWARDED_PROTO'):
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or 'unknown'


def normalized(value):
    return (value or '').strip().casefold()


def rate_limit_key(scope, *parts):
    raw = ':'.join([scope, *[str(part) for part in parts]])
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return f'rate-limit:{digest}'


def check_rate_limit(scope, parts, limit, window_seconds):
    key = rate_limit_key(scope, *parts)
    now = timezone.now()
    payload = cache.get(key)
    if payload is None:
        cache.set(key, {'count': 1, 'first_seen': now.isoformat()}, timeout=window_seconds)
        return False, 1

    count = int(payload.get('count', 0)) + 1
    payload['count'] = count
    cache.set(key, payload, timeout=window_seconds)
    return count > limit, count


def too_many_requests(message=None):
    return HttpResponse(
        message or 'Muitas tentativas em pouco tempo. Aguarde alguns minutos e tente novamente.',
        status=429,
        content_type='text/plain; charset=utf-8',
    )


def invite_rate_limited(request, vinculo):
    return check_rate_limit(
        'invite',
        [
            client_ip(request),
            getattr(request.user, 'pk', 'anonymous'),
            vinculo.empresa_id,
            normalized(vinculo.usuario.email),
        ],
        settings.INVITE_RATE_LIMIT,
        settings.INVITE_RATE_LIMIT_WINDOW,
    )[0]


def post_rate_limit(scope, limit_setting, window_setting, identity_getter):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.method == 'POST':
                blocked, _count = check_rate_limit(
                    scope,
                    identity_getter(request),
                    getattr(settings, limit_setting),
                    getattr(settings, window_setting),
                )
                if blocked:
                    return too_many_requests()
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
