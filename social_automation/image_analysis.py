import base64
import json
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from .ai import OpenAINotConfigured, OpenAIUnavailable
from .models import SocialAIUsage, SocialBaseImage, SocialBaseImageProtectedRegion

ANALYSIS_VERSION = '8I.v1'


@dataclass(frozen=True)
class ImageAnalysisResult:
    subject_position: str = SocialBaseImage.SubjectPosition.NONE
    focal_x: float | None = None
    focal_y: float | None = None
    safe_zones: list[str] = field(default_factory=list)
    protected_regions: list[dict] = field(default_factory=list)
    confidence: float = 0
    raw: dict = field(default_factory=dict)
    error: str = ''


def image_analysis_available():
    return bool(settings.OPENAI_API_KEY and settings.OPENAI_SOCIAL_VISION_MODEL)


def _client():
    if not settings.OPENAI_API_KEY:
        raise OpenAINotConfigured('Configure OPENAI_API_KEY para analisar imagens com IA.')
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIUnavailable('Instale a dependencia openai para usar a analise visual.') from exc
    return OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_SOCIAL_TIMEOUT_SECONDS)


def _read_image_data_url(image):
    with image.arquivo.storage.open(image.arquivo.name, 'rb') as arquivo:
        raw = arquivo.read()
    encoded = base64.b64encode(raw).decode('ascii')
    return f'data:image/jpeg;base64,{encoded}'


def _parse_json(output_text):
    try:
        return json.loads(output_text)
    except Exception as exc:
        raise OpenAIUnavailable('A analise visual retornou formato inesperado.') from exc


def _clamp_float(value, default=None):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def _register_usage(profile, *, image, success=True, model='', error='', metadata=None):
    SocialAIUsage.objects.create(
        profile=profile,
        base_image=image,
        operation=SocialAIUsage.Operation.IMAGE_ANALYSIS,
        model=model or settings.OPENAI_SOCIAL_VISION_MODEL,
        success=success,
        error=str(error or '')[:500],
        metadata=metadata or {},
    )


def analyze_social_image(profile, image, *, persist=False):
    if not image_analysis_available():
        return ImageAnalysisResult(error='Analise visual por IA nao configurada.')
    schema = {
        'type': 'object',
        'additionalProperties': False,
        'required': ['subject_position', 'focal_x', 'focal_y', 'safe_zones', 'protected_regions', 'confidence'],
        'properties': {
            'subject_position': {
                'type': 'string',
                'enum': ['none', 'left', 'center', 'right', 'bottom_left', 'bottom_center', 'bottom_right'],
            },
            'focal_x': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'focal_y': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'safe_zones': {
                'type': 'array',
                'items': {'type': 'string', 'enum': ['left', 'right', 'top', 'bottom', 'full']},
                'maxItems': 4,
            },
            'protected_regions': {
                'type': 'array',
                'maxItems': 6,
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['x', 'y', 'width', 'height', 'region_type', 'confidence'],
                    'properties': {
                        'x': {'type': 'number', 'minimum': 0, 'maximum': 1},
                        'y': {'type': 'number', 'minimum': 0, 'maximum': 1},
                        'width': {'type': 'number', 'minimum': 0, 'maximum': 1},
                        'height': {'type': 'number', 'minimum': 0, 'maximum': 1},
                        'region_type': {'type': 'string', 'enum': ['subject', 'face', 'logo', 'product', 'custom']},
                        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    },
                },
            },
            'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
        },
    }
    prompt = (
        'Analise apenas geometria visual para composicao de card social. '
        'Nao identifique pessoas, marcas ou identidades. '
        'Retorne posicao do assunto dominante, foco aproximado, zonas seguras para texto e regioes protegidas normalizadas de 0 a 1.'
    )
    model = settings.OPENAI_SOCIAL_VISION_MODEL
    try:
        response = _client().responses.create(
            model=model,
            store=False,
            input=[
                {
                    'role': 'user',
                    'content': [
                        {'type': 'input_text', 'text': prompt},
                        {'type': 'input_image', 'image_url': _read_image_data_url(image)},
                    ],
                }
            ],
            text={'format': {'type': 'json_schema', 'name': 'social_image_analysis', 'schema': schema, 'strict': True}},
        )
        payload = _parse_json(response.output_text)
    except Exception as exc:
        _register_usage(profile, image=image, success=False, model=model, error=exc)
        raise OpenAIUnavailable('Nao foi possivel analisar a imagem com IA agora.') from exc

    result = ImageAnalysisResult(
        subject_position=payload.get('subject_position') or SocialBaseImage.SubjectPosition.NONE,
        focal_x=_clamp_float(payload.get('focal_x')),
        focal_y=_clamp_float(payload.get('focal_y')),
        safe_zones=[zone for zone in payload.get('safe_zones', []) if zone in {'left', 'right', 'top', 'bottom', 'full'}],
        protected_regions=payload.get('protected_regions', []),
        confidence=_clamp_float(payload.get('confidence'), 0) or 0,
        raw=payload,
    )
    _register_usage(profile, image=image, success=True, model=model, metadata={'confidence': result.confidence})
    if persist:
        persist_image_analysis(image, result, model=model)
    return result


def persist_image_analysis(image, result, *, model=''):
    if result.confidence < settings.SOCIAL_IMAGE_ANALYSIS_MIN_CONFIDENCE:
        return image
    image.subject_position = result.subject_position or SocialBaseImage.SubjectPosition.NONE
    image.focal_x = result.focal_x
    image.focal_y = result.focal_y
    image.text_safe_zone = result.safe_zones[0] if result.safe_zones else SocialBaseImage.TextSafeZone.AUTO
    image.analysis_metadata = result.raw
    image.analysis_model = model or settings.OPENAI_SOCIAL_VISION_MODEL
    image.analysis_version = ANALYSIS_VERSION
    image.analysis_confidence = result.confidence
    image.analyzed_at = timezone.now()
    image.save(
        update_fields=[
            'subject_position',
            'focal_x',
            'focal_y',
            'text_safe_zone',
            'analysis_metadata',
            'analysis_model',
            'analysis_version',
            'analysis_confidence',
            'analyzed_at',
            'updated_at',
        ]
    )
    for region in result.protected_regions:
        confidence = _clamp_float(region.get('confidence'), 0) or 0
        try:
            x = float(region.get('x'))
            y = float(region.get('y'))
            width = float(region.get('width'))
            height = float(region.get('height'))
        except (TypeError, ValueError):
            continue
        if confidence < settings.SOCIAL_IMAGE_ANALYSIS_MIN_CONFIDENCE:
            continue
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            continue
        SocialBaseImageProtectedRegion.objects.create(
            image=image,
            x=x,
            y=y,
            width=width,
            height=height,
            region_type=region.get('region_type') or SocialBaseImageProtectedRegion.RegionType.SUBJECT,
            source=SocialBaseImageProtectedRegion.Source.AI_ANALYSIS,
            confidence=confidence,
            note='Gerada por analise visual IA',
        )
    return image
