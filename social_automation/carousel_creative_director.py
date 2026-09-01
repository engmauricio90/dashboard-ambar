from .carousel_creative_blueprint import CreativeDirection, SlideCreativePlan, normalize_composition_type
from .models import SocialCarouselSlide
from .visual_composer import visual_identity_for_profile


ROLE_COMPOSITION_PREFS = {
    SocialCarouselSlide.SlideRole.HOOK_COVER: [SocialCarouselSlide.CompositionType.TYPOGRAPHIC_HERO, SocialCarouselSlide.CompositionType.PHOTO_WITH_TYPE],
    SocialCarouselSlide.SlideRole.BELIEF_BREAK: [SocialCarouselSlide.CompositionType.QUOTE_ART, SocialCarouselSlide.CompositionType.MINIMAL_STATEMENT],
    SocialCarouselSlide.SlideRole.CONTEXT: [SocialCarouselSlide.CompositionType.EDITORIAL_CARD, SocialCarouselSlide.CompositionType.SPLIT_COMPOSITION],
    SocialCarouselSlide.SlideRole.EXPLANATION: [SocialCarouselSlide.CompositionType.INFOGRAPHIC_LIGHT, SocialCarouselSlide.CompositionType.EDITORIAL_CARD],
    SocialCarouselSlide.SlideRole.INSIGHT: [SocialCarouselSlide.CompositionType.NUMBER_STATEMENT, SocialCarouselSlide.CompositionType.MINIMAL_STATEMENT],
    SocialCarouselSlide.SlideRole.VISUAL_PUNCH: [SocialCarouselSlide.CompositionType.PHOTO_EDITORIAL, SocialCarouselSlide.CompositionType.COLLAGE],
    SocialCarouselSlide.SlideRole.ACTION_STEP: [SocialCarouselSlide.CompositionType.SPLIT_COMPOSITION, SocialCarouselSlide.CompositionType.INFOGRAPHIC_LIGHT],
    SocialCarouselSlide.SlideRole.PROOF: [SocialCarouselSlide.CompositionType.SOCIAL_POST_CARD, SocialCarouselSlide.CompositionType.NUMBER_STATEMENT],
    SocialCarouselSlide.SlideRole.CONCLUSION: [SocialCarouselSlide.CompositionType.MINIMAL_STATEMENT, SocialCarouselSlide.CompositionType.QUOTE_ART],
    SocialCarouselSlide.SlideRole.CTA: [SocialCarouselSlide.CompositionType.CTA_EDITORIAL, SocialCarouselSlide.CompositionType.SOCIAL_POST_CARD],
}


def build_creative_direction(profile, blueprint, *, selected_idea=None, media_contexts=None, inspiration_context=None):
    identity = visual_identity_for_profile(profile)
    slides = []
    last_composition = ''
    for index, slide in enumerate(blueprint.slides, start=1):
        role = getattr(slide, 'slide_role', '') or SocialCarouselSlide.SlideRole.EXPLANATION
        composition = _composition_for_role(role, index, last_composition, profile.carousel_creative_variation)
        last_composition = composition
        slides.append(
            SlideCreativePlan(
                order=index,
                role=role,
                title=slide.title,
                body=slide.body,
                composition_type=composition,
                visual_goal=_visual_goal(slide, composition),
                image_strategy='REFERENCE_IF_USEFUL' if getattr(slide, 'media_required', False) else 'DIRECT_COMPOSITION',
                image_prompt=getattr(slide, 'media_intent', '') or '',
                text_emphasis=[part for part in [slide.title] if part],
                creative_notes=f'Usar {composition} sem coordenadas fixas; preservar copy canonica.',
                continuity_notes=_continuity_note(index, len(blueprint.slides), role),
            )
        )
    idea = selected_idea.as_dict() if selected_idea else {}
    return CreativeDirection(
        concept_name=idea.get('concept') or blueprint.topic or blueprint.hook,
        visual_story=idea.get('creative_direction') or 'Carrossel com progressao visual coerente entre slides.',
        design_language=_design_language(profile),
        color_strategy=f'Usar identidade do perfil: {identity.primary_color}, {identity.secondary_color}, destaque {identity.accent_color}.',
        typography_strategy='Tipografia legivel e editorial, sem inventar fonte fora da identidade visual cadastrada.',
        image_strategy='Usar referencias como inspiracao ou apoio, sem copiar arte de terceiros.',
        rhythm_strategy=_rhythm_strategy(profile),
        brand_consistency=f'Preservar marca {identity.display_brand_name} e handle {profile.username}.',
        slides=slides,
    )


def _composition_for_role(role, index, last, variation):
    choices = ROLE_COMPOSITION_PREFS.get(role, [SocialCarouselSlide.CompositionType.EDITORIAL_CARD])
    if variation == 'LOW':
        return choices[0]
    if variation == 'HIGH':
        candidate = choices[(index - 1) % len(choices)]
        return candidate if candidate != last or len(choices) == 1 else choices[-1]
    candidate = choices[index % len(choices)]
    return candidate if candidate != last else choices[0]


def _visual_goal(slide, composition):
    return (
        f'Criar slide {composition} para papel {getattr(slide, "slide_role", "")}; '
        f'intencao visual {getattr(slide, "visual_intent", "")}; midia {getattr(slide, "media_intent", "") or "sem midia obrigatoria"}.'
    )


def _continuity_note(index, total, role):
    if index == 1:
        return 'Abrir com contraste e curiosidade; nao explicar tudo.'
    if index == total:
        return 'Encerrar com sensacao de conclusao e convite coerente.'
    return f'Adicionar uma nova informacao ao arco narrativo; papel {role}.'


def _design_language(profile):
    if profile.carousel_generation_mode == 'AI_FINISHED':
        return 'Arte final integrada por IA com direcao editorial e copy em portugues dentro da composicao.'
    if profile.carousel_generation_mode == 'AI_DIRECTED':
        return 'Direcao criativa da IA, renderizacao final pelo VisualComposer do sistema.'
    return 'Composicao do sistema com templates e assets selecionados.'


def _rhythm_strategy(profile):
    if profile.carousel_creative_variation == 'HIGH':
        return 'Variar composicao com contraste entre slides, mantendo familia estetica.'
    if profile.carousel_creative_variation == 'LOW':
        return 'Manter ritmo mais contido e consistente.'
    return 'Alternar respiro, impacto visual e explicacao sem criar clones.'
