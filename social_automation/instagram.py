import json
import logging
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import SocialContent
from .services import registrar_evento


logger = logging.getLogger(__name__)

GRAPH_HOST = 'https://graph.instagram.com'
MEDIA_SIGNING_SALT = 'social-automation-instagram-media'
MEDIA_META_SIGNING_SALT = 'social-automation-instagram-meta-media'
PUBLICADO_INSTAGRAM = 'publicado_instagram'


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


def _token():
    token = settings.INSTAGRAM_ACCESS_TOKEN
    if not token:
        raise InstagramConfigurationError('Configure INSTAGRAM_ACCESS_TOKEN para usar a integracao com Instagram.')
    return token


def _ig_user_id():
    user_id = settings.INSTAGRAM_USER_ID
    if not user_id:
        raise InstagramConfigurationError('Configure INSTAGRAM_USER_ID para usar a integracao com Instagram.')
    return user_id


def verificar_configuracao_instagram():
    _token()
    _ig_user_id()
    return True


def _url(path):
    version = settings.INSTAGRAM_API_VERSION.strip('/') or 'v23.0'
    return f'{GRAPH_HOST}/{version}/{path.lstrip("/")}'


def _request(method, path, params=None):
    token = _token()
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
            body = response.read().decode('utf-8')
            return json.loads(body) if body else {}
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
            _sanitize_error(message),
            status=exc.code,
            code=code,
            error_type=error.get('type'),
            subcode=subcode,
            is_transient=error.get('is_transient'),
            user_title=_sanitize_error(error.get('error_user_title', '')),
            user_msg=_sanitize_error(error.get('error_user_msg', '')),
            fbtrace_id=error.get('fbtrace_id', ''),
        ) from exc
    except Exception as exc:
        logger.warning('Instagram API unavailable path=%s error=%s', path, type(exc).__name__)
        raise InstagramAPIError('Nao foi possivel comunicar com a API do Instagram agora.') from exc


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


def obter_conta_instagram():
    data = _request('GET', _ig_user_id(), {'fields': 'id,username,account_type,media_count'})
    expected = (settings.INSTAGRAM_EXPECTED_USERNAME or '').strip().lstrip('@').lower()
    username = (data.get('username') or '').strip().lstrip('@').lower()
    if expected and username and username != expected:
        raise InstagramConfigurationError('A conta Instagram conectada nao corresponde ao username esperado.')
    return data


def obter_permissoes_instagram():
    try:
        return _request('GET', 'me/permissions')
    except InstagramAPIError:
        return None


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


def url_midia_meta_compat(content):
    base_url = (settings.PLATFORM_BASE_URL or '').rstrip('/')
    if not base_url.startswith('https://'):
        raise InstagramConfigurationError('Configure PLATFORM_BASE_URL com uma URL HTTPS publica antes de publicar.')
    auditar_imagem_final(content)
    signature = gerar_assinatura_midia_meta(content)
    return f'{base_url}{reverse("social_public_final_image_meta_compat", args=[content.id, signature])}'


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
    partes = []
    if content.legenda:
        partes.append(content.legenda.strip())
    if content.hashtags:
        hashtags = []
        for item in content.hashtags.replace('\n', ' ').split():
            tag = item.strip()
            if not tag:
                continue
            tag = '#' + tag.lstrip('#')
            hashtags.append(tag)
        if hashtags:
            partes.append(' '.join(dict.fromkeys(hashtags)))
    return '\n\n'.join(partes)


def criar_container_imagem(image_url, caption):
    payload = {'image_url': image_url, 'caption': caption}
    resumo = resumir_image_url(image_url)
    logger.info(
        'Instagram creating image container endpoint=%s content_type=image image_url_scheme=%s image_url_host=%s image_url_path_structure=%s image_url_length=%s image_url_sha256=%s',
        f'{_ig_user_id()}/media',
        resumo['scheme'],
        resumo['host'],
        resumo['path_structure'],
        resumo['length'],
        resumo['sha256'],
    )
    start = time.monotonic()
    logger.info('media_container_request_start image_url_sha256=%s', resumo['sha256'])
    try:
        data = _request('POST', f'{_ig_user_id()}/media', payload)
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info('media_container_request_end duration_ms=%s image_url_sha256=%s', duration_ms, resumo['sha256'])
    container_id = data.get('id')
    if not container_id:
        raise InstagramAPIError('A API do Instagram nao retornou o container de midia.')
    logger.info('Instagram media container created container_id=%s', container_id)
    return container_id


def consultar_container(container_id):
    return _request('GET', container_id, {'fields': 'id,status_code'})


def aguardar_container_pronto(container_id, attempts=5, interval=3):
    for attempt in range(attempts):
        data = consultar_container(container_id)
        status_code = data.get('status_code')
        if status_code in {'FINISHED', 'PUBLISHED'}:
            return data
        if status_code in {'ERROR', 'EXPIRED'}:
            raise InstagramAPIError(f'Container de midia retornou status {status_code}.')
        if attempt < attempts - 1:
            time.sleep(interval)
    raise InstagramAPIError('Container de midia nao ficou pronto dentro do tempo esperado.')


def publicar_container(container_id):
    data = _request('POST', f'{_ig_user_id()}/media_publish', {'creation_id': container_id})
    media_id = data.get('id')
    if not media_id:
        raise InstagramAPIError('A API do Instagram nao retornou o ID da publicacao.')
    logger.info('Instagram media published media_id=%s container_id=%s', media_id, container_id)
    return media_id


def obter_midia_publicada(media_id):
    try:
        return _request('GET', media_id, {'fields': 'id,permalink'})
    except InstagramAPIError:
        return {'id': media_id}


def validar_username_profile(content):
    expected = (settings.INSTAGRAM_EXPECTED_USERNAME or '').strip().lstrip('@').lower()
    profile_username = (content.profile.username or '').strip().lstrip('@').lower()
    if expected and profile_username and profile_username != expected:
        raise InstagramPublishError('Este conteudo pertence a outro perfil social e nao pode ser publicado nesta conta Instagram.')


def _marcar_publicando(content_id):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().select_related('profile').get(pk=content_id)
        if content.status not in {SocialContent.Status.APROVADO, SocialContent.Status.AGENDADO, SocialContent.Status.ERRO}:
            raise InstagramPublishError('Somente conteudos aprovados, agendados ou em erro podem ser publicados.')
        if not content.final_image:
            raise InstagramPublishError('Renderize o card final antes de publicar.')
        if content.external_post_id:
            raise InstagramPublishError('Este conteudo ja possui publicacao vinculada.')
        validar_username_profile(content)
        content.status = SocialContent.Status.PUBLICANDO
        content.tentativas += 1
        content.ultima_tentativa = timezone.now()
        content.erro = ''
        content.save(update_fields=['status', 'tentativas', 'ultima_tentativa', 'erro', 'updated_at'])
        return content


def _marcar_publicado(content_id, media_id, permalink, usuario=None):
    with transaction.atomic():
        content = SocialContent.objects.select_for_update().get(pk=content_id)
        content.status = SocialContent.Status.PUBLICADO
        content.published_at = timezone.now()
        content.external_post_id = media_id
        content.external_permalink = permalink or ''
        content.erro = ''
        content.save(update_fields=['status', 'published_at', 'external_post_id', 'external_permalink', 'erro', 'updated_at'])
        registrar_evento(content, PUBLICADO_INSTAGRAM, usuario, f'Media ID: {media_id}')
        return content


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
    content = _marcar_publicando(content.id)
    try:
        verificar_configuracao_instagram()
        obter_conta_instagram()
        auditar_imagem_final(content)
        image_url = url_midia_temporaria(content)
        caption = montar_caption(content)
        container_id = criar_container_imagem(image_url, caption)
        aguardar_container_pronto(container_id)
        media_id = publicar_container(container_id)
        media = obter_midia_publicada(media_id)
        return _marcar_publicado(content.id, media_id, media.get('permalink'), usuario)
    except Exception as exc:
        _marcar_erro(content.id, str(exc))
        if isinstance(exc, (InstagramConfigurationError, InstagramAPIError, InstagramPublishError)):
            raise
        raise InstagramPublishError('Falha inesperada ao publicar no Instagram.') from exc
