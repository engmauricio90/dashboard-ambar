from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from social_automation.image_generation import SocialImagePrompt, build_social_image_prompt, generate_social_image, image_generation_available
from social_automation.models import SocialProfile


class Command(BaseCommand):
    help = 'Diagnostica a geracao de imagem social por IA sem publicar conteudo.'

    def add_arguments(self, parser):
        parser.add_argument('perfil')
        parser.add_argument('--generate', action='store_true', help='Executa uma unica geracao real.')
        parser.add_argument('--tema', default='diagnostico visual')

    def handle(self, *args, **options):
        profile = SocialProfile.objects.filter(username=options['perfil']).first() or SocialProfile.objects.filter(pk=options['perfil']).first()
        if not profile:
            raise CommandError('Perfil nao encontrado.')
        prompt = build_social_image_prompt(
            profile,
            purpose='IMAGE_BANK',
            visual_intent='CLEAN',
            media_intent=options['tema'],
            desired_text_zone='HERO_LEFT',
            aspect_ratio='SQUARE',
            context={'dry_run': not options['generate']},
        )
        self.stdout.write(f'Perfil: {profile.nome} ({profile.username})')
        self.stdout.write(f'Politica: {profile.ai_image_policy}')
        self.stdout.write(f'Habilitada: {profile.ai_image_generation_enabled}')
        self.stdout.write(f'Modelo: {settings.OPENAI_SOCIAL_IMAGE_MODEL or "-"}')
        self.stdout.write(f'Qualidade: {settings.OPENAI_SOCIAL_IMAGE_QUALITY}')
        self.stdout.write(f'Disponivel: {image_generation_available(profile)}')
        self.stdout.write(f'Limite diario perfil: {profile.ai_image_daily_limit or "padrao"}')
        self.stdout.write(f'Prompt:\n{prompt}')
        if not options['generate']:
            self.stdout.write(self.style.WARNING('DRY RUN: nenhuma imagem foi gerada.'))
            return
        image = generate_social_image(
            SocialImagePrompt(
                profile_id=profile.id,
                prompt=prompt,
                aspect_ratio='SQUARE',
                purpose='IMAGE_BANK',
                metadata={'command': 'diagnosticar_geracao_imagem_social', 'visual_intent': 'CLEAN', 'media_intent': options['tema']},
            )
        )
        self.stdout.write(self.style.SUCCESS(f'Imagem gerada: {image.id} - {image.arquivo.name}'))
