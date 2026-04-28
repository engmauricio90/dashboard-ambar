from .base import *


DEBUG = False

if not SECRET_KEY or SECRET_KEY == 'dev-insecure-secret-key':
    raise ValueError('Defina DJANGO_SECRET_KEY para o ambiente de producao.')

if not env('DATABASE_URL'):
    if not DATABASES['default']['NAME']:
        raise ValueError('Defina POSTGRES_DB ou DATABASE_URL para o ambiente de producao.')

    if not DATABASES['default']['USER']:
        raise ValueError('Defina POSTGRES_USER ou DATABASE_URL para o ambiente de producao.')

    if not DATABASES['default']['PASSWORD']:
        raise ValueError('Defina POSTGRES_PASSWORD ou DATABASE_URL para o ambiente de producao.')

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
SECURE_HSTS_SECONDS = int(env('DJANGO_SECURE_HSTS_SECONDS', '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', True)
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', True)
