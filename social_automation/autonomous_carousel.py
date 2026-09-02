from dataclasses import asdict, dataclass, field, is_dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .ai import formatar_hashtags, gerar_carrossel_blueprint_ia, moderar_conteudo
from .ai_slide_composer import BRAND_OVERLAY_VERSION, compose_slide_image_with_ai, compose_slide_with_ai, reapply_system_brand_overlay
from .carousel_creative_blueprint import IdeaSelection, is_ai_directed, is_ai_finished
from .carousel_creative_director import build_creative_direction
from .carousel_ideation import generate_carousel_ideas, select_carousel_idea
from .carousel_media_planner import STATUS_GRAPHIC, STATUS_PENDING, plan_carousel_media
from .carousel_quality import PREMIUM_BLUEPRINT_ATTEMPTS, evaluate_blueprint_editorial_quality, evaluate_carousel_quality, is_premium_editorial
from .composed_slide_review import rereview_ai_finished_slide
from .generation import _carousel_template, _historico
from .image_analysis import OpenAIUnavailable as ImageAnalysisUnavailable, analyze_social_image
from .image_generation import SocialImagePrompt, build_social_image_prompt, generate_social_image, image_generation_available
from .media_resolver import STATUS_FULL_TEXT, STATUS_NEEDS_GENERATION, STATUS_SELECTED, STATUS_UNAVAILABLE
from .models import SocialAIUsage, SocialBaseImage, SocialCarouselGenerationRun, SocialCarouselSlide, SocialCarouselTemplateVariant, SocialContent, SocialProfile
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
    processed_slides: int = 0
    approved_slides: int = 0
    failed_slides: int = 0
    composition_calls_used: int = 0
    composition_call_cap: int = 0
    quota_remaining: int = 0
    run: SocialCarouselGenerationRun | None = None
    step: str = ''
    slide_order: int | None = None
    has_more_work: bool = False
    blocking_reason: str = ''


class CarouselExecutionMode:
    AUTOMATIC_TICK = 'AUTOMATIC_TICK'
    MANUAL_RESUME = 'MANUAL_RESUME'


MANUAL_RESUME_STALE_MINUTES = 15


def _usage_today(profile):
    today = timezone.localdate()
    return SocialAIUsage.objects.filter(
        profile=profile,
        operation__in=[SocialAIUsage.Operation.IMAGE_GENERATION, SocialAIUsage.Operation.COMPOSED_SLIDE],
        success=True,
        created_at__date=today,
    ).count()


def _remaining_daily_image_quota(profile):
    used = _usage_today(profile)
    profile_limit = profile.ai_image_daily_limit or settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY
    daily_limit = settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY
    return max(0, min(profile_limit, daily_limit) - used)


def _remaining_image_quota(profile, *, execution_mode=CarouselExecutionMode.AUTOMATIC_TICK):
    if execution_mode == CarouselExecutionMode.MANUAL_RESUME:
        return _remaining_daily_image_quota(profile)
    used = _usage_today(profile)
    tick_limit = max(0, int(settings.SOCIAL_AI_IMAGE_MAX_PER_TICK))
    tick_remaining = max(0, tick_limit - used)
    return max(0, min(_remaining_daily_image_quota(profile), tick_remaining))


def _image_quota_block_reason(profile):
    used = _usage_today(profile)
    if profile.ai_image_daily_limit and used >= profile.ai_image_daily_limit:
        return 'Limite diario do perfil atingido.'
    if used >= settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY:
        return 'Limite diario global do perfil atingido.'
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
    else:
        content.erro = ''
    content.save(update_fields=['erro', 'updated_at'])
    registrar_evento(content, 'gerado_ia', usuario, f'Carrossel AI_FINISHED. Tema: {tema or "-"}')
    return result


def _start_manual_resume_run(content, profile, creative_direction):
    stale_before = timezone.now() - timezone.timedelta(minutes=MANUAL_RESUME_STALE_MINUTES)
    with transaction.atomic():
        SocialContent.objects.select_for_update().get(pk=content.pk)
        active_runs = SocialCarouselGenerationRun.objects.select_for_update().filter(
            content=content,
            status=SocialCarouselGenerationRun.Status.COMPOSING,
            metadata__execution_mode=CarouselExecutionMode.MANUAL_RESUME,
        )
        if active_runs.filter(started_at__gte=stale_before).exists():
            return None
        stale_count = active_runs.filter(started_at__lt=stale_before).update(
            status=SocialCarouselGenerationRun.Status.PARTIAL,
            error='Execucao manual anterior ficou sem atividade e foi liberada para retomada.',
            finished_at=timezone.now(),
        )
        if stale_count:
            _release_stale_manual_slides(content)
        return SocialCarouselGenerationRun.objects.create(
            profile=profile,
            content=content,
            generation_mode=profile.carousel_generation_mode,
            status=SocialCarouselGenerationRun.Status.COMPOSING,
            creative_blueprint=creative_direction if isinstance(creative_direction, dict) else {},
            metadata={'resume': True, 'execution_mode': CarouselExecutionMode.MANUAL_RESUME},
        )


def _validate_manual_resume_content(content):
    profile = content.profile
    if not content.is_carousel or profile.carousel_generation_mode != SocialProfile.CarouselGenerationMode.AI_FINISHED:
        raise ValidationError('Retomada disponivel somente para carrossel AI_FINISHED.')
    if not content.pode_editar_operacionalmente:
        raise ValidationError('Conteudo publicado nao pode retomar composicao pela interface operacional.')
    return profile


def _manual_resume_context(content):
    profile = content.profile
    template = content.carousel_template or _carousel_template(profile)
    aspect_ratio = template.aspect_ratio if template else 'SQUARE'
    latest_run = content.carousel_generation_runs.order_by('-started_at').first()
    creative_direction = latest_run.creative_blueprint if latest_run and latest_run.creative_blueprint else {}
    return profile, aspect_ratio, creative_direction


def start_manual_resume_ai_finished(content, *, usuario=None):
    profile = _validate_manual_resume_content(content)
    _, _, creative_direction = _manual_resume_context(content)
    result = AutonomousCarouselResult(content=content)
    call_cap = max(0, int(getattr(settings, 'SOCIAL_AI_COMPOSED_MAX_CALLS_PER_CAROUSEL', 8)))
    spent_in_content = composition_calls_used(content)
    remaining = min(max(0, call_cap - spent_in_content), _remaining_image_quota(profile, execution_mode=CarouselExecutionMode.MANUAL_RESUME))
    result.composition_calls_used = spent_in_content
    result.composition_call_cap = call_cap
    result.quota_remaining = remaining
    run = _start_manual_resume_run(content, profile, creative_direction)
    if run is None:
        result.pending_slides = content.carousel_slides.filter(is_active=True).exclude(ai_composition_status=SocialCarouselSlide.CompositionStatus.READY).count()
        result.messages.append('Composicao ja esta em andamento.')
        return result
    result.run = run
    result.step = 'START'
    result.has_more_work = _manual_resume_has_more_work(content)
    _fill_ai_finished_progress(result, content)
    registrar_evento(content, 'gerado_ia', usuario, 'Retomada AI_FINISHED incremental iniciada.')
    return result


def retomar_ai_finished_content(content, *, usuario=None):
    return start_manual_resume_ai_finished(content, usuario=usuario)


def advance_manual_resume_ai_finished(content, *, usuario=None):
    profile = _validate_manual_resume_content(content)
    profile, aspect_ratio, creative_direction = _manual_resume_context(content)
    run = _active_manual_resume_run(content)
    if run is None:
        run = _start_manual_resume_run(content, profile, creative_direction)
    result = AutonomousCarouselResult(content=content, run=run)
    if run is None:
        result.messages.append('Composicao ja esta em andamento.')
        _fill_ai_finished_progress(result, content)
        result.has_more_work = True
        result.blocking_reason = result.messages[-1]
        return result

    reviewing = _claim_reviewing_slide(content)
    if reviewing:
        result.step = 'REVIEW'
        result.slide_order = reviewing.order
        try:
            review = _refresh_ai_finished_review_if_needed(reviewing, creative_direction) or _review_claimed_slide(reviewing, creative_direction)
        except Exception as exc:
            reviewing.ai_composition_status = SocialCarouselSlide.CompositionStatus.REVIEWING
            reviewing.save(update_fields=['ai_composition_status', 'updated_at'])
            run.status = SocialCarouselGenerationRun.Status.ERROR
            run.error = str(exc)[:1000]
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error', 'finished_at'])
            raise
        if review.valid:
            result.approved_slides = 1
        else:
            result.failed_slides = 1
            result.messages.extend(review.issues or ['Review automatico reprovou a arte final.'])
        _finish_manual_resume_advance(content, run, result)
        return result

    call_cap = max(0, int(getattr(settings, 'SOCIAL_AI_COMPOSED_MAX_CALLS_PER_CAROUSEL', 8)))
    spent_in_content = composition_calls_used(content)
    remaining = min(max(0, call_cap - spent_in_content), _remaining_image_quota(profile, execution_mode=CarouselExecutionMode.MANUAL_RESUME))
    result.composition_calls_used = spent_in_content
    result.composition_call_cap = call_cap
    result.quota_remaining = remaining
    max_attempts = max(1, int(getattr(settings, 'SOCIAL_AI_COMPOSED_SLIDE_MAX_ATTEMPTS', 2)))
    work_queue = get_composition_work_queue(content, max_attempts=max_attempts)
    if work_queue and remaining <= 0:
        result.messages.append(_no_work_reason(remaining, call_cap, spent_in_content, profile))
        result.blocking_reason = result.messages[-1]
        _finish_manual_resume_advance(content, run, result)
        return result
    first_attempts = [item for item in work_queue if item['action'] in {'COMPOSE_FIRST_ATTEMPT', 'RECOMPOSE'}]
    retries = [item for item in work_queue if item['action'] == 'RETRY']

    for item in [*first_attempts, *retries]:
        slide = item['slide']
        if remaining <= 0:
            if item['action'] == 'RETRY':
                result.messages.append(
                    f'Slide {slide.order}: retry adiado por {_ai_finished_quota_reason(profile, call_cap, result.generated_images + spent_in_content)}'
                )
                break
            _mark_ai_finished_pending_by_quota(slide, result, _ai_finished_quota_reason(profile, call_cap, result.generated_images + spent_in_content))
            break
        claimed = _claim_composition_slide(item, max_attempts=max_attempts)
        if claimed is None:
            result.messages.append(f'Slide {slide.order}: composicao ignorada porque o slide ja foi alterado por outra execucao.')
            continue
        slide = claimed
        try:
            composed = compose_slide_image_with_ai(slide, creative_direction, slide.creative_plan_metadata or {}, aspect_ratio=aspect_ratio, remaining_calls=1)
        except Exception as exc:
            slide.ai_composition_status = item['status']
            slide.save(update_fields=['ai_composition_status', 'updated_at'])
            run.status = SocialCarouselGenerationRun.Status.ERROR
            run.error = str(exc)[:1000]
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error', 'finished_at'])
            raise
        remaining = _record_ai_finished_result(result, composed, remaining)
        result.processed_slides += 1 if composed.attempts else 0
        result.failed_slides += 1 if composed.issues and not composed.pending and not composed.ready else 0
        result.step = 'COMPOSE'
        result.slide_order = slide.order
        break

    _finish_manual_resume_advance(content, run, result)
    return result


def _finish_manual_resume_advance(content, run, result):
    _fill_ai_finished_progress(result, content)
    result.composition_calls_used = composition_calls_used(content)
    result.composition_call_cap = max(0, int(getattr(settings, 'SOCIAL_AI_COMPOSED_MAX_CALLS_PER_CAROUSEL', 8)))
    result.quota_remaining = min(
        max(0, result.composition_call_cap - result.composition_calls_used),
        _remaining_image_quota(content.profile, execution_mode=CarouselExecutionMode.MANUAL_RESUME),
    )
    result.has_more_work = _manual_resume_has_more_work(content)
    if content.status != content.Status.PUBLICADO:
        from .container_versioning import invalidate_instagram_container

        invalidate_instagram_container(content, reason='ai_finished_carousel_resumed')
    quality = evaluate_carousel_quality(content)
    if quality.valid:
        content.erro = ''
        run.status = SocialCarouselGenerationRun.Status.READY
        result.has_more_work = False
    elif result.has_more_work:
        content.erro = 'Carrossel AI_FINISHED ainda nao aprovado: ' + '; '.join(quality.issues)[:900]
        run.status = SocialCarouselGenerationRun.Status.COMPOSING
    else:
        content.erro = 'Carrossel AI_FINISHED ainda nao aprovado: ' + '; '.join(quality.issues)[:900]
        run.status = SocialCarouselGenerationRun.Status.PARTIAL
        result.blocking_reason = result.messages[-1] if result.messages else content.erro[:180]
    content.save(update_fields=['erro', 'updated_at'])
    run.error = content.erro[:1000]
    run.finished_at = timezone.now() if run.status in {SocialCarouselGenerationRun.Status.READY, SocialCarouselGenerationRun.Status.PARTIAL, SocialCarouselGenerationRun.Status.ERROR} else None
    run.save(update_fields=['status', 'error', 'finished_at'])
    registrar_evento(
        content,
        'gerado_ia',
        None,
        (
            f'Retomada AI_FINISHED incremental: etapa {result.step or "-"}'
            f'{f" slide {result.slide_order}" if result.slide_order else ""}; '
            f'{result.composition_calls_used}/{result.composition_call_cap} chamadas utilizadas.'
        ),
    )


def _fill_ai_finished_progress(result, content):
    slides = list(content.carousel_slides.filter(is_active=True, render_mode=SocialCarouselSlide.RenderMode.AI_FINISHED))
    result.pending_slides = sum(1 for slide in slides if slide.ai_composition_status != SocialCarouselSlide.CompositionStatus.READY)
    result.approved_slides += 0


def _manual_resume_has_more_work(content):
    return bool(_claimable_reviewing_exists(content) or get_composition_work_queue(content))


def _active_manual_resume_run(content):
    stale_before = timezone.now() - timezone.timedelta(minutes=MANUAL_RESUME_STALE_MINUTES)
    active = (
        SocialCarouselGenerationRun.objects.filter(
            content=content,
            status=SocialCarouselGenerationRun.Status.COMPOSING,
            metadata__execution_mode=CarouselExecutionMode.MANUAL_RESUME,
        )
        .order_by('-started_at', '-id')
        .first()
    )
    if active and active.started_at < stale_before:
        active.status = SocialCarouselGenerationRun.Status.PARTIAL
        active.error = 'Execucao manual anterior ficou sem atividade e foi liberada para retomada.'
        active.finished_at = timezone.now()
        active.save(update_fields=['status', 'error', 'finished_at'])
        with transaction.atomic():
            SocialContent.objects.select_for_update().get(pk=content.pk)
            _release_stale_manual_slides(content)
        return None
    return active


def _claimable_reviewing_exists(content):
    return content.carousel_slides.filter(
        is_active=True,
        render_mode=SocialCarouselSlide.RenderMode.AI_FINISHED,
        ai_composition_status=SocialCarouselSlide.CompositionStatus.REVIEWING,
        ai_composed_image__isnull=False,
    ).exists()


def _claim_reviewing_slide(content):
    with transaction.atomic():
        slide = (
            SocialCarouselSlide.objects.select_for_update()
            .filter(
                content=content,
                is_active=True,
                render_mode=SocialCarouselSlide.RenderMode.AI_FINISHED,
                ai_composition_status=SocialCarouselSlide.CompositionStatus.REVIEWING,
                ai_composed_image__isnull=False,
            )
            .order_by('order', 'id')
            .first()
        )
        if slide:
            metadata = slide.ai_composition_metadata or {}
            metadata.update({'manual_resume_claim': True, 'manual_resume_previous_status': SocialCarouselSlide.CompositionStatus.REVIEWING})
            slide.ai_composition_metadata = metadata
            slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.COMPOSING
            slide.save(update_fields=['ai_composition_status', 'ai_composition_metadata', 'updated_at'])
        return slide


def _review_claimed_slide(slide, creative_direction):
    return rereview_ai_finished_slide(slide, creative_direction=creative_direction)


def _release_stale_manual_slides(content):
    valid_previous = {
        SocialCarouselSlide.CompositionStatus.PENDING,
        SocialCarouselSlide.CompositionStatus.REVIEWING,
        SocialCarouselSlide.CompositionStatus.ERROR,
        SocialCarouselSlide.CompositionStatus.NEEDS_RECOMPOSE,
    }
    for slide in SocialCarouselSlide.objects.select_for_update().filter(
        content=content,
        is_active=True,
        render_mode=SocialCarouselSlide.RenderMode.AI_FINISHED,
        ai_composition_status=SocialCarouselSlide.CompositionStatus.COMPOSING,
    ):
        metadata = slide.ai_composition_metadata or {}
        if not metadata.get('manual_resume_claim'):
            continue
        previous = metadata.get('manual_resume_previous_status') or SocialCarouselSlide.CompositionStatus.PENDING
        slide.ai_composition_status = previous if previous in valid_previous else SocialCarouselSlide.CompositionStatus.PENDING
        metadata.pop('manual_resume_claim', None)
        metadata.pop('manual_resume_previous_status', None)
        slide.ai_composition_metadata = metadata
        slide.save(update_fields=['ai_composition_status', 'ai_composition_metadata', 'updated_at'])


def _claim_composition_slide(item, *, max_attempts):
    with transaction.atomic():
        slide = SocialCarouselSlide.objects.select_for_update().get(pk=item['slide'].pk)
        if slide.render_mode != SocialCarouselSlide.RenderMode.AI_FINISHED:
            return None
        if slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.PENDING and slide.ai_composition_attempts == 0:
            if item['action'] != 'COMPOSE_FIRST_ATTEMPT':
                return None
        elif slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.NEEDS_RECOMPOSE:
            if item['action'] != 'RECOMPOSE':
                return None
        elif slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.ERROR and slide.ai_composition_attempts < max_attempts:
            if item['action'] != 'RETRY':
                return None
        else:
            return None
        metadata = slide.ai_composition_metadata or {}
        metadata.update({'manual_resume_claim': True, 'manual_resume_previous_status': slide.ai_composition_status})
        slide.ai_composition_metadata = metadata
        slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.COMPOSING
        slide.save(update_fields=['ai_composition_status', 'ai_composition_metadata', 'updated_at'])
        return slide


def composition_calls_used(content):
    usages = list(
        SocialAIUsage.objects.filter(
            content=content,
            operation=SocialAIUsage.Operation.COMPOSED_SLIDE,
        ).only('metadata')
    )
    provider_calls = [
        usage
        for usage in usages
        if (usage.metadata or {}).get('purpose') == 'CAROUSEL_COMPOSED_SLIDE' or (usage.metadata or {}).get('provider_called')
    ]
    if provider_calls:
        return len(provider_calls)
    return sum(
        slide.ai_composition_attempts
        for slide in content.carousel_slides.filter(is_active=True, render_mode=SocialCarouselSlide.RenderMode.AI_FINISHED)
    )


def get_composition_work_queue(content, *, max_attempts=None):
    max_attempts = max_attempts or max(1, int(getattr(settings, 'SOCIAL_AI_COMPOSED_SLIDE_MAX_ATTEMPTS', 2)))
    queue = []
    slides = list(content.carousel_slides.filter(is_active=True).order_by('order', 'id'))
    priority = {
        'COMPOSE_FIRST_ATTEMPT': 1,
        'RECOMPOSE': 2,
        'RETRY': 3,
    }
    for slide in slides:
        item = {
            'slide': slide,
            'slide_id': slide.id,
            'status': slide.ai_composition_status,
            'attempts': slide.ai_composition_attempts,
            'action': 'SKIP',
            'reason': 'ALREADY_READY' if slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.READY else 'NOT_ACTIONABLE',
            'priority': 99,
        }
        if slide.render_mode != SocialCarouselSlide.RenderMode.AI_FINISHED:
            item['reason'] = 'NOT_AI_FINISHED'
        elif slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.PENDING and slide.ai_composition_attempts == 0:
            item.update({'action': 'COMPOSE_FIRST_ATTEMPT', 'reason': 'never attempted', 'priority': priority['COMPOSE_FIRST_ATTEMPT']})
        elif slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.NEEDS_RECOMPOSE:
            item.update({'action': 'RECOMPOSE', 'reason': 'copy or creative plan changed', 'priority': priority['RECOMPOSE']})
        elif slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.ERROR and slide.ai_composition_attempts < max_attempts:
            item.update({'action': 'RETRY', 'reason': 'review failed and attempts remain', 'priority': priority['RETRY']})
        elif slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.ERROR:
            item['reason'] = 'SLIDE_MAX_ATTEMPTS'
        queue.append(item)
    return sorted([item for item in queue if item['action'] != 'SKIP'], key=lambda item: (item['priority'], item['slide'].order, item['slide'].id))


def _no_work_reason(remaining, call_cap, spent_in_content, profile):
    if call_cap <= 0 or spent_in_content >= call_cap:
        return 'Nenhum slide pode ser composto: limite de chamadas deste carrossel atingido.'
    if _remaining_daily_image_quota(profile) <= 0:
        return f'Nenhum slide pode ser composto: {_image_quota_block_reason(profile)}'
    if remaining <= 0:
        return 'Nenhum slide pode ser composto: limite desta execucao atingido.'
    return 'Nenhum slide pode ser composto.'


def _resume_review_candidates(slides):
    return [
        slide
        for slide in slides
        if slide.render_mode == SocialCarouselSlide.RenderMode.AI_FINISHED
        and slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.ERROR
        and slide.ai_composed_image
        and _needs_ai_finished_review_refresh(slide)
    ]


def _resume_pending_candidates(slides):
    priority_statuses = {
        SocialCarouselSlide.CompositionStatus.PENDING,
        SocialCarouselSlide.CompositionStatus.NEEDS_RECOMPOSE,
    }
    return [
        slide
        for slide in slides
        if slide.render_mode == SocialCarouselSlide.RenderMode.AI_FINISHED
        and slide.ai_composition_status in priority_statuses
        and not slide.get_final_image()
    ]


def _needs_ai_finished_review_refresh(slide):
    review = slide.ai_review_metadata or {}
    metadata = slide.ai_composition_metadata or {}
    if review.get('review_schema_version') != 2 or review.get('score_scale') != 100:
        return True
    return bool(metadata.get('raw_composed_image') and metadata.get('brand_overlay_version') != BRAND_OVERLAY_VERSION)


def _refresh_ai_finished_review_if_needed(slide, creative_direction):
    if not _needs_ai_finished_review_refresh(slide):
        return None
    metadata = slide.ai_composition_metadata or {}
    if metadata.get('raw_composed_image') and metadata.get('brand_overlay_version') != BRAND_OVERLAY_VERSION:
        return reapply_system_brand_overlay(slide, creative_direction=creative_direction)
    return rereview_ai_finished_slide(slide, creative_direction=creative_direction)


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
