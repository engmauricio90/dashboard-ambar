from dataclasses import dataclass, field
from difflib import SequenceMatcher

from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from .ai import OpenAINotConfigured, formatar_hashtags, gerar_conteudos_ia, moderar_conteudo, normalizar_frase
from .image_selection import selecionar_imagem_base
from .models import SocialBaseImage, SocialCarouselSlide, SocialCarouselTemplate, SocialContent
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
    if media_type == SocialContent.MediaType.CAROUSEL:
        area = 'carrossel com multiplos slides'
        size_hint = 'frase de capa curta e legenda objetiva; dividir a ideia em 3 a 8 pontos simples'
        return [
            {
                'nome': template.name,
                'tags': 'carrossel',
                'posicao_texto': area,
                'area_disponivel_percentual': 70,
                'tamanho_recomendado_frase': size_hint,
                'tipo_midia': media_type,
            }
            for template in profile.carousel_templates.filter(active=True).order_by('-is_default', 'name')[:6]
        ] or [
            {
                'nome': 'Template padrao de carrossel',
                'tags': 'carrossel',
                'posicao_texto': area,
                'area_disponivel_percentual': 70,
                'tamanho_recomendado_frase': size_hint,
                'tipo_midia': media_type,
            }
        ]
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


def _carousel_template(profile):
    template = profile.carousel_templates.filter(active=True, is_default=True).first()
    if template:
        return template
    template = profile.carousel_templates.filter(active=True).order_by('name').first()
    if template:
        return template
    return SocialCarouselTemplate.objects.create(profile=profile, name='Template padrao', is_default=True)


def _split_carousel_body(text, count):
    source = (text or '').replace('\r', '\n')
    parts = [part.strip(' -\t') for line in source.splitlines() for part in line.split('.') if part.strip(' -\t')]
    if not parts:
        parts = ['Uma ideia simples para guardar.', 'O detalhe muda a forma de olhar.', 'Compartilhe com quem vai entender.']
    while len(parts) < count:
        parts.append(parts[-1])
    return parts[:count]


def _criar_slides_carrossel(content, item):
    total = max(2, min(10, content.profile.carousel_default_slide_count or 6))
    body_count = total - (2 if content.profile.carousel_cta_enabled else 1)
    SocialCarouselSlide.objects.create(
        content=content,
        order=1,
        slide_type=SocialCarouselSlide.SlideType.COVER,
        title=item.frase,
        body='',
    )
    for index, part in enumerate(_split_carousel_body(item.legenda, body_count), start=2):
        SocialCarouselSlide.objects.create(
            content=content,
            order=index,
            slide_type=SocialCarouselSlide.SlideType.CONTENT,
            title=f'{index - 1}.',
            body=part,
        )
    if content.profile.carousel_cta_enabled:
        SocialCarouselSlide.objects.create(
            content=content,
            order=total,
            slide_type=SocialCarouselSlide.SlideType.CTA,
            title=content.profile.carousel_default_cta or 'Salva para lembrar depois.',
            body='',
        )


def gerar_lote_conteudos(profile, quantidade, tema, usuario, media_types=None):
    media_types = list(media_types or [])
    if not media_types:
        media_types = [SocialContent.MediaType.IMAGE] * quantidade
    needs_base_image = any(media_type != SocialContent.MediaType.CAROUSEL for media_type in media_types)
    if needs_base_image and not SocialBaseImage.objects.filter(profile=profile, ativa=True).exists():
        raise ValidationError('Cadastre ao menos uma imagem-base ativa antes de gerar conteudos.')

    quantidade = max(1, int(quantidade))
    historico = _historico(profile)
    historico_normalizado = {normalizar_frase(item) for item in historico}
    result = GenerationResult(solicitados=quantidade)
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
            media_type = media_types[index] if index < len(media_types) else SocialContent.MediaType.IMAGE
            if media_type == SocialContent.MediaType.CAROUSEL:
                from .autonomous_carousel import gerar_carrossel_autonomo

                try:
                    carousel_result = gerar_carrossel_autonomo(
                        profile=profile,
                        tema=tema,
                        slides=profile.carousel_default_slide_count,
                        usuario=usuario,
                    )
                    result.criados += 1
                    result.conteudos.append(carousel_result.content)
                    result.mensagens.extend(carousel_result.messages)
                    continue
                except OpenAINotConfigured:
                    carousel_template = _carousel_template(profile)
                    content = SocialContent.objects.create(
                        profile=profile,
                        base_image=None,
                        carousel_template=carousel_template,
                        media_type=media_type,
                        frase=item.frase,
                        legenda=item.legenda,
                        hashtags=formatar_hashtags(item.hashtags),
                        status=SocialContent.Status.RASCUNHO,
                    )
                    _criar_slides_carrossel(content, item)
                    try:
                        renderizar_midia_social(content)
                    except SocialRenderError as exc:
                        content.delete()
                        result.falhas += 1
                        result.mensagens.append(str(exc))
                        continue
                    registrar_evento(content, 'gerado_ia', usuario, f'Modelo: {profile.nome}')
                    result.criados += 1
                    result.conteudos.append(content)
                    continue
            imagem = None
            carousel_template = None
            imagem = selecionar_imagem_base(profile, item.tags_imagem)
            if not imagem:
                result.falhas += 1
                result.mensagens.append('Nao havia imagem-base disponivel para um dos conteudos.')
                continue
            content = SocialContent.objects.create(
                profile=profile,
                base_image=imagem,
                carousel_template=carousel_template,
                media_type=media_type,
                frase=item.frase,
                legenda=item.legenda,
                hashtags=formatar_hashtags(item.hashtags),
                status=SocialContent.Status.RASCUNHO,
            )
            if media_type == SocialContent.MediaType.CAROUSEL:
                _criar_slides_carrossel(content, item)
            try:
                renderizar_midia_social(content)
            except SocialRenderError as exc:
                content.delete()
                result.falhas += 1
                result.mensagens.append(str(exc))
                continue
            if imagem:
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
