from dataclasses import dataclass, field
from difflib import SequenceMatcher

from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from .ai import OpenAINotConfigured, formatar_hashtags, gerar_conteudos_ia, moderar_conteudo, normalizar_frase
from .image_selection import selecionar_imagem_base
from .models import SocialBaseImage, SocialContent
from .rendering import CANVAS_SIZE, REEL_CANVAS_SIZE, SocialRenderError, _reel_text_boxes, _text_boxes, renderizar_midia_social
from .services import registrar_evento


@dataclass
class GenerationResult:
    solicitados: int
    criados: int = 0
    duplicados: int = 0
    bloqueados: int = 0
    falhas: int = 0
    mensagens: list[str] = field(default_factory=list)
    conteudos: list[SocialContent] = field(default_factory=list)


def _similar(a, b):
    return SequenceMatcher(None, a, b).ratio() >= 0.985


def _historico(profile):
    return list(profile.contents.order_by('-created_at').values_list('frase', flat=True)[:50])


def _phrase_size(area_percent):
    if area_percent < 13:
        return 'curta, preferencialmente ate 55 caracteres'
    if area_percent < 22:
        return 'media, preferencialmente ate 90 caracteres'
    return 'um pouco maior, ainda objetiva, preferencialmente ate 130 caracteres'


def _phrase_size_for_media(area_percent, media_type):
    if media_type == SocialContent.MediaType.REEL:
        if area_percent < 10:
            return 'curta, preferencialmente em 1 linha'
        if area_percent < 20:
            return 'media, preferencialmente em 1 a 2 linhas'
        return 'pode usar ate 3 linhas curtas, mantendo leitura rapida'
    return _phrase_size(area_percent)


def _image_contexts(profile, media_type=SocialContent.MediaType.IMAGE):
    contexts = []
    for image in SocialBaseImage.objects.filter(profile=profile, ativa=True).order_by('vezes_usada', 'id')[:12]:
        if media_type == SocialContent.MediaType.REEL:
            boxes = _reel_text_boxes(image)
            canvas_size = boxes[0].get('source_canvas') or REEL_CANVAS_SIZE
        else:
            boxes = _text_boxes(image)
            canvas_size = CANVAS_SIZE
        box = boxes[0]
        region = box['region']
        area_percent = round((region[2] * region[3]) / (canvas_size[0] * canvas_size[1]) * 100, 2)
        contexts.append(
            {
                'nome': image.nome,
                'tags': image.tags,
                'posicao_texto': f"{box['name']} {box['align_vertical']} {box['align_horizontal']}",
                'area_disponivel_percentual': area_percent,
                'tamanho_recomendado_frase': _phrase_size_for_media(area_percent, media_type),
                'tipo_midia': media_type,
            }
        )
    return contexts


def _duplicado(frase_normalizada, historico_normalizado, vistos):
    if frase_normalizada in historico_normalizado or frase_normalizada in vistos:
        return True
    return any(_similar(frase_normalizada, item) for item in historico_normalizado | vistos)


def gerar_lote_conteudos(profile, quantidade, tema, usuario, media_types=None):
    if not SocialBaseImage.objects.filter(profile=profile, ativa=True).exists():
        raise ValidationError('Cadastre ao menos uma imagem-base ativa antes de gerar conteudos.')

    quantidade = max(1, int(quantidade))
    historico = _historico(profile)
    historico_normalizado = {normalizar_frase(item) for item in historico}
    result = GenerationResult(solicitados=quantidade)
    media_types = list(media_types or [])
    if not media_types:
        media_types = [SocialContent.MediaType.IMAGE] * quantidade
    primary_media_type = 'mixed' if len(set(media_types)) > 1 else (media_types[0] if media_types else SocialContent.MediaType.IMAGE)
    gerados = gerar_conteudos_ia(profile, quantidade, tema, historico, image_contexts=_image_contexts(profile, primary_media_type))
    vistos = set()

    for index, item in enumerate(gerados):
        frase_normalizada = normalizar_frase(item.frase)
        if not frase_normalizada or _duplicado(frase_normalizada, historico_normalizado, vistos):
            result.duplicados += 1
            continue
        vistos.add(frase_normalizada)
        try:
            texto_moderacao = f'{item.frase}\n{item.legenda}\n{formatar_hashtags(item.hashtags)}'
            if moderar_conteudo(texto_moderacao):
                result.bloqueados += 1
                continue
            imagem = selecionar_imagem_base(profile, item.tags_imagem)
            if not imagem:
                result.falhas += 1
                result.mensagens.append('Nao havia imagem-base disponivel para um dos conteudos.')
                continue
            media_type = media_types[index] if index < len(media_types) else SocialContent.MediaType.IMAGE
            content = SocialContent.objects.create(
                profile=profile,
                base_image=imagem,
                media_type=media_type,
                frase=item.frase,
                legenda=item.legenda,
                hashtags=formatar_hashtags(item.hashtags),
                status=SocialContent.Status.RASCUNHO,
            )
            try:
                renderizar_midia_social(content)
            except SocialRenderError as exc:
                content.delete()
                result.falhas += 1
                result.mensagens.append(str(exc))
                continue
            SocialBaseImage.objects.filter(pk=imagem.pk).update(
                vezes_usada=F('vezes_usada') + 1,
                ultima_utilizacao=timezone.now(),
            )
            registrar_evento(content, 'gerado_ia', usuario, f'Modelo: {profile.nome}')
            result.criados += 1
            result.conteudos.append(content)
        except OpenAINotConfigured:
            raise
        except Exception as exc:
            result.falhas += 1
            result.mensagens.append(str(exc))

    return result
