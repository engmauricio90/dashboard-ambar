import json
import logging
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import SocialCarouselSlide, SocialContent, SocialContentEvent, SocialInstagramConnection, SocialProfile, SocialPublishAttempt
from .token_crypto import InstagramTokenEncryptionError
from .container_versioning import (
    REEL_SHARE_TO_FEED,
    build_instagram_caption,
    calculate_instagram_carousel_slide_fingerprint,
    calculate_instagram_container_fingerprint,
    invalidate_instagram_container,
)
from .services import registrar_evento
from .video_rendering import auditar_video_reel


logger = logging.getLogger(__name__)

GRAPH_HOST = 'https://graph.instagram.com'
MEDIA_SIGNING_SALT = 'social-automation-instagram-media'
MEDIA_META_SIGNING_SALT = 'social-automation-instagram-meta-media'
VIDEO_META_SIGNING_SALT = 'social-automation-instagram-meta-video'
CAROUSEL_META_SIGNING_SALT = 'social-automation-instagram-meta-carousel'
PUBLICADO_INSTAGRAM = 'publicado_instagram'
PUBLISH_CONFIRMATION_PENDING_MESSAGE = (
    'Publicacao pendente de confirmacao. A Meta pode ja ter publicado este conteudo. '
    'Uma nova publicacao automatica foi bloqueada para evitar duplicidade.'
)
PUBLISH_ACTIVE_STATUSES = {
    SocialPublishAttempt.Status.PREPARED,
    SocialPublishAttempt.Status.PROVIDER_CALLED,
    SocialPublishAttempt.Status.AMBIGUOUS,
}


class InstagramConfigurationError(Exception):
    pass


class InstagramAPIError(Exception):
    def __init__(self, message, *, status=None, code=None, error_type=None, subcode=None, is_transient=None, user_title='', user_msg='', fbtrace_id=''):
        super().__init__(message)
        self.status = status
        self.code = code
        self.error_type = error_type
        self.subcode = subcode
        self.is_transient = is_transient
        self.user_title = user_title
        self.user_msg = user_msg
        self.fbtrace_id = fbtrace_id


class InstagramPublishError(Exception):
    pass


class InstagramContainerPending(Exception):
    pass


@dataclass(frozen=True)
class InstagramCredentials:
    access_token: str
    instagram_user_id: str
    username: str = ''
    connection: SocialInstagramConnection | None = None
    is_legacy: bool = False


def _normalize_username(value):
    return (value or '').strip().lstrip('@').lower()


def normalize_instagram_account_type(value):
    account_type = (value or '').strip().upper()
    aliases = {
        'MEDIA_CREATOR': SocialInstagramConnection.AccountType.CREATOR,
        'CREATOR': SocialInstagramConnection.AccountType.CREATOR,
        'MEDIA_BUSINESS': SocialInstagramConnection.AccountType.BUSINESS,
        'BUSINESS': SocialInstagramConnection.AccountType.BUSINESS,
        SocialInstagramConnection.AccountType.DESCONHECIDO: SocialInstagramConnection.AccountType.DESCONHECIDO,
    }
    return aliases.get(account_type, account_type)


def is_publishable_instagram_account_type(value):
    return normalize_instagram_account_type(value) in {
        SocialInstagramConnection.AccountType.BUSINESS,
        SocialInstagramConnection.AccountType.CREATOR,
    }


def display_instagram_account_type(value):
    normalized = normalize_instagram_account_type(value)
    labels = {
        SocialInstagramConnection.AccountType.BUSINESS: 'Business',
        SocialInstagramConnection.AccountType.CREATOR: 'Creator',
        SocialInstagramConnection.AccountType.DESCONHECIDO: 'Desconhecido',
    }
    if normalized in labels:
        return labels[normalized]
    return value or 'acessivel'


def _legacy_credentials_for_profile(profile=None):
    if not settings.SOCIAL_INSTAGRAM_LEGACY_FALLBACK:
        return None
    expected = _normalize_username(settings.INSTAGRAM_EXPECTED_USERNAME)
    profile_username = _normalize_username(profile.username if profile else expected)
    if profile and expected and profile_username != expected:
        return None
    if not settings.INSTAGRAM_ACCESS_TOKEN or not settings.INSTAGRAM_USER_ID:
        return None
    return InstagramCredentials(
        access_token=settings.INSTAGRAM_ACCESS_TOKEN,
        instagram_user_id=settings.INSTAGRAM_USER_ID,
        username=expected or profile_username,
        is_legacy=True,
    )


def get_instagram_credentials(profile=None, *, allow_legacy=True):
    if isinstance(profile, SocialContent):
        profile = profile.profile
    if profile:
        connection = getattr(profile, 'instagram_connection', None)
        if connection and connection.is_active:
            try:
                token = connection.get_access_token()
            except InstagramTokenEncryptionError as exc:
                raise InstagramConfigurationError(str(exc)) from exc
            return InstagramCredentials(
                access_token=token,
                instagram_user_id=connection.instagram_user_id,
                username=connection.username,
                connection=connection,
            )
        expected = _normalize_username(settings.INSTAGRAM_EXPECTED_USERNAME)
        profile_username = _normalize_username(profile.username)
        if allow_legacy and settings.INSTAGRAM_ACCESS_TOKEN and settings.INSTAGRAM_USER_ID and expected and profile_username != expected:
            raise InstagramPublishError('Este conteudo pertence a outro perfil social e nao pode ser publicado nesta conta Instagram.')
        if allow_legacy:
            legacy = _legacy_credentials_for_profile(profile)
            if legacy:
                return legacy
        if allow_legacy:
            raise InstagramConfigurationError('Conecte uma conta Instagram neste perfil ou configure INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_USER_ID.')
        raise InstagramConfigurationError('Conecte uma conta Instagram neste perfil antes de publicar.')

    legacy = _legacy_credentials_for_profile(None) if allow_legacy else None
    if legacy:
        return legacy
    raise InstagramConfigurationError('Configure uma conexao Instagram para o perfil.')


def _token(credentials=None):
    credentials = credentials or get_instagram_credentials()
    token = credentials.access_token
    if not token:
        raise InstagramConfigurationError('Conecte uma conta Instagram para usar a integracao.')
    return token


def _ig_user_id(credentials=None):
    credentials = credentials or get_instagram_credentials()
    user_id = credentials.instagram_user_id
    if not user_id:
        raise InstagramConfigurationError('A conexao Instagram nao possui User ID.')
    return user_id


def verificar_configuracao_instagram(profile=None):
    credentials = get_instagram_credentials(profile)
    _token(credentials)
    _ig_user_id(credentials)
    return True


def _url(path):
    version = settings.INSTAGRAM_API_VERSION.strip('/') or 'v23.0'
    return f'{GRAPH_HOST}/{version}/{path.lstrip("/")}'


def _decode_response(response):
    body = response.read().decode('utf-8')
    return json.loads(body) if body else {}


def _request_url(method, url, params=None):
    params = params or {}
    data = None
    headers = {}
    if method == 'GET':
        query = urllib.parse.urlencode(params)
        if query:
            url = f'{url}?{query}'
    else:
        data = urllib.parse.urlencode(params).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=settings.INSTAGRAM_API_TIMEOUT_SECONDS) as response:
            return _decode_response(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        error = payload.get('error') or {}
        message = error.get('message') or 'Erro de comunicacao com a API do Instagram.'
        raise InstagramAPIError(_sanitize_error(message), status=exc.code, code=error.get('code'), error_type=error.get('type')) from exc


def _request(method, path, params=None, *, credentials=None):
    token = _token(credentials)
    params = params or {}
    data = None
    url = _url(path)
    headers = {'Authorization': f'Bearer {token}'}
    if method == 'GET':
        query = urllib.parse.urlencode(params)
        if query:
            url = f'{url}?{query}'
    else:
        data = urllib.parse.urlencode(params).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=settings.INSTAGRAM_API_TIMEOUT_SECONDS) as response:
            return _decode_response(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        error = payload.get('error') or {}
        code = error.get('code')
        subcode = error.get('error_subcode')
        message = error.get('message') or 'Erro de comunicacao com a API do Instagram.'
        logger.warning(
            'Instagram API error status=%s code=%s subcode=%s type=%s fbtrace_id=%s path=%s',
            exc.code,
            code,
            subcode,
            error.get('type'),
            error.get('fbtrace_id'),
            path,
        )
        raise InstagramAPIError(
            _sanitize_error(message).replace(token, '[token]'),
            status=exc.code,
            code=code,
            error_type=error.get('type'),
            subcode=subcode,
            is_transient=error.get('is_transient'),
            user_title=_sanitize_error(error.get('error_user_title', '')).replace(token, '[token]'),
            user_msg=_sanitize_error(error.get('error_user_msg', '')).replace(token, '[token]'),
            fbtrace_id=error.get('fbtrace_id', ''),
        ) from exc
    except Exception as exc:
        logger.warning('Instagram API unavailable path=%s error=%s', path, type(exc).__name__)
        raise InstagramAPIError('Nao foi possivel comunicar com a API do Instagram agora.') from exc


def _request_with_credentials(method, path, params=None, *, credentials=None):
    try:
        return _request(method, path, params, credentials=credentials)
    except TypeError as exc:
        if 'unexpected keyword argument' in str(exc):
            return _request(method, path, params)
        raise


def _sanitize_error(message):
    text = str(message or 'Erro de comunicacao com a API do Instagram.')
    for secret in [settings.INSTAGRAM_ACCESS_TOKEN]:
        if secret:
            text = text.replace(secret, '[token]')
    text = _sanitize_signed_urls(text)
    return text[:500]


def _sanitize_signed_urls(text):
    if not text:
        return ''
    text = str(text)
    text = re.sub(r'(/social-media/ig/\d+/)[^\s"\']+(\.jpg)?', r'\1[signed-token]\2', text)
    text = re.sub(r'(/social-media/ig-video/\d+/)[^\s"\']+(\.mp4)?', r'\1[signed-token]\2', text)
    text = re.sub(r'(/social-media/ig-carousel/\d+/\d+/)[^\s"\']+(\.jpg)?', r'\1[signed-token]\2', text)
    text = re.sub(r'(/social-media/public-jpg/)[^\s"\']+(/imagem\.jpg)?', r'\1[signed-token]\2', text)
    text = re.sub(r'(/social-media/public/)[^\s"\']+', r'\1[signed-token]/', text)
    return text


def resumir_image_url(image_url):
    parsed = urllib.parse.urlparse(image_url)
    path = parsed.path or ''
    if re.search(r'/social-media/ig/\d+/', path):
        path_structure = re.sub(r'(/social-media/ig/\d+/).+(\.jpg)$', r'\1[signed-token]\2', path)
    elif '/social-media/public-jpg/' in path:
        path_structure = '/social-media/public-jpg/[signed-token]/imagem.jpg'
    elif '/social-media/public/' in path:
        path_structure = '/social-media/public/[signed-token]/'
    else:
        path_structure = path
    return {
        'scheme': parsed.scheme,
        'host': parsed.netloc,
        'path_structure': path_structure,
        'length': len(image_url),
        'sha256': sha256(image_url.encode('utf-8')).hexdigest(),
        'has_jpg': path.lower().endswith('.jpg') or path.lower().endswith('.jpeg'),
    }


def resumir_video_url(video_url):
    parsed = urllib.parse.urlparse(video_url)
    path = parsed.path or ''
    if re.search(r'/social-media/ig-video/\d+/', path):
        path_structure = re.sub(r'(/social-media/ig-video/\d+/).+(\.mp4)$', r'\1[signed-token]\2', path)
    else:
        path_structure = path
    return {
        'scheme': parsed.scheme,
        'host': parsed.netloc,
        'path_structure': path_structure,
        'length': len(video_url),
        'sha256': sha256(video_url.encode('utf-8')).hexdigest(),
        'has_mp4': path.lower().endswith('.mp4'),
    }


def resumir_carousel_slide_url(image_url):
    parsed = urllib.parse.urlparse(image_url)
    path = parsed.path or ''
    if re.search(r'/social-media/ig-carousel/\d+/\d+/', path):
        path_structure = re.sub(r'(/social-media/ig-carousel/\d+/\d+/).+(\.jpg)$', r'\1[signed-token]\2', path)
    else:
        path_structure = path
    return {
        'scheme': parsed.scheme,
        'host': parsed.netloc,
        'path_structure': path_structure,
        'length': len(image_url),
        'sha256': sha256(image_url.encode('utf-8')).hexdigest(),
        'has_jpg': path.lower().endswith('.jpg') or path.lower().endswith('.jpeg'),
    }


def obter_conta_instagram(profile=None, *, credentials=None):
    credentials = credentials or get_instagram_credentials(profile)
    data = _request_with_credentials('GET', _ig_user_id(credentials), {'fields': 'id,username,account_type,media_count'}, credentials=credentials)
    expected = _normalize_username(credentials.username)
    username = _normalize_username(data.get('username'))
    if expected and username and username != expected:
        raise InstagramConfigurationError('A conta Instagram conectada nao corresponde ao username esperado.')
    return data


def obter_permissoes_instagram(profile=None, *, credentials=None):
    credentials = credentials or get_instagram_credentials(profile)
    try:
        return _request_with_credentials('GET', 'me/permissions', credentials=credentials)
    except InstagramAPIError:
        return None


def instagram_oauth_redirect_uri(request=None):
    configured = (settings.SOCIAL_INSTAGRAM_OAUTH_REDIRECT_URI or '').strip()
    if configured:
        return configured
    if request is None:
        raise InstagramConfigurationError('Configure SOCIAL_INSTAGRAM_OAUTH_REDIRECT_URI.')
    return request.build_absolute_uri(reverse('social_automation:instagram_callback'))


def build_instagram_oauth_url(state, *, request=None):
    if not settings.SOCIAL_INSTAGRAM_CLIENT_ID:
        raise InstagramConfigurationError('Configure SOCIAL_INSTAGRAM_CLIENT_ID para conectar o Instagram.')
    scopes = (settings.SOCIAL_INSTAGRAM_OAUTH_SCOPES or '').replace(' ', '')
    params = {
        'client_id': settings.SOCIAL_INSTAGRAM_CLIENT_ID,
        'redirect_uri': instagram_oauth_redirect_uri(request),
        'scope': scopes,
        'response_type': 'code',
        'state': state,
        'enable_fb_login': '0',
        'force_authentication': '1',
    }
    return f'https://www.instagram.com/oauth/authorize?{urllib.parse.urlencode(params)}'


def exchange_instagram_code(code, *, request=None):
    if not settings.SOCIAL_INSTAGRAM_CLIENT_ID or not settings.SOCIAL_INSTAGRAM_CLIENT_SECRET:
        raise InstagramConfigurationError('Configure SOCIAL_INSTAGRAM_CLIENT_ID e SOCIAL_INSTAGRAM_CLIENT_SECRET.')
    short_lived = _request_url(
        'POST',
        'https://api.instagram.com/oauth/access_token',
        {
            'client_id': settings.SOCIAL_INSTAGRAM_CLIENT_ID,
            'client_secret': settings.SOCIAL_INSTAGRAM_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'redirect_uri': instagram_oauth_redirect_uri(request),
            'code': code,
        },
    )
    access_token = short_lived.get('access_token')
    if not access_token:
        raise InstagramAPIError('A Meta nao retornou access token.')
    long_lived = _request_url(
        'GET',
        f'{GRAPH_HOST}/access_token',
        {
            'grant_type': 'ig_exchange_token',
            'client_secret': settings.SOCIAL_INSTAGRAM_CLIENT_SECRET,
            'access_token': access_token,
        },
    )
    token = long_lived.get('access_token') or access_token
    expires_in = long_lived.get('expires_in')
    return {
        'access_token': token,
        'expires_in': expires_in,
        'user_id': str(short_lived.get('user_id') or ''),
    }


def criar_ou_atualizar_conexao_instagram(profile, *, access_token, instagram_user_id='', username='', account_type='', token_expires_at=None):
    temp_credentials = InstagramCredentials(
        access_token=access_token,
        instagram_user_id=instagram_user_id or 'me',
        username=username,
    )
    conta = _request_with_credentials('GET', instagram_user_id or 'me', {'fields': 'id,username,account_type'}, credentials=temp_credentials)
    ig_user_id = str(conta.get('id') or instagram_user_id or '')
    if not ig_user_id:
        raise InstagramAPIError('A Meta nao retornou Instagram User ID.')
    username = conta.get('username') or username or profile.username
    account_type = normalize_instagram_account_type(conta.get('account_type') or account_type or SocialInstagramConnection.AccountType.DESCONHECIDO)
    if account_type != SocialInstagramConnection.AccountType.DESCONHECIDO and not is_publishable_instagram_account_type(account_type):
        raise InstagramConfigurationError('A conta Instagram precisa ser Business ou Creator para publicar pela API.')
    connection, _created = SocialInstagramConnection.objects.get_or_create(
        profile=profile,
        defaults={
            'instagram_user_id': ig_user_id,
            'username': username,
            'account_type': account_type,
            'token_expires_at': token_expires_at,
        },
    )
    connection.instagram_user_id = ig_user_id
    connection.username = username
    connection.account_type = account_type
    connection.token_expires_at = token_expires_at
    connection.is_active = True
    connection.set_access_token(access_token)
    connection.last_validation_status = SocialInstagramConnection.ValidationStatus.OK
    connection.last_validation_error = ''
    connection.last_validated_at = timezone.now()
    connection.save()
    return connection


def validar_conexao_instagram(connection):
    credentials = get_instagram_credentials(connection.profile, allow_legacy=False)
    conta = obter_conta_instagram(credentials=credentials)
    username = _normalize_username(conta.get('username'))
    if username and username != connection.normalized_username:
        raise InstagramConfigurationError('A conta retornada pela Meta nao corresponde ao username salvo nesta conexao.')
    account_type = normalize_instagram_account_type(conta.get('account_type') or '')
    if account_type and not is_publishable_instagram_account_type(account_type):
        raise InstagramConfigurationError('A conta Instagram precisa ser Business ou Creator para publicar pela API.')
    connection.account_type = account_type or connection.account_type
    connection.mark_validation(ok=True)
    if account_type:
        connection.save(update_fields=['account_type', 'updated_at'])
    return conta


def gerar_token_midia_temporaria(content):
    if not content.final_image:
        raise InstagramPublishError('Renderize o card final antes de publicar.')
    return signing.dumps(
        {'content_id': content.id, 'file': content.final_image.name},
        salt=MEDIA_SIGNING_SALT,
    )


def gerar_assinatura_midia_meta(content):
    if not content.final_image:
        raise InstagramPublishError('Renderize o card final antes de publicar.')
    signed_value = signing.TimestampSigner(salt=MEDIA_META_SIGNING_SALT).sign(str(content.id))
    prefix = f'{content.id}:'
    if not signed_value.startswith(prefix):
        raise InstagramPublishError('Nao foi possivel gerar a assinatura temporaria da midia.')
    return signed_value[len(prefix):]


def gerar_assinatura_video_meta(content):
    if not content.final_video:
        raise InstagramPublishError('Renderize o Reel antes de publicar.')
    signed_value = signing.TimestampSigner(salt=VIDEO_META_SIGNING_SALT).sign(str(content.id))
    prefix = f'{content.id}:'
    if not signed_value.startswith(prefix):
        raise InstagramPublishError('Nao foi possivel gerar a assinatura temporaria do video.')
    return signed_value[len(prefix):]


def gerar_assinatura_carousel_slide_meta(slide):
    if not slide.get_final_image():
        raise InstagramPublishError('Renderize o slide antes de publicar.')
    signed_value = signing.TimestampSigner(salt=CAROUSEL_META_SIGNING_SALT).sign(f'{slide.content_id}:{slide.id}')
    prefix = f'{slide.content_id}:{slide.id}:'
    if not signed_value.startswith(prefix):
        raise InstagramPublishError('Nao foi possivel gerar a assinatura temporaria do slide.')
    return signed_value[len(prefix):]


def auditar_imagem_final(content):
    if not content.final_image:
        raise InstagramPublishError('Renderize o card final antes de publicar.')
    with content.final_image.storage.open(content.final_image.name, 'rb') as arquivo:
        header = arquivo.read(3)
        arquivo.seek(0, 2)
        size = arquivo.tell()
        arquivo.seek(0)
        try:
            image = Image.open(arquivo)
            image.load()
        except Exception as exc:
            raise InstagramPublishError('A imagem final nao e um arquivo de imagem valido.') from exc
    if image.format != 'JPEG' or header != b'\xff\xd8\xff':
        raise InstagramPublishError('A imagem final precisa ser JPEG valido para publicacao no Instagram.')
    if image.mode != 'RGB':
        raise InstagramPublishError('A imagem final precisa estar em RGB.')
    return {
        'name': content.final_image.name,
        'extension': Path(content.final_image.name).suffix.lower(),
        'format': image.format,
        'mode': image.mode,
        'width': image.width,
        'height': image.height,
        'bytes': size,
        'jpeg_signature': header == b'\xff\xd8\xff',
    }


def auditar_imagem_slide_carrossel(slide):
    media = slide.get_final_image()
    if not media:
        raise InstagramPublishError('Renderize o slide antes de publicar.')
    with media.storage.open(media.name, 'rb') as arquivo:
        header = arquivo.read(3)
        arquivo.seek(0, 2)
        size = arquivo.tell()
        arquivo.seek(0)
        try:
            image = Image.open(arquivo)
            image.load()
        except Exception as exc:
            raise InstagramPublishError('O slide renderizado nao e um arquivo de imagem valido.') from exc
    if image.format != 'JPEG' or header != b'\xff\xd8\xff':
        raise InstagramPublishError('O slide precisa ser JPEG valido para publicacao no Instagram.')
    if image.mode != 'RGB':
        raise InstagramPublishError('O slide precisa estar em RGB.')
    if (image.width, image.height) not in {(1080, 1080), (1080, 1350)}:
        raise InstagramPublishError('O slide precisa estar em 1080x1080 ou 1080x1350.')
    return {
        'name': media.name,
        'format': image.format,
        'mode': image.mode,
        'width': image.width,
        'height': image.height,
        'bytes': size,
    }


def validar_token_midia_temporaria(token):
    try:
        payload = signing.loads(token, salt=MEDIA_SIGNING_SALT, max_age=settings.INSTAGRAM_MEDIA_URL_TTL_SECONDS)
    except signing.BadSignature as exc:
        raise ValidationError('Assinatura invalida ou expirada.') from exc
    content = SocialContent.objects.filter(pk=payload.get('content_id')).first()
    if not content or not content.final_image or content.final_image.name != payload.get('file'):
        raise ValidationError('Assinatura invalida ou expirada.')
    return content


def validar_assinatura_midia_meta(content_id, signature):
    signed_value = f'{content_id}:{signature}'
    try:
        unsigned = signing.TimestampSigner(salt=MEDIA_META_SIGNING_SALT).unsign(
            signed_value,
            max_age=settings.INSTAGRAM_MEDIA_URL_TTL_SECONDS,
        )
    except signing.BadSignature as exc:
        raise ValidationError('Assinatura invalida ou expirada.') from exc
    if str(unsigned) != str(content_id):
        raise ValidationError('Assinatura invalida ou expirada.')
    content = SocialContent.objects.filter(pk=content_id).first()
    if not content or not content.final_image:
        raise ValidationError('Assinatura invalida ou expirada.')
    return content


def validar_assinatura_video_meta(content_id, signature):
    signed_value = f'{content_id}:{signature}'
    try:
        unsigned = signing.TimestampSigner(salt=VIDEO_META_SIGNING_SALT).unsign(
            signed_value,
            max_age=settings.INSTAGRAM_MEDIA_URL_TTL_SECONDS,
        )
    except signing.BadSignature as exc:
        raise ValidationError('Assinatura invalida ou expirada.') from exc
    if str(unsigned) != str(content_id):
        raise ValidationError('Assinatura invalida ou expirada.')
    content = SocialContent.objects.filter(pk=content_id).first()
    if not content or not content.final_video:
        raise ValidationError('Assinatura invalida ou expirada.')
    return content


def validar_assinatura_carousel_slide_meta(content_id, slide_id, signature):
    signed_value = f'{content_id}:{slide_id}:{signature}'
    try:
        unsigned = signing.TimestampSigner(salt=CAROUSEL_META_SIGNING_SALT).unsign(
            signed_value,
            max_age=settings.INSTAGRAM_MEDIA_URL_TTL_SECONDS,
        )
    except signing.BadSignature as exc:
        raise ValidationError('Assinatura invalida ou expirada.') from exc
    if str(unsigned) != f'{content_id}:{slide_id}':
        raise ValidationError('Assinatura invalida ou expirada.')
    slide = SocialCarouselSlide.objects.select_related('content').filter(pk=slide_id, content_id=content_id, is_active=True).first()
    if not slide or not slide.get_final_image():
        raise ValidationError('Assinatura invalida ou expirada.')
    return slide


def url_midia_meta_compat(content):
    base_url = (settings.PLATFORM_BASE_URL or '').rstrip('/')
    if not base_url.startswith('https://'):
        raise InstagramConfigurationError('Configure PLATFORM_BASE_URL com uma URL HTTPS publica antes de publicar.')
    auditar_imagem_final(content)
    signature = gerar_assinatura_midia_meta(content)
    return f'{base_url}{reverse("social_public_final_image_meta_compat", args=[content.id, signature])}'


def url_video_meta_compat(content):
    base_url = (settings.PLATFORM_BASE_URL or '').rstrip('/')
    if not base_url.startswith('https://'):
        raise InstagramConfigurationError('Configure PLATFORM_BASE_URL com uma URL HTTPS publica antes de publicar.')
    auditar_video_reel(content)
    signature = gerar_assinatura_video_meta(content)
    return f'{base_url}{reverse("social_public_final_video_meta_compat", args=[content.id, signature])}'


def url_carousel_slide_meta_compat(slide):
    base_url = (settings.PLATFORM_BASE_URL or '').rstrip('/')
    if not base_url.startswith('https://'):
        raise InstagramConfigurationError('Configure PLATFORM_BASE_URL com uma URL HTTPS publica antes de publicar.')
    auditar_imagem_slide_carrossel(slide)
    signature = gerar_assinatura_carousel_slide_meta(slide)
    return f'{base_url}{reverse("social_public_carousel_slide_meta_compat", args=[slide.content_id, slide.id, signature])}'


def url_midia_temporaria(content, *, com_extensao_jpg=False, legacy=False):
    base_url = (settings.PLATFORM_BASE_URL or '').rstrip('/')
    if not base_url.startswith('https://'):
        raise InstagramConfigurationError('Configure PLATFORM_BASE_URL com uma URL HTTPS publica antes de publicar.')
    if not legacy:
        return url_midia_meta_compat(content)
    auditar_imagem_final(content)
    token = gerar_token_midia_temporaria(content)
    route = 'social_public_final_image_jpg' if com_extensao_jpg else 'social_public_final_image'
    return f'{base_url}{reverse(route, args=[token])}'


def montar_caption(content):
    return build_instagram_caption(content)


def criar_container_imagem(image_url, caption, *, credentials=None):
    credentials = credentials or get_instagram_credentials()
    payload = {'image_url': image_url, 'caption': caption}
    resumo = resumir_image_url(image_url)
    logger.info(
        'Instagram creating image container endpoint=%s content_type=image image_url_scheme=%s image_url_host=%s image_url_path_structure=%s image_url_length=%s image_url_sha256=%s',
        f'{_ig_user_id(credentials)}/media',
        resumo['scheme'],
        resumo['host'],
        resumo['path_structure'],
        resumo['length'],
        resumo['sha256'],
    )
    start = time.monotonic()
    logger.info('media_container_request_start image_url_sha256=%s', resumo['sha256'])
    try:
        data = _request_with_credentials('POST', f'{_ig_user_id(credentials)}/media', payload, credentials=credentials)
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info('media_container_request_end duration_ms=%s image_url_sha256=%s', duration_ms, resumo['sha256'])
    container_id = data.get('id')
    if not container_id:
        raise InstagramAPIError('A API do Instagram nao retornou o container de midia.')
    logger.info('Instagram media container created container_id=%s', container_id)
    return container_id


def criar_container_reel(video_url, caption, *, credentials=None):
    credentials = credentials or get_instagram_credentials()
    payload = {'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'share_to_feed': REEL_SHARE_TO_FEED}
    resumo = resumir_video_url(video_url)
    logger.info(
        'Instagram creating reel container endpoint=%s content_type=video video_url_scheme=%s video_url_host=%s video_url_path_structure=%s video_url_length=%s video_url_sha256=%s',
        f'{_ig_user_id(credentials)}/media',
        resumo['scheme'],
        resumo['host'],
        resumo['path_structure'],
        resumo['length'],
        resumo['sha256'],
    )
    data = _request_with_credentials('POST', f'{_ig_user_id(credentials)}/media', payload, credentials=credentials)
    container_id = data.get('id')
    if not container_id:
        raise InstagramAPIError('A API do Instagram nao retornou o container de Reel.')
    logger.info('Instagram reel container created container_id=%s', container_id)
    return container_id


def criar_container_carousel_child(image_url, *, credentials=None):
    credentials = credentials or get_instagram_credentials()
    payload = {'image_url': image_url, 'is_carousel_item': 'true'}
    resumo = resumir_carousel_slide_url(image_url)
    logger.info(
        'Instagram creating carousel child endpoint=%s image_url_scheme=%s image_url_host=%s image_url_path_structure=%s image_url_sha256=%s',
        f'{_ig_user_id(credentials)}/media',
        resumo['scheme'],
        resumo['host'],
        resumo['path_structure'],
        resumo['sha256'],
    )
    data = _request_with_credentials('POST', f'{_ig_user_id(credentials)}/media', payload, credentials=credentials)
    container_id = data.get('id')
    if not container_id:
        raise InstagramAPIError('A API do Instagram nao retornou o container filho do carrossel.')
    logger.info('Instagram carousel child created container_id=%s', container_id)
    return container_id


def criar_container_carousel_parent(children, caption, *, credentials=None):
    credentials = credentials or get_instagram_credentials()
    payload = {'media_type': 'CAROUSEL', 'children': ','.join(children), 'caption': caption}
    data = _request_with_credentials('POST', f'{_ig_user_id(credentials)}/media', payload, credentials=credentials)
    container_id = data.get('id')
    if not container_id:
        raise InstagramAPIError('A API do Instagram nao retornou o container pai do carrossel.')
    logger.info('Instagram carousel parent created container_id=%s children=%s', container_id, len(children))
    return container_id


def _call_with_optional_credentials(func, *args, credentials=None):
    if credentials and credentials.is_legacy:
        return func(*args)
    try:
        return func(*args, credentials=credentials)
    except TypeError as exc:
        if 'unexpected keyword argument' in str(exc):
            return func(*args)
        raise


def consultar_container(container_id, *, credentials=None):
    return _request_with_credentials('GET', container_id, {'fields': 'id,status_code'}, credentials=credentials)


def aguardar_container_pronto(container_id, attempts=5, interval=3, *, credentials=None):
    for attempt in range(attempts):
        data = consultar_container(container_id, credentials=credentials)
        status_code = data.get('status_code')
        if status_code in {'FINISHED', 'PUBLISHED'}:
            return data
        if status_code in {'ERROR', 'EXPIRED'}:
            raise InstagramAPIError(f'Container de midia retornou status {status_code}.')
        if attempt < attempts - 1:
            time.sleep(interval)
    raise InstagramAPIError('Container de midia nao ficou pronto dentro do tempo esperado.')


def status_container_pronto(container_id, *, credentials=None):
    data = consultar_container(container_id, credentials=credentials)
    status_code = data.get('status_code')
    if status_code in {'FINISHED', 'PUBLISHED'}:
        return True
    if status_code in {'ERROR', 'EXPIRED'}:
        raise InstagramAPIError(f'Container de midia retornou status {status_code}.')
    return False


def publicar_container(container_id, *, credentials=None):
    credentials = credentials or get_instagram_credentials()
    data = _request_with_credentials('POST', f'{_ig_user_id(credentials)}/media_publish', {'creation_id': container_id}, credentials=credentials)
    media_id = data.get('id')
    if not media_id:
        raise InstagramAPIError('A API do Instagram nao retornou o ID da publicacao.')
    logger.info('Instagram media published media_id=%s container_id=%s', media_id, container_id)
    return media_id


def obter_midia_publicada(media_id, *, credentials=None):
    try:
        return _request_with_credentials('GET', media_id, {'fields': 'id,permalink'}, credentials=credentials)
    except InstagramAPIError:
        return {'id': media_id}


def validar_username_profile(content, *, credentials=None):
    credentials = credentials or get_instagram_credentials(content.profile)
    expected = _normalize_username(credentials.username)
    profile_username = _normalize_username(content.profile.username)
    if expected and profile_username and profile_username != expected:
        raise InstagramPublishError('Este conteudo pertence a outro perfil social e nao pode ser publicado nesta conta Instagram.')


def _marcar_publicando(content_id, *, credentials=None):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().select_related('profile').get(pk=content_id)
        if content.status not in {SocialContent.Status.APROVADO, SocialContent.Status.RETRY_LIBERADO_MANUAL, SocialContent.Status.AGENDADO, SocialContent.Status.ERRO}:
            raise InstagramPublishError('Somente conteudos aprovados, liberados manualmente, agendados ou em erro podem ser publicados.')
        if not content.final_media_ready:
            raise InstagramPublishError('Renderize a midia final antes de publicar.')
        if content.external_post_id:
            raise InstagramPublishError('Este conteudo ja possui publicacao vinculada.')
        validar_username_profile(content, credentials=credentials)
        content.status = SocialContent.Status.PUBLICANDO
        content.tentativas += 1
        content.ultima_tentativa = timezone.now()
        content.erro = ''
        content.save(update_fields=['status', 'tentativas', 'ultima_tentativa', 'erro', 'updated_at'])
        return content


def _latest_publish_attempt(content):
    return content.publish_attempts.filter(provider=SocialPublishAttempt.Provider.INSTAGRAM).order_by('-started_at', '-id').first()


def reconcile_publish_state(content, usuario=None):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().select_related('profile').get(pk=content.pk)
        attempt = _latest_publish_attempt(content)
        external_post_id = content.external_post_id or (attempt.external_post_id if attempt else '')
        if external_post_id:
            now = timezone.now()
            content.status = SocialContent.Status.PUBLICADO
            content.published_at = content.published_at or now
            content.external_post_id = external_post_id
            content.erro = ''
            content.instagram_container_id = ''
            content.instagram_container_fingerprint = ''
            content.save(
                update_fields=[
                    'status',
                    'published_at',
                    'external_post_id',
                    'erro',
                    'instagram_container_id',
                    'instagram_container_fingerprint',
                    'updated_at',
                ]
            )
            if content.is_carousel:
                content.carousel_slides.exclude(instagram_container_id='').update(
                    instagram_container_id='',
                    instagram_container_fingerprint='',
                    updated_at=now,
                )
            if attempt and attempt.status != SocialPublishAttempt.Status.CONFIRMED:
                attempt.status = SocialPublishAttempt.Status.CONFIRMED
                attempt.external_post_id = external_post_id
                attempt.provider_response_at = attempt.provider_response_at or now
                attempt.error_class = ''
                attempt.error_message = ''
                attempt.save(update_fields=['status', 'external_post_id', 'provider_response_at', 'error_class', 'error_message', 'updated_at'])
            registrar_evento(content, SocialContentEvent.Acao.PUBLISH_RECONCILIATION, usuario, f'Estado local reconciliado. Media ID: {external_post_id}')
            return content
        if attempt and attempt.status == SocialPublishAttempt.Status.AMBIGUOUS:
            content.status = SocialContent.Status.PUBLISH_CONFIRMATION_PENDING
            content.erro = PUBLISH_CONFIRMATION_PENDING_MESSAGE
            content.save(update_fields=['status', 'erro', 'updated_at'])
        return content


def _prepare_publish_attempt(content_id, *, credentials=None):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().select_related('profile').get(pk=content_id)
        content = reconcile_publish_state(content)
        content = SocialContent.objects.select_for_update().select_related('profile').get(pk=content_id)
        if content.status == SocialContent.Status.PUBLICADO:
            return content, None
        if content.external_post_id:
            return reconcile_publish_state(content), None
        if content.status == SocialContent.Status.PUBLISH_CONFIRMATION_PENDING:
            raise InstagramPublishError(PUBLISH_CONFIRMATION_PENDING_MESSAGE)
        active_attempt = content.publish_attempts.filter(provider=SocialPublishAttempt.Provider.INSTAGRAM, status__in=PUBLISH_ACTIVE_STATUSES).first()
        if active_attempt:
            if active_attempt.status == SocialPublishAttempt.Status.AMBIGUOUS:
                content.status = SocialContent.Status.PUBLISH_CONFIRMATION_PENDING
                content.erro = PUBLISH_CONFIRMATION_PENDING_MESSAGE
                content.save(update_fields=['status', 'erro', 'updated_at'])
                raise InstagramPublishError(PUBLISH_CONFIRMATION_PENDING_MESSAGE)
            raise InstagramPublishError('Ja existe uma tentativa de publicacao em andamento para este conteudo.')
        if content.status not in {SocialContent.Status.APROVADO, SocialContent.Status.RETRY_LIBERADO_MANUAL, SocialContent.Status.AGENDADO, SocialContent.Status.ERRO}:
            raise InstagramPublishError('Somente conteudos aprovados, liberados manualmente, agendados ou em erro podem ser publicados.')
        if not content.final_media_ready:
            raise InstagramPublishError('Renderize a midia final antes de publicar.')
        validar_username_profile(content, credentials=credentials)
        fingerprint = calculate_instagram_container_fingerprint(content, credentials.instagram_user_id if credentials else '')
        attempt = SocialPublishAttempt.objects.create(
            content=content,
            provider=SocialPublishAttempt.Provider.INSTAGRAM,
            fingerprint=fingerprint,
            status=SocialPublishAttempt.Status.PREPARED,
            metadata={'media_type': content.media_type, 'profile_id': content.profile_id},
        )
        content.status = SocialContent.Status.PUBLICANDO
        content.tentativas += 1
        content.ultima_tentativa = timezone.now()
        content.erro = ''
        content.save(update_fields=['status', 'tentativas', 'ultima_tentativa', 'erro', 'updated_at'])
        registrar_evento(content, SocialContentEvent.Acao.PUBLISH_PREPARED, None, f'Tentativa #{attempt.id} preparada.')
        return content, attempt


def _salvar_container_reel(content_id, container_id, fingerprint):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().get(pk=content_id)
        content.instagram_container_id = container_id
        content.instagram_container_fingerprint = fingerprint
        content.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
        return content


def _salvar_container_carrossel(content_id, container_id, fingerprint):
    return _salvar_container_reel(content_id, container_id, fingerprint)


def _salvar_container_slide(slide_id, container_id, fingerprint):
    with transaction.atomic():
        slide = SocialCarouselSlide.objects.select_for_update().get(pk=slide_id)
        slide.instagram_container_id = container_id
        slide.instagram_container_fingerprint = fingerprint
        slide.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
        return slide


def _marcar_reel_pendente(content_id, message='Container de Reel ainda em processamento.'):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().get(pk=content_id)
        content.status = SocialContent.Status.AGENDADO
        content.scheduled_at = timezone.now() + timedelta(minutes=10)
        content.erro = message
        content.save(update_fields=['status', 'scheduled_at', 'erro', 'updated_at'])
        return content


def _mark_attempt_failed_safe(attempt_id, exc):
    if not attempt_id:
        return None
    with transaction.atomic():
        attempt = SocialPublishAttempt.objects.select_for_update().get(pk=attempt_id)
        attempt.status = SocialPublishAttempt.Status.FAILED_SAFE
        attempt.error_class = type(exc).__name__
        attempt.error_message = _sanitize_error(str(exc))
        attempt.save(update_fields=['status', 'error_class', 'error_message', 'updated_at'])
        registrar_evento(attempt.content, SocialContentEvent.Acao.PUBLISH_RETRY_RELEASED, None, f'Tentativa #{attempt.id} falhou antes do media_publish; retry permanece seguro.')
        return attempt


def _mark_attempt_provider_called(attempt_id, container_id, fingerprint=''):
    with transaction.atomic():
        attempt = SocialPublishAttempt.objects.select_for_update().get(pk=attempt_id)
        attempt.status = SocialPublishAttempt.Status.PROVIDER_CALLED
        attempt.container_id = container_id or attempt.container_id
        attempt.fingerprint = fingerprint or attempt.fingerprint
        attempt.provider_called_at = timezone.now()
        attempt.save(update_fields=['status', 'container_id', 'fingerprint', 'provider_called_at', 'updated_at'])
        registrar_evento(attempt.content, SocialContentEvent.Acao.PUBLISH_PROVIDER_CALLED, None, f'Tentativa #{attempt.id}; container {container_id}.')
        return attempt


def _mark_publish_ambiguous(content_id, attempt_id, exc):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().get(pk=content_id)
        attempt = SocialPublishAttempt.objects.select_for_update().filter(pk=attempt_id).first()
        message = _sanitize_error(str(exc))
        if attempt and attempt.external_post_id:
            return reconcile_publish_state(content)
        if content.external_post_id:
            return reconcile_publish_state(content)
        if attempt:
            attempt.status = SocialPublishAttempt.Status.AMBIGUOUS
            attempt.error_class = type(exc).__name__
            attempt.error_message = message
            attempt.save(update_fields=['status', 'error_class', 'error_message', 'updated_at'])
        content.status = SocialContent.Status.PUBLISH_CONFIRMATION_PENDING
        content.erro = PUBLISH_CONFIRMATION_PENDING_MESSAGE
        content.ultima_tentativa = timezone.now()
        content.save(update_fields=['status', 'erro', 'ultima_tentativa', 'updated_at'])
        registrar_evento(content, SocialContentEvent.Acao.PUBLISH_AMBIGUOUS, None, f'Tentativa #{attempt_id}: {message}')
        logger.warning('instagram_publish_ambiguous content_id=%s attempt_id=%s error_class=%s', content_id, attempt_id, type(exc).__name__)
        return content


def _persist_external_post_id(content_id, attempt_id, media_id):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().get(pk=content_id)
        attempt = SocialPublishAttempt.objects.select_for_update().get(pk=attempt_id)
        attempt.external_post_id = media_id
        attempt.provider_response_at = timezone.now()
        attempt.save(update_fields=['external_post_id', 'provider_response_at', 'updated_at'])
        content.external_post_id = media_id
        content.save(update_fields=['external_post_id', 'updated_at'])
        return content


def _marcar_publicado(content_id, media_id, permalink, usuario=None, attempt_id=None):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().get(pk=content_id)
        if content.external_post_id and content.external_post_id != media_id:
            raise InstagramPublishError('Conteudo ja possui outra publicacao vinculada.')
        content.status = SocialContent.Status.PUBLICADO
        content.published_at = timezone.now()
        content.external_post_id = media_id
        content.external_permalink = permalink or ''
        content.instagram_container_id = ''
        content.instagram_container_fingerprint = ''
        content.erro = ''
        content.save(
            update_fields=[
                'status',
                'published_at',
                'external_post_id',
                'external_permalink',
                'instagram_container_id',
                'instagram_container_fingerprint',
                'erro',
                'updated_at',
            ]
        )
        if content.is_carousel:
            content.carousel_slides.exclude(instagram_container_id='').update(
                instagram_container_id='',
                instagram_container_fingerprint='',
                updated_at=timezone.now(),
            )
        if attempt_id:
            attempt = SocialPublishAttempt.objects.select_for_update().get(pk=attempt_id)
            attempt.status = SocialPublishAttempt.Status.CONFIRMED
            attempt.external_post_id = media_id
            attempt.provider_response_at = attempt.provider_response_at or timezone.now()
            attempt.error_class = ''
            attempt.error_message = ''
            attempt.save(update_fields=['status', 'external_post_id', 'provider_response_at', 'error_class', 'error_message', 'updated_at'])
            registrar_evento(content, SocialContentEvent.Acao.PUBLISH_CONFIRMED, usuario, f'Tentativa #{attempt.id}; Media ID: {media_id}')
        registrar_evento(content, PUBLICADO_INSTAGRAM, usuario, f'Media ID: {media_id}')
        return content


def _container_reel_atual_ou_novo(content, caption, *, credentials):
    current_fingerprint = calculate_instagram_container_fingerprint(content, credentials.instagram_user_id)
    if content.instagram_container_id:
        if content.instagram_container_fingerprint == current_fingerprint:
            logger.info(
                'instagram_container_reuse content_id=%s media_type=%s container_id=%s fingerprint_prefix=%s',
                content.id,
                content.media_type,
                content.instagram_container_id,
                current_fingerprint[:12],
            )
            return content.instagram_container_id
        logger.info(
            'instagram_container_stale content_id=%s media_type=%s old_container_id=%s old_fingerprint_prefix=%s new_fingerprint_prefix=%s',
            content.id,
            content.media_type,
            content.instagram_container_id,
            (content.instagram_container_fingerprint or '')[:12],
            current_fingerprint[:12],
        )
        invalidate_instagram_container(content, reason='fingerprint_changed')

    video_url = url_video_meta_compat(content)
    container_id = _call_with_optional_credentials(criar_container_reel, video_url, caption, credentials=credentials)
    _salvar_container_reel(content.id, container_id, current_fingerprint)
    logger.info(
        'instagram_container_created content_id=%s media_type=%s container_id=%s fingerprint_prefix=%s',
        content.id,
        content.media_type,
        container_id,
        current_fingerprint[:12],
    )
    return container_id


def _container_carrossel_atual_ou_novo(content, caption, *, credentials):
    current_fingerprint = calculate_instagram_container_fingerprint(content, credentials.instagram_user_id)
    if content.instagram_container_id and content.instagram_container_fingerprint == current_fingerprint:
        logger.info('instagram_carousel_parent_reuse content_id=%s container_id=%s', content.id, content.instagram_container_id)
        return content.instagram_container_id
    if content.instagram_container_id:
        invalidate_instagram_container(content, reason='carousel_fingerprint_changed')

    slides = list(content.carousel_slides.filter(is_active=True).order_by('order', 'id'))
    if len(slides) < 2 or len(slides) > 10:
        raise InstagramPublishError('Carrossel precisa ter entre 2 e 10 slides ativos.')

    child_ids = []
    for slide in slides:
        slide_fingerprint = calculate_instagram_carousel_slide_fingerprint(slide, credentials.instagram_user_id)
        if slide.instagram_container_id and slide.instagram_container_fingerprint == slide_fingerprint:
            child_ids.append(slide.instagram_container_id)
            continue
        if slide.instagram_container_id:
            slide.instagram_container_id = ''
            slide.instagram_container_fingerprint = ''
            slide.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
        image_url = url_carousel_slide_meta_compat(slide)
        child_id = _call_with_optional_credentials(criar_container_carousel_child, image_url, credentials=credentials)
        _call_with_optional_credentials(aguardar_container_pronto, child_id, credentials=credentials)
        _salvar_container_slide(slide.id, child_id, slide_fingerprint)
        child_ids.append(child_id)

    parent_id = _call_with_optional_credentials(criar_container_carousel_parent, child_ids, caption, credentials=credentials)
    _salvar_container_carrossel(content.id, parent_id, current_fingerprint)
    return parent_id


def _marcar_erro(content_id, message):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().get(pk=content_id)
        content.status = SocialContent.Status.ERRO
        content.erro = _sanitize_error(message)
        content.ultima_tentativa = timezone.now()
        content.save(update_fields=['status', 'erro', 'ultima_tentativa', 'updated_at'])
        return content


def publicar_conteudo_instagram(content, usuario=None):
    logger.info('publication_start content_id=%s', content.id)
    attempt = None
    media_id = ''
    provider_called = False
    try:
        credentials = get_instagram_credentials(content.profile)
        was_already_published = (
            SocialContent.objects.filter(pk=content.pk).values_list('status', flat=True).first()
            == SocialContent.Status.PUBLICADO
        )
        content = reconcile_publish_state(content, usuario=usuario)
        if content.status == SocialContent.Status.PUBLICADO:
            if was_already_published:
                raise InstagramPublishError('Conteudo ja esta publicado.')
            return content
        content, attempt = _prepare_publish_attempt(content.id, credentials=credentials)
        if attempt is None:
            return content
        verificar_configuracao_instagram(content.profile)
        obter_conta_instagram(credentials=credentials)
        caption = montar_caption(content)
        fingerprint = calculate_instagram_container_fingerprint(content, credentials.instagram_user_id)
        if content.is_reel:
            auditar_video_reel(content)
            container_id = _container_reel_atual_ou_novo(content, caption, credentials=credentials)
            if not _call_with_optional_credentials(status_container_pronto, container_id, credentials=credentials):
                _mark_attempt_failed_safe(attempt.id, InstagramContainerPending('Container de Reel ainda em processamento.'))
                _marcar_reel_pendente(content.id)
                raise InstagramContainerPending('Container de Reel ainda em processamento; publicacao sera retomada no proximo tick.')
        elif content.is_carousel:
            for slide in content.carousel_slides.filter(is_active=True):
                auditar_imagem_slide_carrossel(slide)
            container_id = _container_carrossel_atual_ou_novo(content, caption, credentials=credentials)
            _call_with_optional_credentials(aguardar_container_pronto, container_id, credentials=credentials)
        else:
            auditar_imagem_final(content)
            image_url = url_midia_temporaria(content)
            container_id = _call_with_optional_credentials(criar_container_imagem, image_url, caption, credentials=credentials)
            _salvar_container_reel(content.id, container_id, fingerprint)
            _call_with_optional_credentials(aguardar_container_pronto, container_id, credentials=credentials)
        _mark_attempt_provider_called(attempt.id, container_id, fingerprint)
        provider_called = True
        media_id = _call_with_optional_credentials(publicar_container, container_id, credentials=credentials)
        _persist_external_post_id(content.id, attempt.id, media_id)
        try:
            media = _call_with_optional_credentials(obter_midia_publicada, media_id, credentials=credentials)
        except Exception as exc:
            logger.warning('instagram_permalink_lookup_failed content_id=%s attempt_id=%s error_class=%s', content.id, attempt.id, type(exc).__name__)
            media = {'id': media_id}
        return _marcar_publicado(content.id, media_id, media.get('permalink'), usuario, attempt_id=attempt.id)
    except InstagramContainerPending:
        raise
    except Exception as exc:
        if attempt and provider_called:
            reconciled = _mark_publish_ambiguous(content.id, attempt.id, exc)
            if reconciled.status == SocialContent.Status.PUBLICADO:
                return reconciled
        else:
            if attempt:
                _mark_attempt_failed_safe(attempt.id, exc)
                _marcar_erro(content.id, str(exc))
            else:
                current_status = SocialContent.objects.filter(pk=content.id).values_list('status', flat=True).first()
                safe_publish_block = isinstance(exc, InstagramPublishError) and (
                    current_status == SocialContent.Status.PUBLISH_CONFIRMATION_PENDING
                    or 'tentativa de publicacao em andamento' in str(exc)
                    or 'pendente de confirmacao' in str(exc)
                    or 'Somente conteudos aprovados' in str(exc)
                    or 'Conteudo ja esta publicado' in str(exc)
                    or 'publicacao vinculada' in str(exc)
                )
                if not safe_publish_block:
                    _marcar_erro(content.id, str(exc))
        if isinstance(exc, (InstagramConfigurationError, InstagramAPIError, InstagramPublishError)):
            raise
        raise InstagramPublishError('Falha inesperada ao publicar no Instagram.') from exc
