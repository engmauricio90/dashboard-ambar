from dataclasses import dataclass
from hashlib import sha256

from PIL import Image, ImageOps, ImageStat

from .models import SocialBaseImage, SocialCarouselTemplateVariant, SocialVisualIdentity


class VisualCompositionError(Exception):
    pass


@dataclass(frozen=True)
class LayoutCandidate:
    name: str
    text_box: tuple[float, float, float, float]
    image_box: tuple[float, float, float, float] | None = None
    align: str = 'left'
    overlay: str = 'AUTO'


@dataclass(frozen=True)
class CompositionDecision:
    variant_name: str
    layout_type: str
    text_box: tuple[int, int, int, int]
    align: str
    text_color: tuple[int, int, int]
    accent_color: tuple[int, int, int]
    overlay_type: str
    overlay_strength: int
    source_base_image: SocialBaseImage | None
    use_source_photo: bool
    metadata: dict


LAYOUTS = {
    'HERO_LEFT': LayoutCandidate('HERO_LEFT', (0.06, 0.18, 0.43, 0.62), align='left', overlay='GRADIENT_LEFT'),
    'HERO_RIGHT': LayoutCandidate('HERO_RIGHT', (0.51, 0.18, 0.43, 0.62), align='left', overlay='GRADIENT_RIGHT'),
    'TEXT_TOP': LayoutCandidate('TEXT_TOP', (0.08, 0.08, 0.84, 0.35), align='center', overlay='GRADIENT_TOP'),
    'TEXT_BOTTOM': LayoutCandidate('TEXT_BOTTOM', (0.08, 0.58, 0.84, 0.32), align='center', overlay='GRADIENT_BOTTOM'),
    'CENTER_CARD': LayoutCandidate('CENTER_CARD', (0.16, 0.25, 0.68, 0.50), align='center', overlay='DARK'),
    'SPLIT_LEFT': LayoutCandidate('SPLIT_LEFT', (0.06, 0.16, 0.42, 0.68), (0.52, 0.10, 0.42, 0.80), align='left', overlay='GRADIENT_LEFT'),
    'SPLIT_RIGHT': LayoutCandidate('SPLIT_RIGHT', (0.52, 0.16, 0.42, 0.68), (0.06, 0.10, 0.42, 0.80), align='left', overlay='GRADIENT_RIGHT'),
    'MINIMAL': LayoutCandidate('MINIMAL', (0.12, 0.62, 0.76, 0.24), align='center', overlay='GRADIENT_BOTTOM'),
    'FULL_TEXT': LayoutCandidate('FULL_TEXT', (0.10, 0.18, 0.80, 0.62), align='center', overlay='NONE'),
    'EDITORIAL_CARD': LayoutCandidate('EDITORIAL_CARD', (0.12, 0.20, 0.76, 0.56), align='center', overlay='NONE'),
    'IMAGE_BACKGROUND': LayoutCandidate('IMAGE_BACKGROUND', (0.10, 0.18, 0.80, 0.56), align='center', overlay='DARK'),
    'IMAGE_BLUR_TEXT': LayoutCandidate('IMAGE_BLUR_TEXT', (0.13, 0.22, 0.74, 0.52), align='center', overlay='DARK'),
    'QUOTE_VISUAL': LayoutCandidate('QUOTE_VISUAL', (0.14, 0.24, 0.72, 0.48), align='center', overlay='NONE'),
    'GRAPHIC_DARK': LayoutCandidate('GRAPHIC_DARK', (0.11, 0.21, 0.78, 0.54), align='center', overlay='NONE'),
    'GRAPHIC_LIGHT': LayoutCandidate('GRAPHIC_LIGHT', (0.11, 0.21, 0.78, 0.54), align='center', overlay='NONE'),
    'CTA_VISUAL': LayoutCandidate('CTA_VISUAL', (0.12, 0.28, 0.76, 0.40), align='center', overlay='NONE'),
}

GRAPHIC_ONLY_LAYOUTS = {'EDITORIAL_CARD', 'QUOTE_VISUAL', 'GRAPHIC_DARK', 'GRAPHIC_LIGHT', 'CTA_VISUAL'}

DEFAULT_SEQUENCE = {
    'COVER': ['HERO_LEFT', 'HERO_RIGHT', 'TEXT_TOP', 'CENTER_CARD'],
    'CONTENT': ['TEXT_TOP', 'SPLIT_RIGHT', 'SPLIT_LEFT', 'CENTER_CARD', 'TEXT_BOTTOM'],
    'CTA': ['MINIMAL', 'CENTER_CARD', 'TEXT_BOTTOM'],
}


def _hex_to_rgb(value, default):
    value = (value or '').strip().lstrip('#')
    if len(value) != 6:
        return default
    try:
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return default


def visual_identity_for_profile(profile):
    identity = profile.visual_identities.filter(active=True, is_default=True).first() or profile.visual_identities.filter(active=True).first()
    if identity:
        return identity
    return SocialVisualIdentity(profile=profile, name='Identidade padrao', brand_name=profile.nome)


def normalized_to_pixels(box, canvas_size):
    width, height = canvas_size
    x, y, box_width, box_height = box
    return (
        round(width * x),
        round(height * y),
        round(width * box_width),
        round(height * box_height),
    )


def _intersection_area(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0
    return (right - left) * (bottom - top)


def protected_regions_for_image(base_image):
    if not base_image:
        return []
    return [
        (float(region.x), float(region.y), float(region.width), float(region.height))
        for region in base_image.protected_regions.filter(active=True)
    ]


def _candidate_overlaps(candidate, protected_regions):
    text_box = candidate.text_box
    text_area = max(text_box[2] * text_box[3], 0.001)
    for region in protected_regions:
        if _intersection_area(text_box, region) / text_area > 0.02:
            return True
    return False


def _layout_names_for_slide(slide, variants):
    explicit = slide.visual_intent
    if explicit and explicit != SocialCarouselTemplateVariant.LayoutType.AUTO:
        return [explicit]
    names = [variant.layout_type for variant in variants if variant.layout_type != SocialCarouselTemplateVariant.LayoutType.AUTO]
    if names:
        return names
    return DEFAULT_SEQUENCE.get(slide.slide_type, DEFAULT_SEQUENCE['CONTENT'])


def _deterministic_order(items, seed):
    return sorted(items, key=lambda item: sha256(f'{seed}:{item}'.encode()).hexdigest())


def _variant_for_layout(layout_name, variants):
    for variant in variants:
        if variant.layout_type == layout_name:
            return variant
    return None


def _select_source_base_image(slide, layout_name):
    if slide.source_base_image_id:
        if slide.source_base_image.profile_id == slide.content.profile_id:
            return slide.source_base_image
        return None
    if slide.content.base_image_id:
        return slide.content.base_image
    preferred_zone = {
        'HERO_LEFT': SocialBaseImage.TextSafeZone.LEFT,
        'SPLIT_LEFT': SocialBaseImage.TextSafeZone.LEFT,
        'HERO_RIGHT': SocialBaseImage.TextSafeZone.RIGHT,
        'SPLIT_RIGHT': SocialBaseImage.TextSafeZone.RIGHT,
        'TEXT_TOP': SocialBaseImage.TextSafeZone.TOP,
        'TEXT_BOTTOM': SocialBaseImage.TextSafeZone.BOTTOM,
    }.get(layout_name)
    queryset = slide.content.profile.base_images.filter(ativa=True)
    if preferred_zone:
        match = queryset.filter(text_safe_zone=preferred_zone).order_by('vezes_usada', 'ultima_utilizacao', 'id').first()
        if match:
            return match
    subject_opposite = {
        'HERO_LEFT': [SocialBaseImage.SubjectPosition.RIGHT, SocialBaseImage.SubjectPosition.BOTTOM_RIGHT],
        'SPLIT_LEFT': [SocialBaseImage.SubjectPosition.RIGHT, SocialBaseImage.SubjectPosition.BOTTOM_RIGHT],
        'HERO_RIGHT': [SocialBaseImage.SubjectPosition.LEFT, SocialBaseImage.SubjectPosition.BOTTOM_LEFT],
        'SPLIT_RIGHT': [SocialBaseImage.SubjectPosition.LEFT, SocialBaseImage.SubjectPosition.BOTTOM_LEFT],
    }.get(layout_name, [])
    if subject_opposite:
        match = queryset.filter(subject_position__in=subject_opposite).order_by('vezes_usada', 'ultima_utilizacao', 'id').first()
        if match:
            return match
    return queryset.order_by('vezes_usada', 'ultima_utilizacao', 'id').first()


def _average_luminance(base_image, text_box, canvas_size):
    if not base_image or not base_image.arquivo:
        return None
    try:
        with base_image.arquivo.open('rb') as arquivo:
            image = Image.open(arquivo)
            image = ImageOps.exif_transpose(image)
            image = ImageOps.fit(image, canvas_size, method=Image.Resampling.LANCZOS).convert('RGB')
            x, y, width, height = normalized_to_pixels(text_box, canvas_size)
            crop = image.crop((x, y, x + width, y + height)).resize((1, 1))
            r, g, b = ImageStat.Stat(crop).mean
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
    except Exception:
        return None


def _score_candidate(candidate, protected_regions, source_base_image):
    if _candidate_overlaps(candidate, protected_regions):
        return None
    score = 100
    area = candidate.text_box[2] * candidate.text_box[3]
    score += round(area * 40)
    safe_zone = getattr(source_base_image, 'text_safe_zone', None)
    if safe_zone and safe_zone != SocialBaseImage.TextSafeZone.AUTO:
        if safe_zone in candidate.name.lower():
            score += 25
        if safe_zone == SocialBaseImage.TextSafeZone.FULL:
            score += 8
    return score


def _choose_text_color(identity, slide, luminance):
    if slide.text_color_override:
        return _hex_to_rgb(slide.text_color_override, (255, 255, 255))
    if luminance is None:
        return _hex_to_rgb(identity.light_text_color, (255, 255, 255))
    if luminance > 148:
        return _hex_to_rgb(identity.dark_text_color, (17, 24, 39))
    return _hex_to_rgb(identity.light_text_color, (255, 255, 255))


def _choose_overlay(variant, slide, candidate, luminance, identity):
    override = slide.overlay_override
    if override:
        overlay_type = override
    elif variant and variant.overlay_type != SocialCarouselTemplateVariant.OverlayType.AUTO:
        overlay_type = variant.overlay_type
    elif luminance is None:
        overlay_type = SocialCarouselTemplateVariant.OverlayType.NONE
    elif luminance > 178:
        overlay_type = candidate.overlay if candidate.overlay.startswith('GRADIENT') else SocialCarouselTemplateVariant.OverlayType.DARK
    elif luminance < 70:
        overlay_type = SocialCarouselTemplateVariant.OverlayType.LIGHT
    else:
        overlay_type = candidate.overlay
    strength = variant.overlay_strength if variant else identity.default_overlay_strength
    if overlay_type == SocialCarouselTemplateVariant.OverlayType.NONE:
        strength = 0
    return overlay_type, min(max(int(strength), 0), 90)


def compose_carousel_slide(slide, template, total_slides):
    identity = visual_identity_for_profile(slide.content.profile)
    variants = list(template.variants.filter(active=True))
    compatible_variants = [variant for variant in variants if variant.allows_slide_type(slide.slide_type)]
    seed = f'{slide.content.profile_id}:{slide.content_id}:{slide.order}:{slide.slide_type}'
    layout_names = _deterministic_order(_layout_names_for_slide(slide, compatible_variants), seed)

    best = None
    for layout_name in layout_names:
        candidate = LAYOUTS.get(layout_name) or LAYOUTS['FULL_TEXT']
        variant = slide.variant if slide.variant_id and slide.variant.allows_slide_type(slide.slide_type) else _variant_for_layout(layout_name, compatible_variants)
        source_base_image = None if layout_name in GRAPHIC_ONLY_LAYOUTS or layout_name == 'FULL_TEXT' else _select_source_base_image(slide, layout_name)
        regions = protected_regions_for_image(source_base_image)
        score = _score_candidate(candidate, regions, source_base_image)
        if score is None:
            continue
        if best is None or score > best[0]:
            best = (score, candidate, variant, source_base_image, regions)

    if best is None and 'FULL_TEXT' not in layout_names:
        candidate = LAYOUTS['FULL_TEXT']
        variant = _variant_for_layout('FULL_TEXT', compatible_variants)
        score = _score_candidate(candidate, [], None)
        best = (score, candidate, variant, None, [])

    if not best:
        raise VisualCompositionError('Nenhum layout seguro disponivel para o slide.')

    _, candidate, variant, source_base_image, regions = best
    canvas_size = template.canvas_size
    luminance = _average_luminance(source_base_image, candidate.text_box, canvas_size)
    text_color = _choose_text_color(identity, slide, luminance)
    overlay_type, overlay_strength = _choose_overlay(variant, slide, candidate, luminance, identity)
    variant_name = variant.name if variant else f'AUTO {candidate.name}'
    metadata = {
        'variant': variant_name,
        'layout_type': candidate.name,
        'text_zone': candidate.text_box,
        'text_box_px': normalized_to_pixels(candidate.text_box, canvas_size),
        'text_color': text_color,
        'overlay': overlay_type,
        'overlay_strength': overlay_strength,
        'source_base_image_id': source_base_image.id if source_base_image else None,
        'brand_name': identity.display_brand_name,
        'protected_regions': regions,
        'luminance': luminance,
        'total_slides': total_slides,
    }
    return CompositionDecision(
        variant_name=variant_name,
        layout_type=candidate.name,
        text_box=normalized_to_pixels(candidate.text_box, canvas_size),
        align=variant.title_alignment if variant else candidate.align,
        text_color=text_color,
        accent_color=_hex_to_rgb(identity.accent_color, (34, 197, 94)),
        overlay_type=overlay_type,
        overlay_strength=overlay_strength,
        source_base_image=source_base_image,
        use_source_photo=bool(source_base_image and candidate.name not in GRAPHIC_ONLY_LAYOUTS and candidate.name != 'FULL_TEXT'),
        metadata=metadata,
    )


def analyze_social_image(image):
    return {
        'protected_regions': [],
        'focal_point': {'x': 0.5, 'y': 0.5},
        'brightness': None,
        'candidate_text_zones': list(LAYOUTS.keys()),
    }
