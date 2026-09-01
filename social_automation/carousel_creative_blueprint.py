from dataclasses import asdict, dataclass, field
import hashlib
import json

from django.conf import settings

from .models import SocialCarouselSlide, SocialProfile


COMPOSITION_TYPES = [choice[0] for choice in SocialCarouselSlide.CompositionType.choices]


@dataclass(frozen=True)
class CarouselIdea:
    idea_id: str
    hook: str
    concept: str
    promise: str
    audience_angle: str
    editorial_angle: str
    suggested_slide_count: int
    creative_direction: str
    reason: str

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class IdeaSelection:
    selected_idea_id: str
    reason: str
    confidence: int

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class SlideCreativePlan:
    order: int
    role: str
    title: str
    body: str
    composition_type: str
    visual_goal: str
    image_strategy: str = 'AUTO'
    image_prompt: str = ''
    text_emphasis: list[str] = field(default_factory=list)
    creative_notes: str = ''
    continuity_notes: str = ''

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CreativeDirection:
    concept_name: str
    visual_story: str
    design_language: str
    color_strategy: str
    typography_strategy: str
    image_strategy: str
    rhythm_strategy: str
    brand_consistency: str
    slides: list[SlideCreativePlan]

    def as_dict(self):
        data = asdict(self)
        data['slides'] = [slide.as_dict() for slide in self.slides]
        return data


def normalize_composition_type(value):
    value = (value or SocialCarouselSlide.CompositionType.AUTO).upper()
    return value if value in COMPOSITION_TYPES else SocialCarouselSlide.CompositionType.AUTO


def carousel_generation_mode(profile):
    return getattr(profile, 'carousel_generation_mode', SocialProfile.CarouselGenerationMode.SYSTEM_COMPOSED) or SocialProfile.CarouselGenerationMode.SYSTEM_COMPOSED


def is_ai_finished(profile):
    return carousel_generation_mode(profile) == SocialProfile.CarouselGenerationMode.AI_FINISHED


def is_ai_directed(profile):
    return carousel_generation_mode(profile) == SocialProfile.CarouselGenerationMode.AI_DIRECTED


def slide_text_snapshot(slide):
    return {
        'title': slide.title or '',
        'body': slide.body or '',
        'slide_role': slide.slide_role or '',
        'slide_type': slide.slide_type or '',
    }


def composition_fingerprint(profile, slide, creative_plan, *, aspect_ratio='SQUARE', brand_mode='SYSTEM_BRAND_OVERLAY'):
    payload = {
        'profile_id': profile.id,
        'identity': _identity_payload(profile),
        'slide': slide_text_snapshot(slide),
        'creative_plan': creative_plan or {},
        'aspect_ratio': aspect_ratio,
        'brand_mode': brand_mode,
        'model': getattr(settings, 'OPENAI_SOCIAL_IMAGE_MODEL', ''),
        'quality': getattr(settings, 'OPENAI_SOCIAL_IMAGE_QUALITY', ''),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _identity_payload(profile):
    identity = profile.visual_identities.filter(active=True, is_default=True).first()
    if not identity:
        return {'profile': profile.username, 'brand': profile.nome}
    return {
        'profile': profile.username,
        'brand': identity.display_brand_name,
        'primary': identity.primary_color,
        'secondary': identity.secondary_color,
        'accent': identity.accent_color,
        'font_primary': identity.font_primary,
        'font_secondary': identity.font_secondary,
        'logo': bool(identity.brand_logo),
        'show_brand': identity.show_brand_name,
        'show_slide_number': identity.show_slide_number,
    }
