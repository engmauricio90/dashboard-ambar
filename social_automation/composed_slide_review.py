import base64
import json
from dataclasses import asdict, dataclass, field

from django.conf import settings

from .ai import OpenAIUnavailable
from .image_analysis import _client as vision_client
from .image_generation import _sanitize_metadata, _sanitize_value
from .models import SocialAIUsage


@dataclass(frozen=True)
class ComposedSlideReviewResult:
    valid: bool
    text_fidelity: int
    legibility: int
    composition: int
    brand_consistency: int
    visual_quality: int
    issues: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def overall_score(self):
        return min(self.text_fidelity, self.legibility, self.composition, self.brand_consistency, self.visual_quality)

    def as_dict(self):
        data = asdict(self)
        data['overall_score'] = self.overall_score
        return data


def review_composed_slide(slide, *, image_field=None, creative_direction=None):
    if not settings.OPENAI_API_KEY or not settings.OPENAI_SOCIAL_VISION_MODEL:
        result = ComposedSlideReviewResult(
            valid=False,
            text_fidelity=0,
            legibility=0,
            composition=0,
            brand_consistency=0,
            visual_quality=0,
            issues=['Review visual IA nao configurado.'],
            blocking_issues=['Review visual IA nao configurado.'],
        )
        _register_review_usage(slide, result, success=False)
        return result

    expected = _expected_copy(slide)
    if not expected:
        result = ComposedSlideReviewResult(False, 0, 0, 0, 0, 0, ['Copy canonica vazia.'], ['Copy canonica vazia.'])
        _register_review_usage(slide, result, success=False)
        return result
    try:
        response = vision_client().responses.create(
            model=settings.OPENAI_SOCIAL_VISION_MODEL,
            store=False,
            input=[
                {
                    'role': 'user',
                    'content': [
                        {'type': 'input_text', 'text': _review_prompt(slide, creative_direction)},
                        {'type': 'input_image', 'image_url': _read_slide_image_data_url(slide, image_field)},
                    ],
                }
            ],
            text={'format': {'type': 'json_schema', 'name': 'composed_slide_review', 'schema': _review_schema(), 'strict': True}},
        )
        result = review_result_from_payload(json.loads(response.output_text))
    except Exception as exc:
        result = ComposedSlideReviewResult(
            valid=False,
            text_fidelity=0,
            legibility=0,
            composition=0,
            brand_consistency=0,
            visual_quality=0,
            issues=['Review visual IA falhou de forma controlada.'],
            blocking_issues=['Review visual IA falhou de forma controlada.'],
        )
        _register_review_usage(slide, result, success=False, error=exc)
        return result
    _register_review_usage(slide, result, success=result.valid)
    return result


def review_result_from_payload(payload):
    blocking = [str(issue).strip() for issue in payload.get('blocking_issues', []) if str(issue).strip()]
    warnings = [str(issue).strip() for issue in payload.get('warnings', []) if str(issue).strip()]
    info = [str(issue).strip() for issue in payload.get('info', []) if str(issue).strip()]
    legacy_issues = [str(issue).strip() for issue in payload.get('issues', []) if str(issue).strip()]
    if not blocking and legacy_issues and not any(key in payload for key in ['blocking_issues', 'warnings', 'info']):
        blocking = legacy_issues
    text_fidelity = _score(payload.get('text_fidelity'))
    legibility = _score(payload.get('legibility'))
    composition = _score(payload.get('composition'))
    brand_consistency = _score(payload.get('brand_consistency'))
    visual_quality = _score(payload.get('visual_quality'))
    threshold_blocking = []
    if text_fidelity < 90:
        threshold_blocking.append('Fidelidade textual abaixo do minimo.')
    if legibility < 75:
        threshold_blocking.append('Legibilidade principal abaixo do minimo.')
    if composition < 70:
        threshold_blocking.append('Composicao severamente inadequada.')
    if brand_consistency < 80:
        threshold_blocking.append('Consistencia de marca abaixo do minimo.')
    blocking = list(dict.fromkeys([*blocking, *threshold_blocking]))
    valid = bool(payload.get('valid')) and not blocking
    result = ComposedSlideReviewResult(
        valid=valid,
        text_fidelity=text_fidelity,
        legibility=legibility,
        composition=composition,
        brand_consistency=brand_consistency,
        visual_quality=visual_quality,
        issues=blocking,
        blocking_issues=blocking,
        warnings=warnings,
        info=info,
    )
    return result


def rereview_ai_finished_slide(slide, *, creative_direction=None):
    if not slide.ai_composed_image:
        result = ComposedSlideReviewResult(False, 0, 0, 0, 0, 0, ['Arte final IA inexistente.'], ['Arte final IA inexistente.'])
        slide.ai_review_metadata = result.as_dict()
        slide.ai_composition_status = slide.CompositionStatus.ERROR
        slide.save(update_fields=['ai_review_metadata', 'ai_composition_status', 'updated_at'])
        return result
    slide.ai_composition_status = slide.CompositionStatus.REVIEWING
    slide.save(update_fields=['ai_composition_status', 'updated_at'])
    result = review_composed_slide(slide, image_field=slide.ai_composed_image, creative_direction=creative_direction)
    slide.ai_review_metadata = result.as_dict()
    slide.ai_composition_status = slide.CompositionStatus.READY if result.valid else slide.CompositionStatus.ERROR
    slide.save(update_fields=['ai_review_metadata', 'ai_composition_status', 'updated_at'])
    return result


def _expected_copy(slide):
    return '\n'.join(part for part in [slide.title, slide.body] if part).strip()


def _review_prompt(slide, creative_direction=None):
    profile = slide.content.profile
    brand = _expected_brand_elements(slide)
    return '\n'.join(
        [
            'Avalie uma arte final de slide de carrossel Instagram.',
            'Verifique fidelidade textual, legibilidade mobile, composicao, consistencia de marca e qualidade visual.',
            'Nao identifique pessoas. Nao julgue popularidade. Retorne apenas o JSON solicitado.',
            f'Perfil: {profile.nome} ({profile.username}).',
            f'Elementos de marca autorizados: {brand}.',
            'Nao classifique esses elementos autorizados como watermark se corresponderem ao handle/contador esperados.',
            'Classifique como problema bloqueante se houver watermark de terceiro, handle errado, contador claramente errado, texto principal cortado ou copy canonica alterada.',
            'Use warnings para textos decorativos secundarios com baixo contraste ou preferencias esteticas subjetivas que nao comprometam a copy principal.',
            f'Texto canonico esperado: {_expected_copy(slide)}',
            f'Titulo esperado: {slide.title or ""}',
            f'Corpo esperado: {slide.body or ""}',
            f'Papel do slide: {slide.slide_role}. Tipo de composicao: {slide.composition_type}.',
            f'Direcao criativa: {creative_direction.as_dict() if hasattr(creative_direction, "as_dict") else creative_direction or {}}',
            'Separe problemas em blocking_issues, warnings e info. valid deve ser false apenas quando houver problema bloqueante.',
        ]
    )


def _expected_brand_elements(slide):
    profile = slide.content.profile
    username = (profile.username or '').strip()
    handle = username if username.startswith('@') else f'@{username}' if username else ''
    total = slide.content.carousel_slides.filter(is_active=True).count() or slide.order
    return {
        'handle': handle,
        'slide_counter': f'{slide.order}/{total}',
        'allowed': [item for item in [handle, f'{slide.order}/{total}'] if item],
    }


def _read_slide_image_data_url(slide, image_field=None):
    field = image_field or slide.ai_composed_image or slide.rendered_image
    if not field:
        raise OpenAIUnavailable('Slide sem imagem para review visual.')
    with field.storage.open(field.name, 'rb') as arquivo:
        encoded = base64.b64encode(arquivo.read()).decode('ascii')
    return f'data:image/jpeg;base64,{encoded}'


def _review_schema():
    score = {'type': 'integer', 'minimum': 0, 'maximum': 100}
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['valid', 'text_fidelity', 'legibility', 'composition', 'brand_consistency', 'visual_quality', 'issues', 'blocking_issues', 'warnings', 'info'],
        'properties': {
            'valid': {'type': 'boolean'},
            'text_fidelity': score,
            'legibility': score,
            'composition': score,
            'brand_consistency': score,
            'visual_quality': score,
            'issues': {'type': 'array', 'items': {'type': 'string', 'maxLength': 180}, 'maxItems': 8},
            'blocking_issues': {'type': 'array', 'items': {'type': 'string', 'maxLength': 180}, 'maxItems': 8},
            'warnings': {'type': 'array', 'items': {'type': 'string', 'maxLength': 180}, 'maxItems': 8},
            'info': {'type': 'array', 'items': {'type': 'string', 'maxLength': 180}, 'maxItems': 8},
        },
    }


def _score(value):
    try:
        return max(0, min(100, int(value)))
    except Exception:
        return 0


def _register_review_usage(slide, result, *, success, error=''):
    return SocialAIUsage.objects.create(
        profile=slide.content.profile,
        content=slide.content,
        slide=slide,
        operation=SocialAIUsage.Operation.COMPOSED_SLIDE_REVIEW,
        model=settings.OPENAI_SOCIAL_VISION_MODEL,
        success=success,
        error='' if success else _sanitize_value(error or '; '.join(result.issues))[:500],
        metadata=_sanitize_metadata(result.as_dict()),
    )
