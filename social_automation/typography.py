import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont


logger = logging.getLogger(__name__)


FONT_FAMILY_CHOICES = [
    ('SYSTEM_BOLD', 'Padrao do sistema'),
    ('SYSTEM_REGULAR', 'Sistema regular'),
    ('SANS_BOLD', 'Sans negrito'),
    ('MODERN', 'Moderna'),
    ('BOLD_SOCIAL', 'Impacto'),
    ('CONDENSED', 'Condensada'),
    ('ROUNDED', 'Arredondada'),
    ('EDITORIAL', 'Editorial'),
]

FONT_WEIGHT_CHOICES = [
    (400, 'Regular'),
    (600, 'Seminegrito'),
    (700, 'Negrito'),
    (800, 'Extra negrito'),
]

FONT_SCALE_CHOICES = [
    ('SMALL', 'Pequena'),
    ('NORMAL', 'Normal'),
    ('LARGE', 'Grande'),
    ('XLARGE', 'Muito grande'),
]

LINE_SPACING_CHOICES = [
    ('COMPACT', 'Compacto'),
    ('NORMAL', 'Normal'),
    ('WIDE', 'Amplo'),
]

TEXT_OUTLINE_CHOICES = [
    ('AUTO', 'Padrao do sistema'),
    ('NONE', 'Sem contorno'),
    ('SOFT', 'Suave'),
    ('MEDIUM', 'Medio'),
    ('STRONG', 'Forte'),
]

TEXT_SHADOW_CHOICES = [
    ('AUTO', 'Padrao do sistema'),
    ('NONE', 'Sem sombra'),
    ('SOFT', 'Suave'),
    ('MEDIUM', 'Media'),
]

FONT_SCALE_FACTORS = {
    'SMALL': 0.90,
    'NORMAL': 1.00,
    'LARGE': 1.10,
    'XLARGE': 1.20,
}

LINE_SPACING_FACTORS = {
    'COMPACT': 0.74,
    'NORMAL': 1.00,
    'WIDE': 1.28,
}

_REGULAR = [
    'C:/Windows/Fonts/arial.ttf',
    'C:/Windows/Fonts/segoeui.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
]

_BOLD = [
    'C:/Windows/Fonts/arialbd.ttf',
    'C:/Windows/Fonts/segoeuib.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
]

_CONDENSED = [
    'C:/Windows/Fonts/arialn.ttf',
    'C:/Windows/Fonts/arialnb.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf',
]

_IMPACT = [
    'C:/Windows/Fonts/impact.ttf',
    'C:/Windows/Fonts/ariblk.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf',
    '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
]

_SERIF = [
    'C:/Windows/Fonts/georgia.ttf',
    'C:/Windows/Fonts/georgiab.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
]

FONT_REGISTRY = {
    'SYSTEM_BOLD': {400: _REGULAR, 600: _BOLD, 700: _BOLD, 800: _BOLD},
    'SYSTEM_REGULAR': {400: _REGULAR, 600: _BOLD, 700: _BOLD, 800: _BOLD},
    'SANS_BOLD': {400: _REGULAR, 600: _BOLD, 700: _BOLD, 800: _BOLD},
    'MODERN': {400: _REGULAR, 600: _BOLD, 700: _BOLD, 800: _BOLD},
    'BOLD_SOCIAL': {400: _IMPACT, 600: _IMPACT, 700: _IMPACT, 800: _IMPACT},
    'CONDENSED': {400: _CONDENSED, 600: _CONDENSED, 700: _CONDENSED, 800: _CONDENSED},
    'ROUNDED': {400: _REGULAR, 600: _BOLD, 700: _BOLD, 800: _BOLD},
    'EDITORIAL': {400: _SERIF, 600: _SERIF, 700: _SERIF, 800: _SERIF},
}


@dataclass(frozen=True)
class TypographyConfig:
    family: str = 'SYSTEM_BOLD'
    weight: int = 700
    scale: float = 1.0
    line_spacing: float = 1.0
    outline_width: int = 0
    outline_alpha: int = 0
    shadow_offset: tuple[int, int] = (0, 0)
    shadow_alpha: int = 0

    def fingerprint_payload(self):
        return {
            'family': self.family,
            'weight': self.weight,
            'scale': self.scale,
            'line_spacing': self.line_spacing,
            'outline_width': self.outline_width,
            'shadow_offset': self.shadow_offset,
            'shadow_alpha': self.shadow_alpha,
        }


def resolve_font_path(family='SYSTEM_BOLD', weight=700):
    family = family if family in FONT_REGISTRY else 'SYSTEM_BOLD'
    try:
        weight = int(weight or 700)
    except (TypeError, ValueError):
        weight = 700
    available_weights = sorted(FONT_REGISTRY[family])
    nearest_weight = min(available_weights, key=lambda item: abs(item - weight))
    candidates = [*FONT_REGISTRY[family].get(nearest_weight, []), *_BOLD, *_REGULAR]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    logger.warning('social_typography_font_missing family=%s weight=%s fallback=pil_default', family, weight)
    return None


def load_font(size, *, family='SYSTEM_BOLD', weight=700):
    path = resolve_font_path(family, weight)
    if path:
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception as exc:
            logger.warning('social_typography_font_load_failed family=%s path=%s error=%s', family, path, type(exc).__name__)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def typography_for_identity(identity, *, context='image', weight=None):
    family = getattr(identity, 'font_primary', None) or 'SYSTEM_BOLD'
    resolved_weight = weight or getattr(identity, 'font_weight_title', None) or 700
    scale = FONT_SCALE_FACTORS.get(getattr(identity, 'font_scale', None) or 'NORMAL', 1.0)
    line_spacing = LINE_SPACING_FACTORS.get(getattr(identity, 'line_spacing', None) or 'NORMAL', 1.0)
    outline = getattr(identity, 'text_outline', None) or 'AUTO'
    shadow = getattr(identity, 'text_shadow', None) or 'AUTO'

    if outline == 'AUTO':
        outline = 'MEDIUM' if context in {'image', 'reel'} else 'NONE'
    if shadow == 'AUTO':
        shadow = 'MEDIUM' if context in {'image', 'reel'} else 'NONE'

    outline_widths = {'NONE': 0, 'SOFT': 1, 'MEDIUM': 3, 'STRONG': 5}
    outline_alphas = {'NONE': 0, 'SOFT': 120, 'MEDIUM': 170, 'STRONG': 220}
    shadow_specs = {
        'NONE': ((0, 0), 0),
        'SOFT': ((2, 3), 100),
        'MEDIUM': ((3, 4), 150),
    }
    shadow_offset, shadow_alpha = shadow_specs.get(shadow, ((0, 0), 0))
    return TypographyConfig(
        family=family,
        weight=int(resolved_weight),
        scale=scale,
        line_spacing=line_spacing,
        outline_width=outline_widths.get(outline, 0),
        outline_alpha=outline_alphas.get(outline, 0),
        shadow_offset=shadow_offset,
        shadow_alpha=shadow_alpha,
    )
