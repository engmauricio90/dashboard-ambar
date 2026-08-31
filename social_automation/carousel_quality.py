from dataclasses import dataclass, field

from .models import SocialCarouselSlide, SocialContent, SocialProfile


VISUAL_TREATMENTS = {
    SocialCarouselSlide.VisualTreatment.IMAGE_HERO,
    SocialCarouselSlide.VisualTreatment.IMAGE_BACKGROUND,
    SocialCarouselSlide.VisualTreatment.IMAGE_SPLIT,
    SocialCarouselSlide.VisualTreatment.EDITORIAL_CARD,
    SocialCarouselSlide.VisualTreatment.GRAPHIC_BACKGROUND,
    SocialCarouselSlide.VisualTreatment.MINIMAL_VISUAL,
}

IMAGE_TREATMENTS = {
    SocialCarouselSlide.VisualTreatment.IMAGE_HERO,
    SocialCarouselSlide.VisualTreatment.IMAGE_BACKGROUND,
    SocialCarouselSlide.VisualTreatment.IMAGE_SPLIT,
}

TEXT_ONLY_LAYOUTS = {'FULL_TEXT', 'MINIMAL'}


@dataclass(frozen=True)
class CarouselQualityResult:
    valid: bool
    visual_mode: str
    active_slides: int
    visual_slides: int
    image_slides: int
    distinct_images: int
    plain_text_slides: int
    score: int
    issues: list[str] = field(default_factory=list)


def _slide_base_image_valid(slide):
    return bool(
        slide.source_base_image_id
        and slide.content_id
        and slide.source_base_image.profile_id == slide.content.profile_id
    )


def _slide_has_image(slide):
    return bool(_slide_base_image_valid(slide) or slide.source_image)


def _slide_visual_treatment(slide):
    treatment = slide.visual_treatment or SocialCarouselSlide.VisualTreatment.AUTO
    if treatment == SocialCarouselSlide.VisualTreatment.AUTO:
        if _slide_has_image(slide):
            return SocialCarouselSlide.VisualTreatment.IMAGE_BACKGROUND
        if (slide.visual_intent or '').upper() in {'GRAPHIC_DARK', 'GRAPHIC_LIGHT', 'EDITORIAL_CARD', 'CTA_VISUAL', 'CENTER_CARD'}:
            return SocialCarouselSlide.VisualTreatment.GRAPHIC_BACKGROUND
        return SocialCarouselSlide.VisualTreatment.TEXT_ONLY
    return treatment


def evaluate_carousel_quality(content):
    if not content.is_carousel:
        return CarouselQualityResult(True, SocialProfile.CarouselVisualMode.STANDARD, 0, 0, 0, 0, 0, 100)

    visual_mode = content.profile.carousel_visual_mode or SocialProfile.CarouselVisualMode.STANDARD
    slides = list(content.carousel_slides.filter(is_active=True).order_by('order', 'id'))
    active = len(slides)
    issues = []
    image_ids = []
    visual_slides = 0
    image_slides = 0
    plain_text = 0

    for slide in slides:
        has_image = _slide_has_image(slide)
        treatment = _slide_visual_treatment(slide)
        if has_image:
            image_slides += 1
            visual_slides += 1
            if _slide_base_image_valid(slide):
                image_ids.append(slide.source_base_image_id)
        elif treatment in VISUAL_TREATMENTS:
            visual_slides += 1
        if treatment == SocialCarouselSlide.VisualTreatment.TEXT_ONLY or ((slide.visual_intent or '').upper() in TEXT_ONLY_LAYOUTS and not has_image):
            plain_text += 1

    if active < 2 or active > 10:
        issues.append('Carrossel precisa ter entre 2 e 10 slides ativos.')
    if visual_mode == SocialProfile.CarouselVisualMode.VISUAL_RICH:
        if visual_slides < active:
            issues.append('Todos os slides precisam de tratamento visual.')
        if plain_text:
            issues.append('Slide texto puro nao atende ao modo Visual premium.')
    if visual_mode == SocialProfile.CarouselVisualMode.IMAGE_DRIVEN:
        if image_slides < active:
            issues.append('Todos os slides precisam de imagem no modo Imagem em todos os slides.')
        if plain_text:
            issues.append('FULL_TEXT nao atende ao modo Imagem em todos os slides.')

    distinct_images = len(set(image_ids))
    score = 100
    if active:
        score = int(((visual_slides / active) * 45) + ((image_slides / active) * 35) + 20)
        if image_ids:
            score -= max(0, len(image_ids) - distinct_images) * 8
    if issues:
        score = min(score, 69)

    return CarouselQualityResult(
        valid=not issues,
        visual_mode=visual_mode,
        active_slides=active,
        visual_slides=visual_slides,
        image_slides=image_slides,
        distinct_images=distinct_images,
        plain_text_slides=plain_text,
        score=max(0, min(100, score)),
        issues=issues,
    )
