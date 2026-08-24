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


def moderar_conteudo(texto):
    try:
        response = _client().moderations.create(model=settings.OPENAI_SOCIAL_MODERATION_MODEL, input=texto)
    except SocialAIError:
        raise
    except Exception as exc:
        raise OpenAIUnavailable('Nao foi possivel moderar o conteudo gerado.') from exc
    return bool(response.results[0].flagged)
