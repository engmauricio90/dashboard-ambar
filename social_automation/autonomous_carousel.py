from dataclasses import asdict, dataclass, field, is_dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from .ai import formatar_hashtags, gerar_carrossel_blueprint_ia, moderar_conteudo
from .ai_slide_composer import compose_slide_with_ai
from .carousel_creative_blueprint import IdeaSelection, is_ai_directed, is_ai_finished
from .carousel_creative_director import build_creative_direction
from .carousel_ideation import generate_carousel_ideas, select_carousel_idea
from .carousel_media_planner import STATUS_GRAPHIC, STATUS_PENDING, plan_carousel_media
from .carousel_quality import PREMIUM_BLUEPRINT_ATTEMPTS, evaluate_blueprint_editorial_quality, evaluate_carousel_quality, is_premium_editorial
from .generation import _carousel_template, _historico
from .image_analysis import OpenAIUnavailable as ImageAnalysisUnavailable, analyze_social_image
from .image_generation import SocialImagePrompt, build_social_image_prompt, generate_social_image, image_generation_available
from .media_resolver import STATUS_FULL_TEXT, STATUS_NEEDS_GENERATION, STATUS_SELECTED, STATUS_UNAVAILABLE
from .models import SocialAIUsage, SocialBaseImage, SocialCarouselGenerationRun, SocialCarouselSlide, SocialCarouselTemplateVariant, SocialContent
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
        operation__in=[SocialAIUsage.Operation.IMAGE_GENERATION, SocialAIUsage.Operation.COMPOSED_SLIDE],
        success=True,
        created_at__date=today,
    ).count()


def _remaining_image_quota(profile):
    profile_limit = profile.ai_image_daily_limit or settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY
    return max(0, min(profile_limit, settings.SOCIAL_AI_IMAGE_MAX_PER_TICK) - _usage_today(profile))


def _image_quota_block_reason(profile):
    used = _usage_today(profile)
    if profile.ai_image_daily_limit and used >= profile.ai_image_daily_limit:
        return 'Limite diario do perfil atingido.'
    if used >= settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY:
        return 'Limite diario global do perfil atingido.'
    if used >= settings.SOCIAL_AI_IMAGE_MAX_PER_TICK:
        return 'Limite global do tick atingido.'
    return 'Quota de composicao IA esgotada.'


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


def _creative_idea(profile, tema):
    if not (is_ai_directed(profile) or is_ai_finished(profile)):
        return None, None
    ideas = generate_carousel_ideas(profile, tema, historico=_historico(profile), inspiration_context=_creative_references(profile))
    return select_carousel_idea(profile, ideas, mode='AUTO')


def _creative_references(profile):
    references = []
    for reference in profile.creative_references.filter(active=True).order_by('-created_at')[:8]:
        references.append(
            {
                'type': reference.reference_type,
                'tags': reference.style_tags,
                'notes': reference.notes,
                'ownership': reference.ownership_type,
                'has_image': bool(reference.image),
            }
        )
    return references


def _run(profile, *, mode, selected_idea=None, selection=None, metadata=None):
    return SocialCarouselGenerationRun.objects.create(
        profile=profile,
        generation_mode=mode,
        status=SocialCarouselGenerationRun.Status.IDEA_SELECTED if selected_idea else SocialCarouselGenerationRun.Status.IDEATING,
        selected_idea=selected_idea.as_dict() if selected_idea else {},
        selection_metadata=selection.as_dict() if selection else {},
        metadata=metadata or {},
    )


def _finish_run(run, *, content=None, status=None, blueprint=None, error=''):
    if not run:
        return
    run.content = content or run.content
    run.status = status or run.status
    if blueprint is not None:
        run.creative_blueprint = blueprint.as_dict() if hasattr(blueprint, 'as_dict') else asdict(blueprint) if is_dataclass(blueprint) else blueprint
    run.error = error[:1000]
    run.finished_at = timezone.now() if run.status in {SocialCarouselGenerationRun.Status.READY, SocialCarouselGenerationRun.Status.PARTIAL, SocialCarouselGenerationRun.Status.ERROR} else run.finished_at
    run.save()


def _create_slide(content, index, item, *, image=None, preferred_layout=None, planned=None, creative_plan=None, render_mode=None):
    return SocialCarouselSlide.objects.create(
        content=content,
        order=index,
        slide_type=item.slide_type,
        slide_role=getattr(item, 'slide_role', '') or SocialCarouselSlide.SlideRole.EXPLANATION,
        source_base_image=image,
        visual_intent=_normalize_layout(preferred_layout or getattr(item, 'preferred_layout', None)),
        visual_treatment=planned.visual_treatment if planned else SocialCarouselSlide.VisualTreatment.AUTO,
        semantic_visual_intent=item.visual_intent,
        media_intent=item.media_intent,
        media_required=planned.media_required if planned else bool(getattr(item, 'media_required', False)),
        title=item.title,
        body=item.body,
        render_mode=render_mode or SocialCarouselSlide.RenderMode.SYSTEM,
        composition_type=(creative_plan.composition_type if creative_plan else SocialCarouselSlide.CompositionType.AUTO),
        creative_plan_metadata=creative_plan.as_dict() if creative_plan else {},
        render_metadata={
            'editorial_mode': getattr(content.profile, 'carousel_editorial_mode', 'STANDARD'),
            'generation_mode': getattr(content.profile, 'carousel_generation_mode', 'SYSTEM_COMPOSED'),
        },
    )


def _compose_ai_finished_content(profile, content, blueprint, creative_direction, *, aspect_ratio, usuario, tema):
    result = AutonomousCarouselResult(content=content)
    call_cap = max(0, int(getattr(settings, 'SOCIAL_AI_COMPOSED_MAX_CALLS_PER_CAROUSEL', 8)))
    remaining = min(call_cap, _remaining_image_quota(profile))
    max_attempts = max(1, int(getattr(settings, 'SOCIAL_AI_COMPOSED_SLIDE_MAX_ATTEMPTS', 2)))
    slides = []
    for index, item in enumerate(blueprint.slides, start=1):
        plan = creative_direction.slides[index - 1] if index - 1 < len(creative_direction.slides) else None
        slide = _create_slide(
            content,
            index,
            item,
            preferred_layout=getattr(item, 'preferred_layout', None),
            creative_plan=plan,
            render_mode=SocialCarouselSlide.RenderMode.AI_FINISHED,
        )
        slides.append((slide, plan))

    for slide, plan in slides:
        if remaining <= 0:
            _mark_ai_finished_pending_by_quota(slide, result, _ai_finished_quota_reason(profile, call_cap, result.generated_images))
            continue
        composed = compose_slide_with_ai(slide, creative_direction, plan.as_dict() if plan else {}, aspect_ratio=aspect_ratio, remaining_calls=1)
        remaining = _record_ai_finished_result(result, composed, remaining)

    retry_candidates = [slide_plan for slide_plan in slides if _can_retry_ai_finished_slide(slide_plan[0], max_attempts)]
    while remaining > 0 and retry_candidates:
        next_candidates = []
        for slide, plan in retry_candidates:
            if remaining <= 0:
                next_candidates.append((slide, plan))
                continue
            composed = compose_slide_with_ai(slide, creative_direction, plan.as_dict() if plan else {}, aspect_ratio=aspect_ratio, remaining_calls=1)
            remaining = _record_ai_finished_result(result, composed, remaining, count_pending=False)
            slide.refresh_from_db()
            if _can_retry_ai_finished_slide(slide, max_attempts):
                next_candidates.append((slide, plan))
        retry_candidates = next_candidates

    for slide, _plan in slides:
        slide.refresh_from_db()
        if slide.ai_composition_status != SocialCarouselSlide.CompositionStatus.READY:
            result.pending_slides += 1
            if not any(message.startswith(f'Slide {slide.order}:') for message in result.messages):
                reason = _ai_finished_quota_reason(profile, call_cap, result.generated_images) if remaining <= 0 else 'Arte final IA ainda nao aprovada.'
                result.messages.append(f'Slide {slide.order}: {reason}')
    if content.status != content.Status.PUBLICADO:
        from .container_versioning import invalidate_instagram_container

        invalidate_instagram_container(content, reason='ai_finished_carousel_composed')
    quality = evaluate_carousel_quality(content)
    if not quality.valid:
        content.erro = 'Carrossel AI_FINISHED ainda nao aprovado: ' + '; '.join(quality.issues)[:900]
        content.save(update_fields=['erro', 'updated_at'])
    registrar_evento(content, 'gerado_ia', usuario, f'Carrossel AI_FINISHED. Tema: {tema or "-"}')
    return result


def _record_ai_finished_result(result, composed, remaining, *, count_pending=True):
    spent_calls = 0 if composed.reused else composed.attempts
    remaining = max(0, remaining - spent_calls)
    result.generated_images += spent_calls
    if count_pending and composed.pending:
        result.messages.extend(composed.issues)
    elif composed.issues:
        result.messages.extend(composed.issues)
    return remaining


def _can_retry_ai_finished_slide(slide, max_attempts):
    return (
        slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.ERROR
        and slide.ai_composition_attempts < max_attempts
    )


def _mark_ai_finished_pending_by_quota(slide, result, reason):
    result.messages.append(f'Slide {slide.order}: {reason}')
    slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.PENDING
    slide.ai_composition_metadata = {'reason': reason}
    slide.save(update_fields=['ai_composition_status', 'ai_composition_metadata', 'updated_at'])


def _ai_finished_quota_reason(profile, call_cap, calls_used):
    if call_cap <= 0 or calls_used >= call_cap:
        return 'Limite de chamadas deste carrossel atingido.'
    return _image_quota_block_reason(profile)


def gerar_carrossel_autonomo(profile, *, tema='', slides=None, usuario=None, selected_idea=None, idea_selection=None):
    slide_count = max(2, min(10, int(slides or profile.carousel_default_slide_count or 6)))
    media_contexts = _media_contexts(profile)
    if selected_idea:
        selection = idea_selection or IdeaSelection(selected_idea.idea_id, 'Selecao manual do usuario.', 100)
    else:
        selected_idea, selection = _creative_idea(profile, tema)
    run = _run(profile, mode=profile.carousel_generation_mode, selected_idea=selected_idea, selection=selection, metadata={'tema': tema, 'slides': slide_count}) if (is_ai_directed(profile) or is_ai_finished(profile)) else None
    if selected_idea:
        tema = f'{tema or selected_idea.hook} | Ideia: {selected_idea.hook} | {selected_idea.concept}'
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
        _finish_run(run, content=content, status=SocialCarouselGenerationRun.Status.ERROR, blueprint=blueprint, error=content.erro)
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
    _finish_run(run, content=content, status=SocialCarouselGenerationRun.Status.EDITORIAL_APPROVED, blueprint=blueprint)
    result = AutonomousCarouselResult(content=content)
    remaining_quota = _remaining_image_quota(profile)
    aspect_ratio = template.aspect_ratio
    creative_direction = build_creative_direction(profile, blueprint, selected_idea=selected_idea, media_contexts=media_contexts, inspiration_context=_creative_references(profile)) if (is_ai_directed(profile) or is_ai_finished(profile)) else None
    if creative_direction:
        run.creative_blueprint = creative_direction.as_dict()
        run.status = SocialCarouselGenerationRun.Status.BLUEPRINT_READY
        run.save(update_fields=['creative_blueprint', 'status'])
    if is_ai_finished(profile):
        result = _compose_ai_finished_content(profile, content, blueprint, creative_direction, aspect_ratio=aspect_ratio, usuario=usuario, tema=tema)
        _finish_run(
            run,
            content=content,
            status=SocialCarouselGenerationRun.Status.READY if content.final_media_ready else SocialCarouselGenerationRun.Status.PARTIAL,
            blueprint=creative_direction,
            error=content.erro,
        )
        return result

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

        creative_plan = creative_direction.slides[index - 1] if creative_direction and index - 1 < len(creative_direction.slides) else None
        created_slide = _create_slide(
            content,
            index,
            item,
            image=image,
            preferred_layout=preferred_layout,
            planned=planned,
            creative_plan=creative_plan,
            render_mode=SocialCarouselSlide.RenderMode.HYBRID if is_ai_directed(profile) else SocialCarouselSlide.RenderMode.SYSTEM,
        )
        created_slide.render_metadata.update(
            {
                'visual_mode': plan.visual_mode,
                'image_density': plan.image_density,
                'media_resolution': planned.status,
                'media_score': planned.score,
                'media_reason': planned.reason,
                'needs_generation': planned.needs_generation,
                'editorial_preflight_score': preflight.score if preflight else None,
                'editorial_preflight_attempts': preflight_attempts,
            }
        )
        created_slide.save(update_fields=['render_metadata', 'updated_at'])

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
    _finish_run(
        run,
        content=content,
        status=SocialCarouselGenerationRun.Status.READY if content.final_media_ready else SocialCarouselGenerationRun.Status.PARTIAL,
        blueprint=creative_direction,
        error=content.erro,
    )
    return result
