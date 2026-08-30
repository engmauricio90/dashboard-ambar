import json
import re
from dataclasses import dataclass

from django.conf import settings


class SocialAIError(Exception):
    pass


class OpenAINotConfigured(SocialAIError):
    pass


class OpenAIUnavailable(SocialAIError):
    pass


@dataclass(frozen=True)
class GeneratedContent:
    frase: str
    legenda: str
    hashtags: list[str]
    tags_imagem: list[str]


@dataclass(frozen=True)
class GeneratedCarouselSlide:
    order: int
    slide_type: str
    title: str
    body: str
    visual_intent: str
    media_intent: str
    media_required: bool
    preferred_layout: str


@dataclass(frozen=True)
class GeneratedCarouselBlueprint:
    topic: str
    hook: str
    caption: str
    hashtags: list[str]
    slides: list[GeneratedCarouselSlide]


def normalizar_frase(texto):
    return re.sub(r'\s+', ' ', (texto or '').strip()).lower()


def formatar_hashtags(tags):
    resultado = []
    for tag in tags or []:
        normalizada = ''.join(ch for ch in str(tag).strip().replace(' ', '') if ch.isalnum() or ch == '_')
        if not normalizada:
            continue
        if not normalizada.startswith('#'):
            normalizada = f'#{normalizada}'
        resultado.append(normalizada)
    return ' '.join(dict.fromkeys(resultado))


def _client():
    if not settings.OPENAI_API_KEY:
        raise OpenAINotConfigured('Configure OPENAI_API_KEY para gerar conteudos com IA.')
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIUnavailable('Instale a dependencia openai para usar a geracao com IA.') from exc
    return OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_SOCIAL_TIMEOUT_SECONDS)


def _schema():
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['conteudos'],
        'properties': {
            'conteudos': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['frase', 'legenda', 'hashtags', 'tags_imagem'],
                    'properties': {
                        'frase': {'type': 'string', 'minLength': 10, 'maxLength': 220},
                        'legenda': {'type': 'string', 'maxLength': 1200},
                        'hashtags': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 12},
                        'tags_imagem': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 8},
                    },
                },
            },
        },
    }


def _carousel_schema():
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['topic', 'hook', 'caption', 'hashtags', 'slides'],
        'properties': {
            'topic': {'type': 'string', 'maxLength': 160},
            'hook': {'type': 'string', 'minLength': 8, 'maxLength': 180},
            'caption': {'type': 'string', 'maxLength': 1400},
            'hashtags': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 12},
            'slides': {
                'type': 'array',
                'minItems': 2,
                'maxItems': 10,
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': [
                        'order',
                        'slide_type',
                        'title',
                        'body',
                        'visual_intent',
                        'media_intent',
                        'media_required',
                        'preferred_layout',
                    ],
                    'properties': {
                        'order': {'type': 'integer', 'minimum': 1, 'maximum': 10},
                        'slide_type': {'type': 'string', 'enum': ['COVER', 'CONTENT', 'CTA']},
                        'title': {'type': 'string', 'maxLength': 180},
                        'body': {'type': 'string', 'maxLength': 500},
                        'visual_intent': {
                            'type': 'string',
                            'enum': ['HERO', 'EDUCATIONAL', 'CONTRAST', 'QUOTE', 'MINIMAL', 'DARK', 'LIGHT', 'DRAMATIC', 'CLEAN'],
                        },
                        'media_intent': {'type': 'string', 'maxLength': 255},
                        'media_required': {'type': 'boolean'},
                        'preferred_layout': {
                            'type': 'string',
                            'enum': ['AUTO', 'HERO_LEFT', 'HERO_RIGHT', 'TEXT_TOP', 'TEXT_BOTTOM', 'CENTER_CARD', 'SPLIT_LEFT', 'SPLIT_RIGHT', 'MINIMAL', 'FULL_TEXT'],
                        },
                    },
                },
            },
        },
    }


def gerar_conteudos_ia(profile, quantidade, tema, historico, image_contexts=None):
    image_contexts = image_contexts or []
    image_guidance = []
    for context in image_contexts:
        image_guidance.append(
            {
                'imagem': context.get('nome'),
                'tags': context.get('tags'),
                'posicao_texto': context.get('posicao_texto'),
                'area_disponivel_percentual': context.get('area_disponivel_percentual'),
                'tamanho_recomendado_frase': context.get('tamanho_recomendado_frase'),
            }
        )
    prompt = (
        'Voce gera rascunhos para Instagram de um perfil interno. '
        'Responda somente no JSON solicitado. '
        'Crie frases curtas para card, legenda complementar e hashtags. '
        'Considere as imagens-base disponiveis e o espaco de texto delas. '
        'Quando a area disponivel for pequena, gere frase curta; quando for media, frase media; quando for grande, a frase pode ser um pouco maior. '
        'Se tipo_midia for REEL, gere uma unica frase ainda mais curta, sem roteiro, sem cenas e sem chamadas para audio. '
        'Priorize frases que caibam sem cobrir rosto/corpo da pessoa da foto. '
        'Evite repetir ideias, palavras e estruturas do historico. '
        f'Perfil: {profile.nome} ({profile.username}). '
        f'Estilo: {profile.estilo or "sem estilo cadastrado"}. '
        f'Instrucoes: {profile.instrucoes_ia or "sem instrucoes adicionais"}. '
        f'Tema opcional: {tema or "livre"}. '
        f'Quantidade: {quantidade}. '
        f'Imagens e areas de texto: {image_guidance}. '
        f'Historico recente: {historico or []}.'
    )
    try:
        response = _client().responses.create(
            model=settings.OPENAI_SOCIAL_MODEL,
            store=False,
            input=[{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}]}],
            text={
                'format': {
                    'type': 'json_schema',
                    'name': 'social_content_batch',
                    'schema': _schema(),
                    'strict': True,
                }
            },
        )
    except SocialAIError:
        raise
    except Exception as exc:
        raise OpenAIUnavailable('Nao foi possivel gerar conteudos com IA agora.') from exc

    try:
        payload = json.loads(response.output_text)
    except Exception as exc:
        raise OpenAIUnavailable('A IA retornou uma resposta fora do formato esperado.') from exc

    conteudos = []
    for item in payload.get('conteudos', []):
        conteudos.append(
            GeneratedContent(
                frase=(item.get('frase') or '').strip(),
                legenda=(item.get('legenda') or '').strip(),
                hashtags=[str(tag).strip() for tag in item.get('hashtags', []) if str(tag).strip()],
                tags_imagem=[str(tag).strip() for tag in item.get('tags_imagem', []) if str(tag).strip()],
            )
        )
    return conteudos


def gerar_carrossel_blueprint_ia(profile, tema, slide_count, historico=None, media_contexts=None):
    slide_count = max(2, min(10, int(slide_count or profile.carousel_default_slide_count or 6)))
    media_contexts = media_contexts or []
    prompt = (
        'Voce cria um blueprint estruturado para um carrossel de Instagram. '
        'Responda somente no JSON solicitado. '
        'Nao escolha IDs de imagens do banco; descreva a intencao visual e a necessidade de midia. '
        'Use visual_intent apenas como intencao semantica, nao coordenadas. '
        'Use preferred_layout como sugestao visual, sabendo que o compositor final decide a area segura. '
        'Se o slide funcionar bem sem imagem, marque media_required=false e use layout textual/minimal. '
        'Evite textos longos nos slides; cada slide precisa ser legivel em celular. '
        f'Perfil: {profile.nome} ({profile.username}). '
        f'Estilo: {profile.estilo or "sem estilo cadastrado"}. '
        f'Instrucoes gerais: {profile.instrucoes_ia or "sem instrucoes adicionais"}. '
        f'Instrucoes de carrossel: {profile.carousel_ai_instructions or "sem instrucoes adicionais"}. '
        f'Tema opcional: {tema or "livre"}. '
        f'Quantidade de slides: {slide_count}. '
        f'Contexto de midias disponiveis: {media_contexts}. '
        f'Historico recente para evitar repeticao: {historico or []}.'
    )
    try:
        response = _client().responses.create(
            model=settings.OPENAI_SOCIAL_MODEL,
            store=False,
            input=[{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}]}],
            text={
                'format': {
                    'type': 'json_schema',
                    'name': 'social_carousel_blueprint',
                    'schema': _carousel_schema(),
                    'strict': True,
                }
            },
        )
    except SocialAIError:
        raise
    except Exception as exc:
        raise OpenAIUnavailable('Nao foi possivel gerar o carrossel com IA agora.') from exc

    try:
        payload = json.loads(response.output_text)
    except Exception as exc:
        raise OpenAIUnavailable('A IA retornou um carrossel fora do formato esperado.') from exc

    slides = []
    for item in payload.get('slides', [])[:slide_count]:
        slides.append(
            GeneratedCarouselSlide(
                order=int(item.get('order') or len(slides) + 1),
                slide_type=(item.get('slide_type') or 'CONTENT').strip(),
                title=(item.get('title') or '').strip(),
                body=(item.get('body') or '').strip(),
                visual_intent=(item.get('visual_intent') or 'CLEAN').strip(),
                media_intent=(item.get('media_intent') or '').strip(),
                media_required=bool(item.get('media_required')),
                preferred_layout=(item.get('preferred_layout') or 'AUTO').strip(),
            )
        )
    slides.sort(key=lambda slide: slide.order)
    return GeneratedCarouselBlueprint(
        topic=(payload.get('topic') or tema or '').strip(),
        hook=(payload.get('hook') or (slides[0].title if slides else tema) or '').strip(),
        caption=(payload.get('caption') or '').strip(),
        hashtags=[str(tag).strip() for tag in payload.get('hashtags', []) if str(tag).strip()],
        slides=slides,
    )


def moderar_conteudo(texto):
    try:
        response = _client().moderations.create(model=settings.OPENAI_SOCIAL_MODERATION_MODEL, input=texto)
    except SocialAIError:
        raise
    except Exception as exc:
        raise OpenAIUnavailable('Nao foi possivel moderar o conteudo gerado.') from exc
    return bool(response.results[0].flagged)
