from django.core.management.base import BaseCommand, CommandError

from social_automation.ai import build_social_content_prompt
from social_automation.generation import _historico, _image_contexts
from social_automation.models import SocialContent, SocialProfile


def _find_profile(username):
    normalized = (username or '').strip()
    if not normalized:
        raise CommandError('Informe --username.')
    alternatives = {normalized}
    if normalized.startswith('@'):
        alternatives.add(normalized[1:])
    else:
        alternatives.add(f'@{normalized}')
    return SocialProfile.objects.get(username__in=alternatives)


def _approx_tokens(text):
    return max(1, round(len(text or '') / 4))


class Command(BaseCommand):
    help = 'Inspeciona o prompt final de geracao de copy social sem chamar OpenAI.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--type', choices=[SocialContent.MediaType.IMAGE, SocialContent.MediaType.REEL], required=True)
        parser.add_argument('--tema', default='')
        parser.add_argument('--quantidade', type=int, default=1)
        parser.add_argument('--show-schema', action='store_true')

    def handle(self, *args, **options):
        profile = _find_profile(options['username'])
        media_type = options['type']
        historico = _historico(profile)
        image_contexts = _image_contexts(profile, media_type)
        inspection = build_social_content_prompt(
            profile,
            options['quantidade'],
            options['tema'],
            historico,
            image_contexts=image_contexts,
        )

        self.stdout.write(f'Perfil: {profile.nome} ({profile.username})')
        self.stdout.write(f'Tipo: {media_type}')
        self.stdout.write('Provider calls: 0')
        self.stdout.write(f'Prompt chars: {len(inspection.prompt)}')
        self.stdout.write(f'Prompt tokens aprox: {_approx_tokens(inspection.prompt)}')
        self.stdout.write(f'Historico recente: {len(historico)}')
        self.stdout.write(f'Contextos de imagem: {len(image_contexts)}')
        self.stdout.write('')
        self.stdout.write('Blocos:')
        for name, text in inspection.blocks:
            self.stdout.write(f'{name}: chars={len(text)} tokens_aprox={_approx_tokens(text)}')
        self.stdout.write('')
        self.stdout.write('Prompt final:')
        self.stdout.write(inspection.prompt)
        if options['show_schema']:
            self.stdout.write('')
            self.stdout.write('Schema:')
            self.stdout.write(str(inspection.schema))
