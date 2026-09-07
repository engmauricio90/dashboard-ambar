from .models import SocialAIUsage


TEXT_CATEGORY = 'TEXT'
IMAGE_CATEGORY = 'IMAGE'
COMPOSITION_CATEGORY = 'COMPOSITION'
REVIEW_CATEGORY = 'REVIEW'
OTHER_CATEGORY = 'OTHER'

VISUAL_QUOTA_OPERATIONS = {
    SocialAIUsage.Operation.IMAGE_GENERATION,
    SocialAIUsage.Operation.COMPOSED_SLIDE,
}

COMPOSITION_OPERATIONS = {
    SocialAIUsage.Operation.COMPOSED_SLIDE,
}

REVIEW_OPERATIONS = {
    SocialAIUsage.Operation.COMPOSED_SLIDE_REVIEW,
}

PROVIDER_OPERATIONS = {
    SocialAIUsage.Operation.TEXT_GENERATION,
    SocialAIUsage.Operation.IMAGE_GENERATION,
    SocialAIUsage.Operation.IMAGE_ANALYSIS,
    SocialAIUsage.Operation.IDEATION,
    SocialAIUsage.Operation.CREATIVE_BLUEPRINT,
    SocialAIUsage.Operation.COMPOSED_SLIDE,
    SocialAIUsage.Operation.COMPOSED_SLIDE_REVIEW,
}

OPERATION_CATEGORIES = {
    SocialAIUsage.Operation.TEXT_GENERATION: TEXT_CATEGORY,
    SocialAIUsage.Operation.IDEATION: TEXT_CATEGORY,
    SocialAIUsage.Operation.CREATIVE_BLUEPRINT: TEXT_CATEGORY,
    SocialAIUsage.Operation.IMAGE_GENERATION: IMAGE_CATEGORY,
    SocialAIUsage.Operation.IMAGE_ANALYSIS: IMAGE_CATEGORY,
    SocialAIUsage.Operation.COMPOSED_SLIDE: COMPOSITION_CATEGORY,
    SocialAIUsage.Operation.COMPOSED_SLIDE_REVIEW: REVIEW_CATEGORY,
}

OPERATION_DESCRIPTIONS = {
    SocialAIUsage.Operation.TEXT_GENERATION: 'Texto/legenda',
    SocialAIUsage.Operation.IMAGE_GENERATION: 'Imagem IA avulsa',
    SocialAIUsage.Operation.IMAGE_ANALYSIS: 'Analise visual',
    SocialAIUsage.Operation.IDEATION: 'Ideacao de carrossel',
    SocialAIUsage.Operation.CREATIVE_BLUEPRINT: 'Blueprint criativo',
    SocialAIUsage.Operation.COMPOSED_SLIDE: 'Arte final de slide',
    SocialAIUsage.Operation.COMPOSED_SLIDE_REVIEW: 'Review visual/editorial',
}


def ai_usage_category(operation):
    return OPERATION_CATEGORIES.get(operation, OTHER_CATEGORY)


def counts_toward_visual_quota(operation):
    return operation in VISUAL_QUOTA_OPERATIONS


def ai_usage_policy(operation):
    return {
        'operation': operation,
        'description': OPERATION_DESCRIPTIONS.get(operation, operation),
        'category': ai_usage_category(operation),
        'provider_called_by_design': operation in PROVIDER_OPERATIONS,
        'quota': counts_toward_visual_quota(operation),
        'composition': operation in COMPOSITION_OPERATIONS,
        'review': operation in REVIEW_OPERATIONS,
        'health': True,
        'daily_profile_limit': counts_toward_visual_quota(operation),
    }
