import base64
import hashlib
import json
from dataclasses import dataclass, field
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps

from .ai import OpenAINotConfigured, OpenAIUnavailable, moderar_conteudo
from .media_paths import unique_media_filename
from .models import SocialAIUsage, SocialBaseImage, SocialProfile


class SocialImageGenerationDisabled(Exception):
    pass


@dataclass(frozen=True)
class SocialImagePrompt:
    profile_id: int
    prompt: str
    aspect_ratio: str = '1:1'
    purpose: str = 'IMAGE_BANK'
    metadata: dict = field(default_factory=dict)


def image_generation_available(profile=None):
    if profile and not profile.ai_image_generation_enabled:
        return False
    return bool(settings.OPENAI_API_KEY and settings.OPENAI_SOCIAL_IMAGE_MODEL)


def _text_zone_instruction(desired_text_zone):
    zone = (desired_text_zone or 'AUTO').upper()
    if 'LEFT' in zone:
        return 'Reserve area limpa e com baixo contraste visual no lado esquerdo; posicione o assunto principal mais a direita.'
    if 'RIGHT' in zone:
        return 'Reserve area limpa e com baixo contraste visual no lado direito; posicione o assunto principal mais a esquerda.'
    if 'TOP' in zone:
        return 'Reserve area limpa na parte superior para aplicacao posterior de texto.'
    if 'BOTTOM' in zone:
        return 'Reserve area limpa na parte inferior para aplicacao posterior de texto.'
    if zone in {'CENTER_CARD', 'MINIMAL', 'FULL_TEXT'}:
        return 'Crie fundo visual simples com areas amplas de respiro para texto posterior.'
    return 'Preserve areas de respiro sem elementos importantes para texto posterior.'


def build_social_image_prompt(profile, *, purpose, visual_intent, media_intent, desired_text_zone, aspect_ratio, context=None):
    context = context or {}
    parts = [
        'Crie uma imagem fotografica/ilustrativa para uso em post social.',
        'Nao inclua texto, tipografia, logotipo, assinatura, marca d agua ou moldura. O texto sera aplicado depois pelo sistema.',
        f'Perfil: {profile.nome} ({profile.username}).',
        f'Finalidade: {purpose}.',
        f'Formato/aspect ratio: {aspect_ratio}.',
        f'Intencao visual: {visual_intent or "CLEAN"}.',
        f'Intencao de midia: {media_intent or "imagem contextual generica"}.',
        _text_zone_instruction(desired_text_zone),
    ]
    if profile.image_ai_instructions:
        parts.append(f'Instrucoes visuais do perfil: {profile.image_ai_instructions}.')
    if context:
        parts.append(f'Contexto adicional: {context}.')
    return '\n'.join(part for part in parts if part)


def build_image_generation_prompt(profile, base_prompt):
    return '\n\n'.join(item.strip() for item in [profile.image_ai_instructions, base_prompt] if item and item.strip())


def _client():
    if not settings.OPENAI_API_KEY:
        raise OpenAINotConfigured('Configure OPENAI_API_KEY para gerar imagens com IA.')
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIUnavailable('Instale a dependencia openai para usar a geracao de imagem.') from exc
    return OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_SOCIAL_TIMEOUT_SECONDS)


def _image_size(aspect_ratio):
    ratio = (aspect_ratio or '').upper()
    if ratio in {'PORTRAIT', '4:5', '1080X1350'}:
        return '1024x1536'
    if ratio in {'REEL', 'STORY', '9:16', '1080X1920'}:
        return '1024x1536'
    return '1024x1024'


def _request_fingerprint(prompt: SocialImagePrompt, *, model, quality):
    payload = {
        'profile_id': prompt.profile_id,
        'purpose': prompt.purpose,
        'prompt': prompt.prompt,
        'aspect_ratio': prompt.aspect_ratio,
        'model': model,
        'quality': quality,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _find_reusable_image(profile, *, fingerprint, prompt, model):
    if not profile.ai_generated_images_reusable:
        return None
    for image in SocialBaseImage.objects.filter(
        profile=profile,
        source=SocialBaseImage.Source.AI,
        ai_model=model,
        generation_purpose=prompt.purpose,
    ).exclude(arquivo='').order_by('-generated_at', '-id')[:20]:
        if (image.analysis_metadata or {}).get('request_fingerprint') == fingerprint:
            return image
    return None


def _daily_quota_remaining(profile):
    today = timezone.localdate()
    limit = profile.ai_image_daily_limit or settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY
    used = SocialAIUsage.objects.filter(
        profile=profile,
        operation=SocialAIUsage.Operation.IMAGE_GENERATION,
        success=True,
        created_at__date=today,
    ).count()
    return max(0, limit - used)


def _sanitize_value(value):
    if value is None:
        return value
    text = str(value)
    secrets_to_mask = [
        settings.OPENAI_API_KEY,
        getattr(settings, 'INSTAGRAM_ACCESS_TOKEN', ''),
        getattr(settings, 'SOCIAL_INSTAGRAM_CLIENT_SECRET', ''),
        getattr(settings, 'SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY', ''),
    ]
    for secret in secrets_to_mask:
        if secret and secret in text:
            text = text.replace(secret, '[secret]')
    return text


def _sanitize_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}
    safe = {}
    for key, value in metadata.items():
        if isinstance(value, dict):
            safe[key] = _sanitize_metadata(value)
        elif isinstance(value, (list, tuple)):
            safe[key] = [_sanitize_value(item) for item in value]
        else:
            safe[key] = _sanitize_value(value)
    return safe


def _extract_image_bytes(response):
    data = getattr(response, 'data', None)
    if not data:
        raise OpenAIUnavailable('A API de imagem nao retornou dados de imagem.')
    item = data[0]
    raw = getattr(item, 'b64_json', None)
    if raw:
        try:
            return base64.b64decode(raw, validate=True)
        except Exception as exc:
            raise OpenAIUnavailable('A API de imagem retornou base64 invalido.') from exc
    raise OpenAIUnavailable('A API de imagem nao retornou bytes em base64.')


def _validate_image_bytes(image_bytes):
    if not image_bytes:
        raise OpenAIUnavailable('A API de imagem retornou arquivo vazio.')
    if len(image_bytes) > settings.SOCIAL_AI_IMAGE_MAX_BYTES:
        raise OpenAIUnavailable('A imagem gerada ultrapassou o limite de tamanho configurado.')
    with Image.open(BytesIO(image_bytes)) as image:
        ImageOps.exif_transpose(image).verify()
    with Image.open(BytesIO(image_bytes)) as image:
        width, height = image.size
    if width < 512 or height < 512:
        raise OpenAIUnavailable('A imagem gerada possui resolucao insuficiente.')
    return width, height


def _register_usage(profile, *, image=None, success=True, model='', error='', metadata=None):
    return SocialAIUsage.objects.create(
        profile=profile,
        base_image=image,
        operation=SocialAIUsage.Operation.IMAGE_GENERATION,
        model=model or settings.OPENAI_SOCIAL_IMAGE_MODEL,
        success=success,
        error=_sanitize_value(error or '')[:500],
        metadata=_sanitize_metadata(metadata or {}),
    )


def generate_social_image(prompt: SocialImagePrompt):
    if not image_generation_available():
        raise SocialImageGenerationDisabled('Geracao de imagem por IA nao configurada.')
    profile = SocialProfile.objects.get(pk=prompt.profile_id)
    if not image_generation_available(profile):
        raise SocialImageGenerationDisabled('Geracao de imagem por IA desabilitada para o perfil.')
    if profile.ai_image_policy in {SocialProfile.AIImagePolicy.NONE, SocialProfile.AIImagePolicy.BANK_ONLY}:
        raise SocialImageGenerationDisabled('Politica do perfil nao permite gerar imagem por IA.')
    model = settings.OPENAI_SOCIAL_IMAGE_MODEL
    fingerprint = _request_fingerprint(prompt, model=model, quality=settings.OPENAI_SOCIAL_IMAGE_QUALITY)
    reusable = _find_reusable_image(profile, fingerprint=fingerprint, prompt=prompt, model=model)
    if reusable:
        return reusable
    if _daily_quota_remaining(profile) <= 0:
        _register_usage(profile, success=False, model=model, error='Quota diaria de imagem IA esgotada.', metadata={**prompt.metadata, 'request_fingerprint': fingerprint})
        raise SocialImageGenerationDisabled('Quota diaria de imagem IA esgotada.')
    if moderar_conteudo(prompt.prompt):
        _register_usage(profile, success=False, model=model, error='Prompt bloqueado pela moderacao.', metadata={**prompt.metadata, 'request_fingerprint': fingerprint})
        raise SocialImageGenerationDisabled('Prompt visual bloqueado pela moderacao.')
    try:
        response = _client().images.generate(
            model=model,
            prompt=prompt.prompt,
            size=_image_size(prompt.aspect_ratio),
            quality=settings.OPENAI_SOCIAL_IMAGE_QUALITY,
            n=1,
        )
        image_bytes = _extract_image_bytes(response)
        width, height = _validate_image_bytes(image_bytes)
    except (OpenAINotConfigured, SocialImageGenerationDisabled):
        raise
    except Exception as exc:
        _register_usage(profile, success=False, model=model, error=exc, metadata={**prompt.metadata, 'request_fingerprint': fingerprint})
        raise OpenAIUnavailable('Nao foi possivel gerar imagem com IA agora.') from exc

    image = SocialBaseImage(
        profile=profile,
        nome=f'IA {prompt.purpose} {timezone.now():%d/%m/%Y %H:%M}',
        descricao=str(prompt.metadata.get('media_intent') or ''),
        tags=', '.join(filter(None, ['ia', prompt.purpose, prompt.metadata.get('visual_intent'), prompt.metadata.get('media_intent')]))[:255],
        source=SocialBaseImage.Source.AI,
        ai_model=model,
        ai_prompt=prompt.prompt,
        ai_generation_id=getattr(response, 'id', '') or '',
        generation_purpose=prompt.purpose,
        generated_at=timezone.now(),
        ativa=bool(profile.ai_generated_images_reusable),
    )
    filename = unique_media_filename('.jpg')
    image.arquivo.save(filename, ContentFile(image_bytes), save=False)
    image.analysis_metadata = {'width': width, 'height': height, 'request_fingerprint': fingerprint, **_sanitize_metadata(prompt.metadata)}
    image.save()
    _register_usage(profile, image=image, success=True, model=model, metadata={**prompt.metadata, 'width': width, 'height': height, 'request_fingerprint': fingerprint})
    return image
