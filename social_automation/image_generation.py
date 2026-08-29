from dataclasses import dataclass

from django.conf import settings


class SocialImageGenerationDisabled(Exception):
    pass


@dataclass(frozen=True)
class SocialImagePrompt:
    profile_id: int
    prompt: str
    aspect_ratio: str = '1:1'
    purpose: str = 'base_image'


def image_generation_available(profile=None):
    if profile and not profile.ai_image_generation_enabled:
        return False
    return bool(settings.OPENAI_API_KEY and settings.OPENAI_SOCIAL_IMAGE_MODEL)


def build_image_generation_prompt(profile, base_prompt):
    instructions = [profile.image_ai_instructions, base_prompt]
    return '\n\n'.join(item.strip() for item in instructions if item and item.strip())


def generate_social_image(prompt: SocialImagePrompt):
    if not image_generation_available():
        raise SocialImageGenerationDisabled('Geracao de imagem por IA nao configurada.')
    raise SocialImageGenerationDisabled('Fundacao pronta; chamada real de geracao de imagem ainda nao foi habilitada.')
