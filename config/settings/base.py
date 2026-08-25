import importlib.util
import logging
import os
from pathlib import Path

import dj_database_url


BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    value = env(key)
    if value is None:
        return default
    return value.lower() in {'1', 'true', 'yes', 'on'}


def env_list(key, default=''):
    value = env(key, default)
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def media_root_path():
    return Path(env('MEDIA_ROOT') or env('DJANGO_MEDIA_ROOT') or BASE_DIR / 'media')


SECRET_KEY = env('DJANGO_SECRET_KEY', 'dev-insecure-secret-key')
DEBUG = env_bool('DJANGO_DEBUG', False)
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', '')
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(env('DJANGO_DATA_UPLOAD_MAX_NUMBER_FIELDS', '20000'))
DJANGO_LOG_LEVEL = env('DJANGO_LOG_LEVEL', 'INFO')
LOGIN_RATE_LIMIT = int(env('LOGIN_RATE_LIMIT', '10'))
LOGIN_RATE_LIMIT_WINDOW = int(env('LOGIN_RATE_LIMIT_WINDOW', '300'))
PASSWORD_RESET_RATE_LIMIT = int(env('PASSWORD_RESET_RATE_LIMIT', '5'))
PASSWORD_RESET_RATE_LIMIT_WINDOW = int(env('PASSWORD_RESET_RATE_LIMIT_WINDOW', '3600'))
INVITE_RATE_LIMIT = int(env('INVITE_RATE_LIMIT', '20'))
INVITE_RATE_LIMIT_WINDOW = int(env('INVITE_RATE_LIMIT_WINDOW', '3600'))
OPENAI_API_KEY = env('OPENAI_API_KEY', '')
OPENAI_SOCIAL_MODEL = env('OPENAI_SOCIAL_MODEL', 'gpt-5.6-luna')
OPENAI_SOCIAL_TIMEOUT_SECONDS = int(env('OPENAI_SOCIAL_TIMEOUT_SECONDS', '60'))
OPENAI_SOCIAL_MAX_BATCH = int(env('OPENAI_SOCIAL_MAX_BATCH', '30'))
OPENAI_SOCIAL_MODERATION_MODEL = env('OPENAI_SOCIAL_MODERATION_MODEL', 'omni-moderation-latest')
INSTAGRAM_ACCESS_TOKEN = env('INSTAGRAM_ACCESS_TOKEN', '')
INSTAGRAM_USER_ID = env('INSTAGRAM_USER_ID', '')
INSTAGRAM_API_VERSION = env('INSTAGRAM_API_VERSION', 'v23.0')
INSTAGRAM_EXPECTED_USERNAME = env('INSTAGRAM_EXPECTED_USERNAME', '')
INSTAGRAM_MEDIA_URL_TTL_SECONDS = int(env('INSTAGRAM_MEDIA_URL_TTL_SECONDS', '3600'))
INSTAGRAM_API_TIMEOUT_SECONDS = int(env('INSTAGRAM_API_TIMEOUT_SECONDS', '30'))
SOCIAL_AUTOMATION_CRON_SECRET = env('SOCIAL_AUTOMATION_CRON_SECRET', '')
SOCIAL_AUTOMATION_QUEUE_MIN = int(env('SOCIAL_AUTOMATION_QUEUE_MIN', '40'))
SOCIAL_AUTOMATION_QUEUE_TARGET = int(env('SOCIAL_AUTOMATION_QUEUE_TARGET', '60'))
SOCIAL_AUTOMATION_GENERATION_BATCH = int(env('SOCIAL_AUTOMATION_GENERATION_BATCH', '5'))
SOCIAL_AUTOMATION_MIN_POST_GAP_MINUTES = int(env('SOCIAL_AUTOMATION_MIN_POST_GAP_MINUTES', '30'))
SOCIAL_AUTOMATION_MAX_RETRIES = int(env('SOCIAL_AUTOMATION_MAX_RETRIES', '3'))
SOCIAL_AUTOMATION_HARD_24H_CAP = int(env('SOCIAL_AUTOMATION_HARD_24H_CAP', '30'))
SOCIAL_AUTOMATION_TICK_LOCK_SECONDS = int(env('SOCIAL_AUTOMATION_TICK_LOCK_SECONDS', '240'))
SOCIAL_REEL_MAX_FILE_MB = int(env('SOCIAL_REEL_MAX_FILE_MB', '20'))
SOCIAL_REEL_DURATION_SECONDS = int(env('SOCIAL_REEL_DURATION_SECONDS', '7'))
SOCIAL_REEL_RENDER_TIMEOUT_SECONDS = int(env('SOCIAL_REEL_RENDER_TIMEOUT_SECONDS', '30'))

render_hostname = env('RENDER_EXTERNAL_HOSTNAME')
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'obras',
    'dashboard',
    'controles',
    'propostas',
    'financeiro',
    'medicoes',
    'diarios',
    'usuarios',
    'empresas',
    'social_automation',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'empresas.middleware.EmpresaAtivaMiddleware',
    'config.middleware.LoginRequiredMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = '.'
DECIMAL_SEPARATOR = ','
NUMBER_GROUPING = 3


STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = media_root_path()


LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'login'

PLATFORM_NAME = env('PLATFORM_NAME', 'Sistema de Obras')
PLATFORM_BASE_URL = env('PLATFORM_BASE_URL', '')
PLATFORM_SUPPORT_EMAIL = env('PLATFORM_SUPPORT_EMAIL', '')

EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = env('EMAIL_HOST', '')
EMAIL_PORT = int(env('EMAIL_PORT', '587'))
EMAIL_HOST_USER = env('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', False)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', PLATFORM_SUPPORT_EMAIL or 'no-reply@sistema-obras.local')
SERVER_EMAIL = env('SERVER_EMAIL', DEFAULT_FROM_EMAIL)
PASSWORD_RESET_TIMEOUT = int(env('PASSWORD_RESET_TIMEOUT', '259200'))


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CACHES = {
    'default': {
        'BACKEND': env('DJANGO_CACHE_BACKEND', 'django.core.cache.backends.locmem.LocMemCache'),
        'LOCATION': env('DJANGO_CACHE_LOCATION', 'sistema-obras-default'),
    }
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'console',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': DJANGO_LOG_LEVEL,
    },
    'loggers': {
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

SENTRY_DSN = env('SENTRY_DSN', '')
SENTRY_ENVIRONMENT = env('SENTRY_ENVIRONMENT', 'development' if DEBUG else 'production')
SENTRY_RELEASE = env('SENTRY_RELEASE', '')
SENTRY_TRACES_SAMPLE_RATE = float(env('SENTRY_TRACES_SAMPLE_RATE', '0'))

if SENTRY_DSN:
    if importlib.util.find_spec('sentry_sdk'):
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_options = {
            'dsn': SENTRY_DSN,
            'integrations': [DjangoIntegration()],
            'environment': SENTRY_ENVIRONMENT,
            'traces_sample_rate': SENTRY_TRACES_SAMPLE_RATE,
            'send_default_pii': False,
        }
        if SENTRY_RELEASE:
            sentry_options['release'] = SENTRY_RELEASE
        sentry_sdk.init(**sentry_options)
    else:
        logging.getLogger(__name__).warning('SENTRY_DSN configurado, mas sentry-sdk nao esta instalado.')


SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE', not DEBUG)
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', False)
SECURE_HSTS_SECONDS = int(env('DJANGO_SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', False)
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', False)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'


database_url = env('DATABASE_URL')

if database_url:
    DATABASES = {
        'default': dj_database_url.parse(
            database_url,
            conn_max_age=int(env('POSTGRES_CONN_MAX_AGE', '60')),
            ssl_require=env_bool('POSTGRES_SSL_REQUIRE', True),
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('POSTGRES_DB', ''),
            'USER': env('POSTGRES_USER', ''),
            'PASSWORD': env('POSTGRES_PASSWORD', ''),
            'HOST': env('POSTGRES_HOST', 'localhost'),
            'PORT': env('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': int(env('POSTGRES_CONN_MAX_AGE', '60')),
        }
    }
