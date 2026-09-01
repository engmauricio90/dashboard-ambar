import json

from django.conf import settings

from .ai import OpenAIUnavailable, _client
from .carousel_creative_blueprint import CarouselIdea, IdeaSelection
from .image_generation import _sanitize_metadata, _sanitize_value
from .models import SocialAIUsage


DEFAULT_IDEA_COUNT = 4


def generate_carousel_ideas(profile, tema='', historico=None, inspiration_context=None, *, count=DEFAULT_IDEA_COUNT):
    count = max(3, min(5, int(count or DEFAULT_IDEA_COUNT)))
    prompt = (
        'Voce e estrategista editorial de redes sociais. Gere ideias distintas para um carrossel. '
        'Nao copie referencias; extraia apenas linguagem visual, mecanismo e hierarquia. '
        f'Perfil: {profile.nome} ({profile.username}). '
        f'Estilo: {profile.estilo or "sem estilo cadastrado"}. '
        f'Instrucoes gerais: {profile.instrucoes_ia or "sem instrucoes adicionais"}. '
        f'Instrucoes de carrossel: {profile.carousel_ai_instructions or "sem instrucoes adicionais"}. '
        f'Modo editorial: {profile.carousel_editorial_mode}. Modo de geracao: {profile.carousel_generation_mode}. '
        f'Variacao criativa: {profile.carousel_creative_variation}. Tema: {tema or "livre"}. '
        f'Historico recente: {historico or []}. Referencias/inspiracoes: {inspiration_context or []}. '
        f'Quantidade: {count}.'
    )
    try:
        response = _client().responses.create(
            model=settings.OPENAI_SOCIAL_MODEL,
            store=False,
            input=[{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}]}],
            text={'format': {'type': 'json_schema', 'name': 'carousel_ideas', 'schema': _ideas_schema(), 'strict': True}},
        )
        payload = json.loads(response.output_text)
    except Exception as exc:
        _usage(profile, success=False, error=exc, metadata={'stage': 'ideation'})
        raise OpenAIUnavailable('Nao foi possivel gerar ideias de carrossel agora.') from exc

    ideas = [_idea_from_payload(item, index) for index, item in enumerate(payload.get('ideas', []), start=1)]
    _usage(profile, success=True, metadata={'stage': 'ideation', 'ideas': len(ideas)})
    return ideas[:count]


def select_carousel_idea(profile, ideas, *, mode='AUTO', selected_idea_id=''):
    ideas = list(ideas)
    if not ideas:
        raise ValueError('Nenhuma ideia disponivel para selecao.')
    if mode == 'MANUAL' and selected_idea_id:
        selected = next((idea for idea in ideas if idea.idea_id == selected_idea_id), None)
        if not selected:
            raise ValueError('Ideia selecionada nao existe.')
        return selected, IdeaSelection(selected.idea_id, 'Selecao manual do usuario.', 100)

    selected = max(ideas, key=lambda idea: (_score_idea(idea), -len(idea.hook)))
    confidence = max(55, min(95, _score_idea(selected)))
    selection = IdeaSelection(
        selected_idea_id=selected.idea_id,
        reason='Maior combinacao de clareza, promessa e direcao criativa sem promessa matematica de viralidade.',
        confidence=confidence,
    )
    _usage(profile, success=True, metadata={'stage': 'idea_selection', **selection.as_dict()})
    return selected, selection


def _score_idea(idea):
    score = 55
    for attr in ['hook', 'concept', 'promise', 'creative_direction']:
        if getattr(idea, attr, ''):
            score += 8
    if 3 <= idea.suggested_slide_count <= 8:
        score += 6
    if len(idea.hook.split()) <= 12:
        score += 5
    return score


def _idea_from_payload(item, index):
    return CarouselIdea(
        idea_id=str(item.get('idea_id') or f'idea_{index}'),
        hook=(item.get('hook') or '').strip(),
        concept=(item.get('concept') or '').strip(),
        promise=(item.get('promise') or '').strip(),
        audience_angle=(item.get('audience_angle') or '').strip(),
        editorial_angle=(item.get('editorial_angle') or '').strip(),
        suggested_slide_count=max(2, min(10, int(item.get('suggested_slide_count') or 6))),
        creative_direction=(item.get('creative_direction') or '').strip(),
        reason=(item.get('reason') or '').strip(),
    )


def _ideas_schema():
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['ideas'],
        'properties': {
            'ideas': {
                'type': 'array',
                'minItems': 3,
                'maxItems': 5,
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['idea_id', 'hook', 'concept', 'promise', 'audience_angle', 'editorial_angle', 'suggested_slide_count', 'creative_direction', 'reason'],
                    'properties': {
                        'idea_id': {'type': 'string', 'maxLength': 40},
                        'hook': {'type': 'string', 'maxLength': 140},
                        'concept': {'type': 'string', 'maxLength': 260},
                        'promise': {'type': 'string', 'maxLength': 220},
                        'audience_angle': {'type': 'string', 'maxLength': 220},
                        'editorial_angle': {'type': 'string', 'maxLength': 220},
                        'suggested_slide_count': {'type': 'integer', 'minimum': 2, 'maximum': 10},
                        'creative_direction': {'type': 'string', 'maxLength': 360},
                        'reason': {'type': 'string', 'maxLength': 220},
                    },
                },
            }
        },
    }


def _usage(profile, *, success, error='', metadata=None):
    return SocialAIUsage.objects.create(
        profile=profile,
        operation=SocialAIUsage.Operation.IDEATION,
        model=settings.OPENAI_SOCIAL_MODEL,
        success=success,
        error=_sanitize_value(error or '')[:500],
        metadata=_sanitize_metadata(metadata or {}),
    )
