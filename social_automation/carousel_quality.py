from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
import unicodedata

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
PREMIUM_EDITORIAL_MODES = {'SOCIAL_PREMIUM', 'PREMIUM_INSTAGRAM'}
PREMIUM_BLUEPRINT_ATTEMPTS = 2
SIMILARITY_THRESHOLD = 0.86
LAYOUT_REPEAT_LIMIT = 4

EDITORIAL_ROLE_ORDER = [
    'HOOK_COVER',
    'BELIEF_BREAK',
    'CONTEXT',
    'EXPLANATION',
    'INSIGHT',
    'VISUAL_PUNCH',
    'ACTION_STEP',
    'PROOF',
    'CONCLUSION',
    'CTA',
]


@dataclass(frozen=True)
class SlideTextBudget:
    max_title_words: int
    max_body_words: int
    max_total_chars: int
    max_lines: int


@dataclass(frozen=True)
class EditorialQualityResult:
    valid: bool
    editorial_mode: str
    score: int
    issues: list[str] = field(default_factory=list)
    role_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class LayoutRhythmResult:
    valid: bool
    score: int
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CarouselQualityResult:
    valid: bool
    visual_mode: str
    editorial_mode: str
    active_slides: int
    visual_slides: int
    image_slides: int
    distinct_images: int
    plain_text_slides: int
    score: int
    visual_score: int
    editorial_score: int
    visual_valid: bool
    editorial_valid: bool
    issues: list[str] = field(default_factory=list)
    visual_issues: list[str] = field(default_factory=list)
    editorial_issues: list[str] = field(default_factory=list)


TEXT_BUDGETS = {
    'HOOK_COVER': SlideTextBudget(max_title_words=8, max_body_words=12, max_total_chars=105, max_lines=3),
    'BELIEF_BREAK': SlideTextBudget(max_title_words=10, max_body_words=18, max_total_chars=135, max_lines=3),
    'CONTEXT': SlideTextBudget(max_title_words=11, max_body_words=28, max_total_chars=185, max_lines=4),
    'EXPLANATION': SlideTextBudget(max_title_words=12, max_body_words=34, max_total_chars=225, max_lines=5),
    'INSIGHT': SlideTextBudget(max_title_words=10, max_body_words=24, max_total_chars=165, max_lines=4),
    'VISUAL_PUNCH': SlideTextBudget(max_title_words=6, max_body_words=10, max_total_chars=80, max_lines=2),
    'ACTION_STEP': SlideTextBudget(max_title_words=9, max_body_words=20, max_total_chars=150, max_lines=3),
    'PROOF': SlideTextBudget(max_title_words=10, max_body_words=24, max_total_chars=170, max_lines=4),
    'CONCLUSION': SlideTextBudget(max_title_words=9, max_body_words=18, max_total_chars=135, max_lines=3),
    'CTA': SlideTextBudget(max_title_words=8, max_body_words=14, max_total_chars=120, max_lines=3),
}
STANDARD_TEXT_BUDGET = SlideTextBudget(max_title_words=30, max_body_words=90, max_total_chars=650, max_lines=9)


def is_premium_editorial(mode):
    return (mode or '').upper() in PREMIUM_EDITORIAL_MODES


def get_slide_text_budget(editorial_mode, editorial_role, layout=None):
    if not is_premium_editorial(editorial_mode):
        return STANDARD_TEXT_BUDGET
    role = (editorial_role or SocialCarouselSlide.SlideRole.EXPLANATION).upper()
    budget = TEXT_BUDGETS.get(role, TEXT_BUDGETS['EXPLANATION'])
    layout = (layout or '').upper()
    if layout in {'FULL_TEXT', 'MINIMAL'} and role not in {'HOOK_COVER', 'VISUAL_PUNCH', 'CTA'}:
        return SlideTextBudget(
            max_title_words=budget.max_title_words,
            max_body_words=min(budget.max_body_words + 8, STANDARD_TEXT_BUDGET.max_body_words),
            max_total_chars=min(budget.max_total_chars + 45, STANDARD_TEXT_BUDGET.max_total_chars),
            max_lines=min(budget.max_lines + 1, STANDARD_TEXT_BUDGET.max_lines),
        )
    return budget


def default_editorial_role(slide_type, index, slide_count):
    slide_type = (slide_type or '').upper()
    if slide_type == SocialCarouselSlide.SlideType.COVER or index == 0:
        return SocialCarouselSlide.SlideRole.HOOK_COVER
    if slide_type == SocialCarouselSlide.SlideType.CTA or index >= slide_count - 1:
        return SocialCarouselSlide.SlideRole.CTA
    sequence = ['BELIEF_BREAK', 'CONTEXT', 'EXPLANATION', 'INSIGHT', 'VISUAL_PUNCH', 'ACTION_STEP', 'PROOF', 'CONCLUSION']
    return sequence[(max(index, 1) - 1) % len(sequence)]


def evaluate_blueprint_editorial_quality(profile, blueprint):
    mode = getattr(profile, 'carousel_editorial_mode', SocialProfile.CarouselEditorialMode.STANDARD) or SocialProfile.CarouselEditorialMode.STANDARD
    slides = list(getattr(blueprint, 'slides', []) or [])
    return _evaluate_editorial_quality(slides, mode, cta_enabled=getattr(profile, 'carousel_cta_enabled', True))


def evaluate_layout_rhythm(slides, *, editorial_mode=None):
    if not is_premium_editorial(editorial_mode):
        return LayoutRhythmResult(True, 100)

    sequence = []
    issues = []
    for slide in slides:
        layout = _slide_layout(slide)
        treatment = _slide_visual_treatment(slide) if isinstance(slide, SocialCarouselSlide) else (getattr(slide, 'visual_treatment', '') or '')
        sequence.append((layout, treatment))

    repeats = 1
    for index in range(1, len(sequence)):
        if sequence[index] == sequence[index - 1]:
            repeats += 1
            if repeats >= LAYOUT_REPEAT_LIMIT:
                issues.append('Sequencia longa com o mesmo layout/tratamento visual.')
                break
        else:
            repeats = 1

    distinct_layouts = len({layout for layout, _ in sequence if layout})
    if len(sequence) >= 5 and distinct_layouts < 3:
        issues.append('Carrossel premium precisa de mais variedade de layouts.')

    cover_layout = sequence[0][0] if sequence else ''
    if len(sequence) >= 3 and cover_layout and cover_layout == sequence[1][0] == sequence[2][0]:
        issues.append('Capa premium esta visualmente parecida demais com os slides internos.')

    score = 100 - len(issues) * 18
    return LayoutRhythmResult(not issues, max(0, min(100, score)), issues)


def automation_quality_ready(content):
    if not content.is_carousel:
        return content.final_media_ready
    return evaluate_carousel_quality(content).valid


def evaluate_carousel_quality(content):
    if not content.is_carousel:
        return CarouselQualityResult(
            valid=True,
            visual_mode=SocialProfile.CarouselVisualMode.STANDARD,
            editorial_mode=SocialProfile.CarouselEditorialMode.STANDARD,
            active_slides=0,
            visual_slides=0,
            image_slides=0,
            distinct_images=0,
            plain_text_slides=0,
            score=100,
            visual_score=100,
            editorial_score=100,
            visual_valid=True,
            editorial_valid=True,
        )

    visual_mode = content.profile.carousel_visual_mode or SocialProfile.CarouselVisualMode.STANDARD
    editorial_mode = content.profile.carousel_editorial_mode or SocialProfile.CarouselEditorialMode.STANDARD
    slides = list(content.carousel_slides.filter(is_active=True).order_by('order', 'id'))
    visual = _evaluate_visual_quality(slides, visual_mode)
    editorial = _evaluate_editorial_quality(slides, editorial_mode, cta_enabled=content.profile.carousel_cta_enabled)
    issues = [*visual.issues, *editorial.issues]
    valid = visual.valid and editorial.valid
    score = min(visual.score, editorial.score)
    if issues:
        score = min(score, 69)

    return CarouselQualityResult(
        valid=valid,
        visual_mode=visual_mode,
        editorial_mode=editorial_mode,
        active_slides=visual.active_slides,
        visual_slides=visual.visual_slides,
        image_slides=visual.image_slides,
        distinct_images=visual.distinct_images,
        plain_text_slides=visual.plain_text_slides,
        score=max(0, min(100, score)),
        visual_score=visual.score,
        editorial_score=editorial.score,
        visual_valid=visual.valid,
        editorial_valid=editorial.valid,
        issues=issues,
        visual_issues=visual.issues,
        editorial_issues=editorial.issues,
    )


@dataclass(frozen=True)
class _VisualQuality:
    valid: bool
    active_slides: int
    visual_slides: int
    image_slides: int
    distinct_images: int
    plain_text_slides: int
    score: int
    issues: list[str]


def _evaluate_visual_quality(slides, visual_mode):
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
        if treatment == SocialCarouselSlide.VisualTreatment.TEXT_ONLY or (_slide_layout(slide) in TEXT_ONLY_LAYOUTS and not has_image):
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
    return _VisualQuality(
        valid=not issues,
        active_slides=active,
        visual_slides=visual_slides,
        image_slides=image_slides,
        distinct_images=distinct_images,
        plain_text_slides=plain_text,
        score=max(0, min(100, score)),
        issues=issues,
    )


def _evaluate_editorial_quality(slides, editorial_mode, *, cta_enabled=True):
    if not is_premium_editorial(editorial_mode):
        return EditorialQualityResult(True, editorial_mode, 100, [], _role_counts(slides))

    issues = []
    role_counts = _role_counts(slides)
    active = len(slides)

    if active < 2 or active > 10:
        issues.append('Carrossel premium precisa ter entre 2 e 10 slides ativos.')
    if slides:
        first = slides[0]
        if _slide_role(first) != SocialCarouselSlide.SlideRole.HOOK_COVER or _slide_type(first) != SocialCarouselSlide.SlideType.COVER:
            issues.append('Capa premium precisa usar COVER + HOOK_COVER.')

    for index, slide in enumerate(slides, start=1):
        role = _slide_role(slide)
        slide_type = _slide_type(slide)
        if role not in EDITORIAL_ROLE_ORDER:
            issues.append(f'Slide {index}: papel editorial invalido.')
        if slide_type == SocialCarouselSlide.SlideType.COVER and role != SocialCarouselSlide.SlideRole.HOOK_COVER:
            issues.append(f'Slide {index}: capa deve usar HOOK_COVER.')
        if slide_type == SocialCarouselSlide.SlideType.CTA and role != SocialCarouselSlide.SlideRole.CTA:
            issues.append(f'Slide {index}: CTA deve usar papel CTA.')
        issues.extend(_text_budget_issues(slide, index, editorial_mode))

    if active >= 5 and len([role for role in role_counts if role]) < 4:
        issues.append('Progressao premium precisa de mais papeis editoriais distintos.')
    if cta_enabled and slides and not any(_slide_role(slide) == SocialCarouselSlide.SlideRole.CTA for slide in slides):
        issues.append('CTA habilitado no perfil, mas o carrossel nao possui slide CTA.')
    issues.extend(_repetition_issues(slides))
    issues.extend(evaluate_layout_rhythm(slides, editorial_mode=editorial_mode).issues)

    plain_text = sum(1 for slide in slides if _slide_layout(slide) in TEXT_ONLY_LAYOUTS)
    if active and plain_text / active > 0.4:
        issues.append('Excesso de slides FULL_TEXT/MINIMAL para o modo social premium.')

    score = 100
    seen = set()
    for issue in issues:
        if issue in seen:
            continue
        seen.add(issue)
        if 'texto' in issue.lower() or 'budget' in issue.lower():
            score -= 14
        elif 'parecida' in issue.lower() or 'repet' in issue.lower():
            score -= 16
        else:
            score -= 10
    if issues:
        score = min(score, 69)
    return EditorialQualityResult(
        valid=not issues,
        editorial_mode=editorial_mode,
        score=max(0, min(100, score)),
        issues=list(dict.fromkeys(issues)),
        role_counts=role_counts,
    )


def _text_budget_issues(slide, index, editorial_mode):
    role = _slide_role(slide)
    budget = get_slide_text_budget(editorial_mode, role, _slide_layout(slide))
    title = _slide_title(slide)
    body = _slide_body(slide)
    issues = []
    title_words = _word_count(title)
    body_words = _word_count(body)
    total_chars = len((title + ' ' + body).strip())
    lines = len([line for line in (title + '\n' + body).splitlines() if line.strip()])

    if title_words > budget.max_title_words:
        issues.append(f'Slide {index}: titulo excede o limite editorial do papel {role}.')
    if body_words > budget.max_body_words:
        issues.append(f'Slide {index}: texto excede o limite editorial do papel {role}.')
    if total_chars > budget.max_total_chars:
        issues.append(f'Slide {index}: densidade textual alta para o papel {role}.')
    if lines > budget.max_lines:
        issues.append(f'Slide {index}: muitas linhas de texto para o papel {role}.')
    return issues


def _repetition_issues(slides):
    issues = []
    normalized = [_normalize_text(f'{_slide_title(slide)} {_slide_body(slide)}') for slide in slides]
    for left_index, left in enumerate(normalized):
        if not left:
            continue
        for right_index in range(left_index + 1, len(normalized)):
            right = normalized[right_index]
            if not right:
                continue
            ratio = SequenceMatcher(None, left, right).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                issues.append(f'Slides {left_index + 1} e {right_index + 1} estao muito semelhantes.')
                return issues

    openings = {}
    for index, text in enumerate(normalized, start=1):
        words = text.split()
        if len(words) < 2:
            continue
        opening = ' '.join(words[:2])
        openings.setdefault(opening, []).append(index)
    repeated = [items for items in openings.values() if len(items) >= 3]
    if repeated:
        issues.append('Repeticao de abertura textual em muitos slides.')
    return issues


def _role_counts(slides):
    counts = {}
    for slide in slides:
        role = _slide_role(slide)
        counts[role] = counts.get(role, 0) + 1
    return counts


def _slide_base_image_valid(slide):
    return bool(
        getattr(slide, 'source_base_image_id', None)
        and getattr(slide, 'content_id', None)
        and slide.source_base_image.profile_id == slide.content.profile_id
    )


def _slide_has_image(slide):
    return bool(_slide_base_image_valid(slide) or getattr(slide, 'source_image', None))


def _slide_visual_treatment(slide):
    treatment = getattr(slide, 'visual_treatment', '') or SocialCarouselSlide.VisualTreatment.AUTO
    if treatment == SocialCarouselSlide.VisualTreatment.AUTO:
        if _slide_has_image(slide):
            return SocialCarouselSlide.VisualTreatment.IMAGE_BACKGROUND
        if _slide_layout(slide) in {'GRAPHIC_DARK', 'GRAPHIC_LIGHT', 'EDITORIAL_CARD', 'CTA_VISUAL', 'CENTER_CARD', 'CTA_CLEAN', 'EDITORIAL_SPLIT', 'QUOTE_BIG', 'DARK_MINIMAL_TEXT'}:
            return SocialCarouselSlide.VisualTreatment.GRAPHIC_BACKGROUND
        return SocialCarouselSlide.VisualTreatment.TEXT_ONLY
    return treatment


def _slide_layout(slide):
    return (getattr(slide, 'preferred_layout', None) or getattr(slide, 'visual_intent', '') or '').upper()


def _slide_role(slide):
    return (getattr(slide, 'editorial_role', None) or getattr(slide, 'slide_role', '') or default_editorial_role(_slide_type(slide), 0, 1)).upper()


def _slide_type(slide):
    return (getattr(slide, 'slide_type', '') or SocialCarouselSlide.SlideType.CONTENT).upper()


def _slide_title(slide):
    return (getattr(slide, 'title', '') or '').strip()


def _slide_body(slide):
    return (getattr(slide, 'body', '') or '').strip()


def _word_count(text):
    return len(re.findall(r'\w+', text or '', flags=re.UNICODE))


def _normalize_text(text):
    normalized = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode('ascii')
    normalized = re.sub(r'[^a-zA-Z0-9 ]+', ' ', normalized).lower()
    return re.sub(r'\s+', ' ', normalized).strip()
