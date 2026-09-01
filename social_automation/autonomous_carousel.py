from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from .ai import formatar_hashtags, gerar_carrossel_blueprint_ia, moderar_conteudo
from .carousel_media_planner import STATUS_GRAPHIC, STATUS_PENDING, plan_carousel_media
from .carousel_quality import PREMIUM_BLUEPRINT_ATTEMPTS, evaluate_blueprint_editorial_quality, evaluate_carousel_quality, is_premium_editorial
from .generation import _carousel_template, _historico
from .image_analysis import OpenAIUnavailable as ImageAnalysisUnavailable, analyze_social_image
from .image_generation import SocialImagePrompt, build_social_image_prompt, generate_social_image, image_generation_available
from .media_resolver import STATUS_FULL_TEXT, STATUS_NEEDS_GENERATION, STATUS_SELECTED, STATUS_UNAVAILABLE
from .models import SocialAIUsage, SocialBaseImage, SocialCarouselSlide, SocialCarouselTemplateVariant, SocialContent
from .rendering import SocialRenderError, renderizar_midia_social
from .services import registrar_evento


@dataclass
class AutonomousCarouselResult:
    content: SocialContent | None = None
    generated_images: int = 0
    selected_bank_images: int = 0
    full_text_slides: int = 0
    graphic_slides: int = 0
    pending_slides: int = 0
    messages: list[str] = field(default_factory=list)


def _usage_today(profile):
    today = timezone.localdate()
    return SocialAIUsage.objects.filter(
        profile=profile,
        operation=SocialAIUsage.Operation.IMAGE_GENERATION,
        success=True,
        created_at__date=today,
    ).count()


def _remaining_image_quota(profile):
    profile_limit = profile.ai_image_daily_limit or settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY
    return max(0, min(profile_limit, settings.SOCIAL_AI_IMAGE_MAX_PER_TICK) - _usage_today(profile))


def _normalize_layout(value):
    valid = {choice[0] for choice in SocialCarouselTemplateVariant.LayoutType.choices}
    value = (value or 'AUTO').upper()
    return value if value in valid else SocialCarouselTemplateVariant.LayoutType.AUTO


def _media_contexts(profile):
    contexts = []
    for image in profile.base_images.filter(ativa=True).order_by('vezes_usada', 'ultima_utilizacao', 'id')[:24]:
        contexts.append(
            {
                'nome': image.nome,
                'tags': image.tags,
                'descricao': image.descricao,
                'origem': image.source,
                'safe_zone': image.text_safe_zone,
                'subject_position': image.subject_position,
                'vezes_usada': image.vezes_usada,
            }
        )
    return contexts


def _purpose_for_slide(slide_type):
    if slide_type == SocialCarouselSlide.SlideType.COVER:
        return 'CAROUSEL_COVER'
    return 'CAROUSEL_SLIDE'


def _generate_blueprint_with_preflight(profile, tema, slide_count, media_contexts):
    attempts = PREMIUM_BLUEPRINT_ATTEMPTS if is_premium_editorial(getattr(profile, 'carousel_editorial_mode', None)) else 1
    last_blueprint = None
    last_quality = None
    for attempt in range(1, attempts + 1):
        blueprint = gerar_carrossel_blueprint_ia(
            profile,
            tema,
            slide_count,
            historico=_historico(profile),
            media_contexts=media_contexts,
        )
        quality = evaluate_blueprint_editorial_quality(profile, blueprint)
        last_blueprint = blueprint
        last_quality = quality
        if quality.valid:
            return blueprint, quality, attempt
    return last_blueprint, last_quality, attempts


def _create_preflight_rejected_content(profile, template, blueprint, preflight, attempts, usuario, tema):
    content = SocialContent.objects.create(
        profile=profile,
        carousel_template=template,
        media_type=SocialContent.MediaType.CAROUSEL,
        frase=blueprint.hook,
        legenda=blueprint.caption,
        hashtags=formatar_hashtags(blueprint.hashtags),
        status=SocialContent.Status.RASCUNHO,
        erro='Preflight editorial reprovado: ' + '; '.join(preflight.issues)[:900],
    )
    for index, item in enumerate(blueprint.slides, start=1):
        SocialCarouselSlide.objects.create(
            content=content,
            order=index,
            slide_type=item.slide_type,
            slide_role=getattr(item, 'slide_role', '') or SocialCarouselSlide.SlideRole.EXPLANATION,
            visual_intent=_normalize_layout(getattr(item, 'preferred_layout', None) or SocialCarouselTemplateVariant.LayoutType.FULL_TEXT),
            visual_treatment=SocialCarouselSlide.VisualTreatment.TEXT_ONLY,
            semantic_visual_intent=item.visual_intent,
            media_intent=item.media_intent,
            media_required=False,
            title=item.title,
            body=item.body,
            render_metadata={
                'editorial_preflight': 'rejected',
                'editorial_attempts': attempts,
                'editorial_score': preflight.score,
                'editorial_issues': preflight.issues,
            },
        )
    registrar_evento(content, 'gerado_ia', usuario, f'Carrossel reprovado no preflight editorial. Tema: {tema or "-"}')
    return content


def gerar_carrossel_autonomo(profile, *, tema='', slides=None, usuario=None):
    slide_count = max(2, min(10, int(slides or profile.carousel_default_slide_count or 6)))
    media_contexts = _media_contexts(profile)
    blueprint, preflight, preflight_attempts = _generate_blueprint_with_preflight(profile, tema, slide_count, media_contexts)
    text_for_moderation = '\n'.join(
        [blueprint.hook, blueprint.caption, formatar_hashtags(blueprint.hashtags)]
        + [f'{slide.title}\n{slide.body}' for slide in blueprint.slides]
    )
    if moderar_conteudo(text_for_moderation):
        raise ValidationError('Carrossel bloqueado pela moderacao.')

    template = _carousel_template(profile)
    if preflight and not preflight.valid:
        content = _create_preflight_rejected_content(profile, template, blueprint, preflight, preflight_attempts, usuario, tema)
        return AutonomousCarouselResult(content=content, pending_slides=len(blueprint.slides), messages=preflight.issues)

    content = SocialContent.objects.create(
        profile=profile,
        carousel_template=template,
        media_type=SocialContent.MediaType.CAROUSEL,
        frase=blueprint.hook,
        legenda=blueprint.caption,
        hashtags=formatar_hashtags(blueprint.hashtags),
        status=SocialContent.Status.RASCUNHO,
    )
    result = AutonomousCarouselResult(content=content)
    remaining_quota = _remaining_image_quota(profile)
    aspect_ratio = template.aspect_ratio
    plan = plan_carousel_media(profile, blueprint.slides[:slide_count], template, remaining_quota=remaining_quota)

    for index, planned in enumerate(plan.items, start=1):
        item = planned.slide
        preferred_layout = _normalize_layout(planned.visual_intent)
        image = planned.image
        if planned.status == STATUS_SELECTED and image:
            result.selected_bank_images += 1
            SocialBaseImage.objects.filter(pk=image.pk).update(vezes_usada=F('vezes_usada') + 1, ultima_utilizacao=timezone.now())
        elif planned.status == STATUS_NEEDS_GENERATION:
            if remaining_quota <= 0 or not image_generation_available(profile):
                result.pending_slides += 1
                result.messages.append(f'Slide {index}: geracao indisponivel ou quota esgotada; midia pendente.')
            else:
                prompt_text = build_social_image_prompt(
                    profile,
                    purpose=_purpose_for_slide(item.slide_type),
                    visual_intent=item.visual_intent,
                    media_intent=item.media_intent,
                    desired_text_zone=preferred_layout,
                    aspect_ratio=aspect_ratio,
                    context={'tema': tema, 'slide': index, 'title': item.title},
                )
                try:
                    image = generate_social_image(
                        SocialImagePrompt(
                            profile_id=profile.id,
                            prompt=prompt_text,
                            aspect_ratio=aspect_ratio,
                            purpose=_purpose_for_slide(item.slide_type),
                            metadata={'visual_intent': item.visual_intent, 'media_intent': item.media_intent, 'preferred_layout': preferred_layout},
                        )
                    )
                except Exception as exc:
                    content.erro = str(exc)[:1000]
                    content.save(update_fields=['erro', 'updated_at'])
                    result.messages.append(f'Slide {index}: falha controlada na geracao de imagem.')
                    return result
                remaining_quota -= 1
                result.generated_images += 1
                try:
                    analyze_social_image(profile, image, persist=True)
                except ImageAnalysisUnavailable as exc:
                    result.messages.append(f'Slide {index}: imagem gerada sem analise visual ({exc}).')
        elif planned.status == STATUS_GRAPHIC:
            result.graphic_slides += 1
        elif planned.status == STATUS_FULL_TEXT:
            preferred_layout = SocialCarouselTemplateVariant.LayoutType.FULL_TEXT
            result.full_text_slides += 1
        elif planned.status in {STATUS_PENDING, STATUS_UNAVAILABLE}:
            result.pending_slides += 1
            result.messages.append(f'Slide {index}: midia visual pendente. {planned.reason}')

        SocialCarouselSlide.objects.create(
            content=content,
            order=index,
            slide_type=item.slide_type,
            slide_role=getattr(item, 'slide_role', '') or SocialCarouselSlide.SlideRole.EXPLANATION,
            source_base_image=image,
            visual_intent=preferred_layout,
            visual_treatment=planned.visual_treatment,
            semantic_visual_intent=item.visual_intent,
            media_intent=item.media_intent,
            media_required=planned.media_required,
            title=item.title,
            body=item.body,
            render_metadata={
                'visual_mode': plan.visual_mode,
                'image_density': plan.image_density,
                'media_resolution': planned.status,
                'media_score': planned.score,
                'media_reason': planned.reason,
                'needs_generation': planned.needs_generation,
                'editorial_mode': getattr(profile, 'carousel_editorial_mode', 'STANDARD'),
                'editorial_preflight_score': preflight.score if preflight else None,
                'editorial_preflight_attempts': preflight_attempts,
            },
        )

    try:
        renderizar_midia_social(content)
    except SocialRenderError:
        content.delete()
        raise
    quality = evaluate_carousel_quality(content)
    if not content.final_media_ready:
        if quality.editorial_issues:
            content.erro = 'Carrossel ainda nao atende a politica editorial do perfil: ' + '; '.join(quality.editorial_issues)[:900]
        else:
            content.erro = 'Carrossel ainda nao atende a politica visual do perfil.'
        content.save(update_fields=['erro', 'updated_at'])
    registrar_evento(content, 'gerado_ia', usuario, f'Carrossel autonomo. Tema: {tema or "-"}')
    return result
