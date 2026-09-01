from dataclasses import dataclass, field
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .ai import OpenAINotConfigured, OpenAIUnavailable, _client, moderar_conteudo
from .carousel_creative_blueprint import composition_fingerprint, slide_text_snapshot
from .composed_slide_review import ComposedSlideReviewResult, review_composed_slide
from .image_generation import SocialImageGenerationDisabled, _extract_image_bytes, _sanitize_metadata, _sanitize_value, _validate_image_bytes, image_generation_available
from .models import SocialAIUsage, SocialCarouselSlide, SocialProfile


BRAND_MODE_SYSTEM_OVERLAY = 'SYSTEM_BRAND_OVERLAY'
BRAND_MODE_FULL_AI = 'FULL_AI'
BRAND_OVERLAY_VERSION = 2


@dataclass
class ComposeSlideResult:
    slide: SocialCarouselSlide
    composed: bool = False
    reused: bool = False
    ready: bool = False
    pending: bool = False
    attempts: int = 0
    issues: list[str] = field(default_factory=list)


def build_composed_slide_prompt(profile, slide, creative_direction, creative_plan, *, aspect_ratio='SQUARE', brand_mode=BRAND_MODE_SYSTEM_OVERLAY, previous_issues=None):
    identity = profile.visual_identities.filter(active=True, is_default=True).first()
    brand = {
        'brand_name': identity.display_brand_name if identity else profile.nome,
        'handle': profile.username,
        'primary_color': identity.primary_color if identity else '#111827',
        'secondary_color': identity.secondary_color if identity else '#334155',
        'accent_color': identity.accent_color if identity else '#22c55e',
        'font_policy': 'Use a brand typography spirit; do not invent unreadable decorative fonts.',
        'brand_overlay': brand_mode,
    }
    plan = creative_plan or {}
    previous_issues = previous_issues or []
    return '\n'.join(
        [
            'ROLE: You are a senior social media art director creating one final Instagram carousel slide.',
            'OUTPUT: Generate a complete final social media slide image. Text and art must be visually integrated.',
            'Do not create a blank background for later text placement. Do not add watermark, extra slogans, signatures, fake usernames or unrequested text.',
            f'PROFILE: {profile.nome} ({profile.username}).',
            f'PROFILE STYLE: {profile.estilo or "not specified"}.',
            f'PROFILE INSTRUCTIONS: {profile.instrucoes_ia or "not specified"}.',
            f'CAROUSEL INSTRUCTIONS: {profile.carousel_ai_instructions or "not specified"}.',
            f'BRAND: {brand}.',
            f'CAROUSEL CONCEPT: {creative_direction.as_dict() if hasattr(creative_direction, "as_dict") else creative_direction}.',
            f'SLIDE ROLE: {slide.slide_role}.',
            f'COMPOSITION TYPE: {plan.get("composition_type") or slide.composition_type}.',
            f'VISUAL GOAL: {plan.get("visual_goal") or ""}.',
            f'CONTINUITY: {plan.get("continuity_notes") or ""}.',
            f'SIZE/ASPECT: {aspect_ratio}.',
            'Render exactly the following Portuguese text. Preserve accents, punctuation and line meaning. Do not translate.',
            f'TITLE: {slide.title or ""}',
            f'BODY: {slide.body or ""}',
            'If BODY is empty, do not invent body copy.',
            'Keep the exact words readable on mobile and inside the art composition.',
            f'PREVIOUS ATTEMPT ISSUES TO CORRECT: {previous_issues}.',
        ]
    )


def compose_slide_with_ai(slide, creative_direction, creative_plan=None, *, aspect_ratio='SQUARE', brand_mode=BRAND_MODE_SYSTEM_OVERLAY, remaining_calls=None):
    profile = slide.content.profile
    plan = creative_plan or slide.creative_plan_metadata or {}
    fingerprint = composition_fingerprint(profile, slide, plan, aspect_ratio=aspect_ratio, brand_mode=brand_mode)
    if _can_reuse(slide, fingerprint):
        slide.rendered_image.name = slide.ai_composed_image.name
        slide.save(update_fields=['rendered_image', 'updated_at'])
        return ComposeSlideResult(slide=slide, reused=True, ready=True, attempts=0)
    if not image_generation_available(profile):
        _mark_pending(slide, fingerprint, 'Geracao de arte final IA indisponivel.')
        return ComposeSlideResult(slide=slide, pending=True, issues=['Geracao de arte final IA indisponivel.'])
    if profile.ai_image_policy in {SocialProfile.AIImagePolicy.NONE, SocialProfile.AIImagePolicy.BANK_ONLY}:
        _mark_pending(slide, fingerprint, 'Politica do perfil nao permite arte final IA.')
        return ComposeSlideResult(slide=slide, pending=True, issues=['Politica do perfil nao permite arte final IA.'])
    if remaining_calls is not None and remaining_calls <= 0:
        _mark_pending(slide, fingerprint, 'Quota do carrossel para arte final IA esgotada.')
        return ComposeSlideResult(slide=slide, pending=True, issues=['Quota do carrossel para arte final IA esgotada.'])

    max_attempts = max(1, int(getattr(settings, 'SOCIAL_AI_COMPOSED_SLIDE_MAX_ATTEMPTS', 2)))
    previous_attempts = slide.ai_composition_attempts if slide.ai_composition_fingerprint == fingerprint else 0
    remaining_attempts = max_attempts - previous_attempts
    if remaining_attempts <= 0:
        issues = ['Maximo de tentativas deste slide atingido.']
        _mark_error(slide, fingerprint, issues, previous_attempts)
        return ComposeSlideResult(slide=slide, attempts=0, issues=issues)
    if remaining_calls is not None:
        remaining_attempts = min(remaining_attempts, max(1, int(remaining_calls)))
    issues = []
    attempts_spent = 0
    for local_attempt in range(1, remaining_attempts + 1):
        attempt = previous_attempts + local_attempt
        if _daily_quota_remaining(profile) <= 0:
            _register_usage(slide, success=False, error='Quota diaria de composicao IA esgotada.', metadata={'fingerprint': fingerprint, 'attempt': attempt})
            _mark_pending(slide, fingerprint, 'Quota diaria de composicao IA esgotada.')
            return ComposeSlideResult(slide=slide, pending=True, attempts=attempts_spent, issues=['Quota diaria de composicao IA esgotada.'])
        prompt = build_composed_slide_prompt(profile, slide, creative_direction, plan, aspect_ratio=aspect_ratio, brand_mode=brand_mode, previous_issues=issues)
        if moderar_conteudo(prompt):
            _register_usage(slide, success=False, error='Prompt de composicao bloqueado pela moderacao.', metadata={'fingerprint': fingerprint})
            _mark_error(slide, fingerprint, ['Prompt de composicao bloqueado pela moderacao.'], attempt)
            return ComposeSlideResult(slide=slide, attempts=attempts_spent, issues=['Prompt de composicao bloqueado pela moderacao.'])
        try:
            image_bytes, response_id = _generate_image_bytes(prompt, aspect_ratio=aspect_ratio)
            attempts_spent += 1
            raw_image_bytes = _normalize_image(image_bytes, aspect_ratio=aspect_ratio)
            final_image_bytes = _apply_system_brand_overlay_to_bytes(raw_image_bytes, profile, slide) if brand_mode == BRAND_MODE_SYSTEM_OVERLAY else raw_image_bytes
            _validate_image_bytes(final_image_bytes)
            _persist_composed_slide(slide, final_image_bytes, fingerprint, response_id, attempt, plan, brand_mode, raw_image_bytes=raw_image_bytes)
            _register_usage(slide, success=True, metadata={'fingerprint': fingerprint, 'attempt': attempt, 'purpose': 'CAROUSEL_COMPOSED_SLIDE', 'provider_called': True})
            review = review_composed_slide(slide, creative_direction=creative_direction)
            slide.ai_review_metadata = review.as_dict()
            slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.READY if review.valid else SocialCarouselSlide.CompositionStatus.ERROR
            slide.ai_composition_attempts = attempt
            slide.save(update_fields=['ai_review_metadata', 'ai_composition_status', 'ai_composition_attempts', 'updated_at'])
            if review.valid:
                return ComposeSlideResult(slide=slide, composed=True, ready=True, attempts=attempts_spent)
            issues = review.issues or ['Review automatico reprovou a arte final.']
        except (OpenAINotConfigured, SocialImageGenerationDisabled):
            raise
        except Exception as exc:
            issues = ['Falha controlada na composicao IA do slide.']
            _register_usage(slide, success=False, error=exc, metadata={'fingerprint': fingerprint, 'attempt': attempt, 'purpose': 'CAROUSEL_COMPOSED_SLIDE', 'provider_called': True})
            if local_attempt >= remaining_attempts:
                _mark_error(slide, fingerprint, issues, attempt)
                return ComposeSlideResult(slide=slide, attempts=attempts_spent, issues=issues)

    _mark_error(slide, fingerprint, issues, previous_attempts + attempts_spent)
    return ComposeSlideResult(slide=slide, attempts=attempts_spent, issues=issues)


def _can_reuse(slide, fingerprint):
    return bool(
        slide.ai_composed_image
        and slide.ai_composition_fingerprint == fingerprint
        and slide.ai_composition_status == SocialCarouselSlide.CompositionStatus.READY
    )


def _generate_image_bytes(prompt, *, aspect_ratio):
    response = _client().images.generate(
        model=settings.OPENAI_SOCIAL_IMAGE_MODEL,
        prompt=prompt,
        size=_image_size(aspect_ratio),
        quality=settings.OPENAI_SOCIAL_IMAGE_QUALITY,
        n=1,
    )
    return _extract_image_bytes(response), getattr(response, 'id', '') or ''


def _normalize_image(image_bytes, *, aspect_ratio):
    target = (1080, 1350) if (aspect_ratio or '').upper() in {'PORTRAIT', '4:5', '1080X1350'} else (1080, 1080)
    with Image.open(BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail(target, Image.Resampling.LANCZOS)
        canvas = Image.new('RGB', target, color='white')
        left = (target[0] - image.width) // 2
        top = (target[1] - image.height) // 2
        canvas.paste(image, (left, top))
    output = BytesIO()
    canvas.save(output, format='JPEG', quality=92, optimize=True)
    return output.getvalue()


def _apply_system_brand_overlay_to_bytes(image_bytes, profile, slide):
    with Image.open(BytesIO(image_bytes)) as image:
        canvas = ImageOps.exif_transpose(image).convert('RGB')
        _apply_brand_overlay(canvas, profile, slide)
        output = BytesIO()
        canvas.save(output, format='JPEG', quality=92, optimize=True)
        return output.getvalue()


def _apply_brand_overlay(canvas, profile, slide):
    draw = ImageDraw.Draw(canvas)
    handle, counter = brand_overlay_elements(profile, slide)
    if not handle and not counter:
        return
    font = _brand_overlay_font(max(24, int(canvas.width * 0.026)))
    padding = max(24, int(canvas.width * 0.030))
    gap = max(10, int(canvas.width * 0.010))
    y = canvas.height - padding
    if handle:
        _draw_overlay_chip(draw, (padding, y), handle, font, anchor='bottom-left', gap=gap)
    if counter:
        _draw_overlay_chip(draw, (canvas.width - padding, y), counter, font, anchor='bottom-right', gap=gap)


def brand_overlay_elements(profile, slide):
    username = (profile.username or '').strip().lstrip('@')
    handle = f'@{username}' if username else ''
    total = slide.content.carousel_slides.filter(is_active=True).count() or slide.order
    counter = f'{slide.order}/{total}'
    return handle, counter


def _brand_overlay_font(size):
    for font_name in ['DejaVuSans-Bold.ttf', 'Arial.ttf']:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_overlay_chip(draw, point, text, font, *, anchor, gap):
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    radius = max(10, int(height * 0.55))
    px = max(14, int(height * 0.75))
    py = max(9, int(height * 0.45))
    x, y = point
    if anchor == 'bottom-right':
        left = x - width - (px * 2)
    else:
        left = x
    top = y - height - (py * 2)
    right = left + width + (px * 2)
    bottom = y
    draw.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(17, 24, 39), outline=(255, 255, 255), width=1)
    draw.text((left + px, top + py - bbox[1]), text, fill=(255, 255, 255), font=font)


def reapply_system_brand_overlay(slide, *, creative_direction=None):
    raw_name = (slide.ai_composition_metadata or {}).get('raw_composed_image')
    if not raw_name or not default_storage.exists(raw_name):
        result = ComposedSlideReviewResult(False, 0, 0, 0, 0, 0, ['Arte base sem overlay inexistente.'], ['Arte base sem overlay inexistente.'])
        slide.ai_review_metadata = result.as_dict()
        slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.ERROR
        slide.save(update_fields=['ai_review_metadata', 'ai_composition_status', 'updated_at'])
        return result
    with default_storage.open(raw_name, 'rb') as arquivo:
        final_image_bytes = _apply_system_brand_overlay_to_bytes(arquivo.read(), slide.content.profile, slide)
    filename = f'{slide.ai_composition_fingerprint or slide.id}-brand-v{BRAND_OVERLAY_VERSION}.jpg'
    slide.ai_composed_image.save(filename, ContentFile(final_image_bytes), save=False)
    slide.rendered_image.name = slide.ai_composed_image.name
    metadata = slide.ai_composition_metadata or {}
    metadata.update({'brand_mode': BRAND_MODE_SYSTEM_OVERLAY, 'brand_overlay_version': BRAND_OVERLAY_VERSION, 'brand_overlay': dict(zip(['handle', 'counter'], brand_overlay_elements(slide.content.profile, slide)))})
    slide.ai_composition_metadata = metadata
    slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.REVIEWING
    slide.save(update_fields=['ai_composed_image', 'rendered_image', 'ai_composition_metadata', 'ai_composition_status', 'updated_at'])
    result = review_composed_slide(slide, image_field=slide.ai_composed_image, creative_direction=creative_direction)
    slide.ai_review_metadata = result.as_dict()
    slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.READY if result.valid else SocialCarouselSlide.CompositionStatus.ERROR
    slide.save(update_fields=['ai_review_metadata', 'ai_composition_status', 'updated_at'])
    return result


def _persist_composed_slide(slide, image_bytes, fingerprint, response_id, attempt, plan, brand_mode, *, raw_image_bytes=None):
    filename = f'{fingerprint}.jpg'
    raw_name = ''
    if raw_image_bytes:
        raw_name = _raw_composed_image_name(slide, fingerprint)
        raw_name = default_storage.save(raw_name, ContentFile(raw_image_bytes))
    slide.ai_composed_image.save(filename, ContentFile(image_bytes), save=False)
    slide.rendered_image.name = slide.ai_composed_image.name
    slide.render_mode = SocialCarouselSlide.RenderMode.AI_FINISHED
    slide.ai_composition_id = response_id
    slide.ai_composition_fingerprint = fingerprint
    slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.REVIEWING
    slide.ai_composition_attempts = attempt
    slide.rendered_text_snapshot = slide_text_snapshot(slide)
    slide.creative_plan_metadata = plan
    metadata = {'fingerprint': fingerprint, 'attempt': attempt, 'brand_mode': brand_mode}
    if raw_name:
        metadata.update({'raw_composed_image': raw_name, 'brand_overlay_version': BRAND_OVERLAY_VERSION, 'brand_overlay': dict(zip(['handle', 'counter'], brand_overlay_elements(slide.content.profile, slide)))})
    slide.ai_composition_metadata = metadata
    slide.save()


def _raw_composed_image_name(slide, fingerprint):
    profile_id = slide.content.profile_id if slide.content_id else 'sem-perfil'
    content_id = slide.content_id or 'sem-conteudo'
    return f'social/{profile_id}/carousels/{content_id}/composed_raw/{fingerprint}.jpg'


def _daily_quota_remaining(profile):
    today = timezone.localdate()
    limit = profile.ai_image_daily_limit or settings.SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY
    used = SocialAIUsage.objects.filter(
        profile=profile,
        operation__in=[SocialAIUsage.Operation.IMAGE_GENERATION, SocialAIUsage.Operation.COMPOSED_SLIDE],
        success=True,
        created_at__date=today,
    ).count()
    return max(0, limit - used)


def _register_usage(slide, *, success, error='', metadata=None):
    return SocialAIUsage.objects.create(
        profile=slide.content.profile,
        content=slide.content,
        slide=slide,
        operation=SocialAIUsage.Operation.COMPOSED_SLIDE,
        model=settings.OPENAI_SOCIAL_IMAGE_MODEL,
        success=success,
        error=_sanitize_value(error or '')[:500],
        metadata=_sanitize_metadata(metadata or {}),
    )


def _mark_pending(slide, fingerprint, reason):
    slide.ai_composition_fingerprint = fingerprint
    slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.PENDING
    slide.ai_composition_metadata = {'reason': reason, 'fingerprint': fingerprint}
    slide.save(update_fields=['ai_composition_fingerprint', 'ai_composition_status', 'ai_composition_metadata', 'updated_at'])


def _mark_error(slide, fingerprint, issues, attempts):
    slide.ai_composition_fingerprint = fingerprint
    slide.ai_composition_status = SocialCarouselSlide.CompositionStatus.ERROR
    slide.ai_composition_attempts = attempts
    slide.ai_review_metadata = {'valid': False, 'issues': issues}
    slide.ai_composition_metadata = {'fingerprint': fingerprint, 'issues': issues}
    slide.save(update_fields=['ai_composition_fingerprint', 'ai_composition_status', 'ai_composition_attempts', 'ai_review_metadata', 'ai_composition_metadata', 'updated_at'])


def _image_size(aspect_ratio):
    return '1024x1536' if (aspect_ratio or '').upper() in {'PORTRAIT', '4:5', '1080X1350'} else '1024x1024'
