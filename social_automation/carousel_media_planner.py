from dataclasses import dataclass

from django.conf import settings

from .carousel_quality import is_premium_editorial
from .media_resolver import STATUS_FULL_TEXT, STATUS_NEEDS_GENERATION, STATUS_SELECTED, STATUS_UNAVAILABLE, resolve_slide_media
from .models import SocialBaseImage, SocialCarouselSlide, SocialCarouselTemplateVariant, SocialProfile


STATUS_GRAPHIC = 'GRAPHIC_BACKGROUND'
STATUS_PENDING = 'PENDING_MEDIA'


@dataclass(frozen=True)
class CarouselMediaPlanItem:
    order: int
    slide: object
    status: str
    image: SocialBaseImage | None
    visual_intent: str
    visual_treatment: str
    media_required: bool
    needs_generation: bool = False
    score: float = 0
    reason: str = ''


@dataclass(frozen=True)
class CarouselMediaPlan:
    visual_mode: str
    image_density: str
    items: list[CarouselMediaPlanItem]

    @property
    def needs_generation_count(self):
        return sum(1 for item in self.items if item.needs_generation)

    @property
    def image_count(self):
        return sum(1 for item in self.items if item.image)

    @property
    def graphic_count(self):
        return sum(1 for item in self.items if item.status == STATUS_GRAPHIC)

    @property
    def pending_count(self):
        return sum(1 for item in self.items if item.status == STATUS_PENDING)


def _normalize_layout(value):
    valid = {choice[0] for choice in SocialCarouselTemplateVariant.LayoutType.choices}
    value = (value or 'AUTO').upper()
    return value if value in valid else SocialCarouselTemplateVariant.LayoutType.AUTO


def _target_image_count(total, mode, density):
    if mode == SocialProfile.CarouselVisualMode.IMAGE_DRIVEN:
        return total
    if density == SocialProfile.CarouselImageDensity.EVERY_SLIDE:
        return total
    if mode == SocialProfile.CarouselVisualMode.STANDARD:
        return 0
    if density == SocialProfile.CarouselImageDensity.LOW:
        return max(1, total // 3)
    if density == SocialProfile.CarouselImageDensity.HIGH:
        return max(1, total - 1)
    return max(1, (total + 1) // 2)


def _slide_role(slide):
    return (getattr(slide, 'slide_role', '') or '').upper()


def _graphic_layout_for(slide, index):
    role = _slide_role(slide)
    if getattr(slide, 'slide_type', '') == SocialCarouselSlide.SlideType.CTA:
        return SocialCarouselTemplateVariant.LayoutType.CTA_CLEAN
    if role == SocialCarouselSlide.SlideRole.BELIEF_BREAK:
        return SocialCarouselTemplateVariant.LayoutType.QUOTE_BIG
    if role == SocialCarouselSlide.SlideRole.VISUAL_PUNCH:
        return SocialCarouselTemplateVariant.LayoutType.IMAGE_PUNCH_MINIMAL
    if role == SocialCarouselSlide.SlideRole.ACTION_STEP:
        return SocialCarouselTemplateVariant.LayoutType.EDITORIAL_SPLIT
    layouts = [
        SocialCarouselTemplateVariant.LayoutType.EDITORIAL_CARD,
        SocialCarouselTemplateVariant.LayoutType.GRAPHIC_LIGHT,
        SocialCarouselTemplateVariant.LayoutType.GRAPHIC_DARK,
        SocialCarouselTemplateVariant.LayoutType.QUOTE_VISUAL,
    ]
    return layouts[index % len(layouts)]


def _image_treatment_for(slide, layout):
    if getattr(slide, 'slide_type', '') == SocialCarouselSlide.SlideType.COVER:
        return SocialCarouselSlide.VisualTreatment.IMAGE_HERO
    if 'SPLIT' in (layout or ''):
        return SocialCarouselSlide.VisualTreatment.IMAGE_SPLIT
    return SocialCarouselSlide.VisualTreatment.IMAGE_BACKGROUND


def _image_layout_for(slide, layout):
    if layout in {
        SocialCarouselTemplateVariant.LayoutType.FULL_TEXT,
        SocialCarouselTemplateVariant.LayoutType.MINIMAL,
        SocialCarouselTemplateVariant.LayoutType.CENTER_CARD,
        SocialCarouselTemplateVariant.LayoutType.AUTO,
    }:
        role = _slide_role(slide)
        if getattr(slide, 'slide_type', '') == SocialCarouselSlide.SlideType.COVER or role == SocialCarouselSlide.SlideRole.HOOK_COVER:
            return SocialCarouselTemplateVariant.LayoutType.COVER_HERO_LEFT
        if role == SocialCarouselSlide.SlideRole.VISUAL_PUNCH:
            return SocialCarouselTemplateVariant.LayoutType.IMAGE_PUNCH_MINIMAL
        if role == SocialCarouselSlide.SlideRole.ACTION_STEP:
            return SocialCarouselTemplateVariant.LayoutType.EDITORIAL_SPLIT
        return SocialCarouselTemplateVariant.LayoutType.IMAGE_BACKGROUND
    return layout


def _graphic_treatment_for(layout):
    if layout in {
        SocialCarouselTemplateVariant.LayoutType.EDITORIAL_CARD,
        SocialCarouselTemplateVariant.LayoutType.CTA_VISUAL,
        SocialCarouselTemplateVariant.LayoutType.CTA_CLEAN,
        SocialCarouselTemplateVariant.LayoutType.CENTER_CARD,
        SocialCarouselTemplateVariant.LayoutType.EDITORIAL_SPLIT,
    }:
        return SocialCarouselSlide.VisualTreatment.EDITORIAL_CARD
    return SocialCarouselSlide.VisualTreatment.GRAPHIC_BACKGROUND


def _policy_allows_generation(profile):
    return bool(
        profile.ai_image_generation_enabled
        and profile.ai_image_policy in {SocialProfile.AIImagePolicy.AI_WHEN_NEEDED, SocialProfile.AIImagePolicy.AI_ALWAYS}
    )


def plan_carousel_media(profile, slides, template, *, remaining_quota=None):
    slide_list = list(slides)
    visual_mode = profile.carousel_visual_mode or SocialProfile.CarouselVisualMode.STANDARD
    editorial_mode = profile.carousel_editorial_mode or SocialProfile.CarouselEditorialMode.STANDARD
    planning_visual_mode = SocialProfile.CarouselVisualMode.VISUAL_RICH if is_premium_editorial(editorial_mode) and visual_mode == SocialProfile.CarouselVisualMode.STANDARD else visual_mode
    density = profile.carousel_image_density or SocialProfile.CarouselImageDensity.AUTO
    target_images = _target_image_count(len(slide_list), planning_visual_mode, density)
    remaining_quota = settings.SOCIAL_AI_IMAGE_MAX_PER_TICK if remaining_quota is None else max(0, remaining_quota)
    image_use_counts = {}
    max_same_uses = profile.effective_carousel_max_same_image_uses
    image_slots_used = 0
    items = []
    aspect_ratio = template.aspect_ratio if template else 'SQUARE'

    for index, slide in enumerate(slide_list, start=1):
        preferred_layout = _normalize_layout(getattr(slide, 'preferred_layout', None) or getattr(slide, 'visual_intent', None))
        manual_image = getattr(slide, 'source_base_image', None)
        role = _slide_role(slide)
        force_image = visual_mode == SocialProfile.CarouselVisualMode.IMAGE_DRIVEN
        role_prefers_image = is_premium_editorial(editorial_mode) and role in {
            SocialCarouselSlide.SlideRole.HOOK_COVER,
            SocialCarouselSlide.SlideRole.VISUAL_PUNCH,
        }
        wants_image = force_image or role_prefers_image or bool(getattr(slide, 'media_required', False)) or image_slots_used < target_images

        if manual_image:
            image_layout = _image_layout_for(slide, preferred_layout)
            image_use_counts[manual_image.id] = image_use_counts.get(manual_image.id, 0) + 1
            image_slots_used += 1
            items.append(
                CarouselMediaPlanItem(
                    order=index,
                    slide=slide,
                    status=STATUS_SELECTED,
                    image=manual_image,
                    visual_intent=image_layout,
                    visual_treatment=_image_treatment_for(slide, image_layout),
                    media_required=True,
                    score=100,
                    reason='Imagem definida manualmente preservada.',
                )
            )
            continue

        if wants_image:
            exclude = {image_id for image_id, uses in image_use_counts.items() if uses >= max_same_uses}
            resolution = resolve_slide_media(
                profile,
                media_intent=getattr(slide, 'media_intent', ''),
                visual_intent=getattr(slide, 'visual_intent', ''),
                preferred_layout=preferred_layout,
                aspect_ratio=aspect_ratio,
                media_required=True,
                exclude_image_ids=exclude,
            )
            if resolution.status == STATUS_SELECTED and resolution.image:
                image_layout = _image_layout_for(slide, preferred_layout)
                image_use_counts[resolution.image.id] = image_use_counts.get(resolution.image.id, 0) + 1
                image_slots_used += 1
                items.append(
                    CarouselMediaPlanItem(
                        order=index,
                        slide=slide,
                        status=STATUS_SELECTED,
                        image=resolution.image,
                        visual_intent=image_layout,
                        visual_treatment=_image_treatment_for(slide, image_layout),
                        media_required=True,
                        score=resolution.score,
                        reason=resolution.reason,
                    )
                )
                continue
            if resolution.status == STATUS_NEEDS_GENERATION and _policy_allows_generation(profile) and remaining_quota > 0:
                image_layout = _image_layout_for(slide, preferred_layout)
                remaining_quota -= 1
                image_slots_used += 1
                items.append(
                    CarouselMediaPlanItem(
                        order=index,
                        slide=slide,
                        status=STATUS_NEEDS_GENERATION,
                        image=None,
                        visual_intent=image_layout,
                        visual_treatment=_image_treatment_for(slide, image_layout),
                        media_required=True,
                        needs_generation=True,
                        score=resolution.score,
                        reason=resolution.reason,
                    )
                )
                continue
            if force_image:
                items.append(
                    CarouselMediaPlanItem(
                        order=index,
                        slide=slide,
                        status=STATUS_PENDING,
                        image=None,
                        visual_intent=preferred_layout,
                        visual_treatment=SocialCarouselSlide.VisualTreatment.TEXT_ONLY,
                        media_required=True,
                        score=resolution.score,
                        reason=resolution.reason or 'Imagem obrigatoria indisponivel.',
                    )
                )
                continue

        if planning_visual_mode == SocialProfile.CarouselVisualMode.VISUAL_RICH:
            graphic_layout = _graphic_layout_for(slide, index)
            items.append(
                CarouselMediaPlanItem(
                    order=index,
                    slide=slide,
                    status=STATUS_GRAPHIC,
                    image=None,
                    visual_intent=graphic_layout,
                    visual_treatment=_graphic_treatment_for(graphic_layout),
                    media_required=False,
                    reason='Tratamento grafico atende ao modo visual premium.',
                )
            )
            continue

        items.append(
            CarouselMediaPlanItem(
                order=index,
                slide=slide,
                status=STATUS_FULL_TEXT if not wants_image else STATUS_UNAVAILABLE,
                image=None,
                visual_intent=SocialCarouselTemplateVariant.LayoutType.FULL_TEXT,
                visual_treatment=SocialCarouselSlide.VisualTreatment.TEXT_ONLY,
                media_required=bool(getattr(slide, 'media_required', False)),
                reason='Slide textual permitido pelo modo padrao.',
            )
        )

    return CarouselMediaPlan(visual_mode=visual_mode, image_density=density, items=items)
