from django.core.management.base import BaseCommand, CommandError

from social_automation.backlog import cleanup_runaway, filtered_profiles
from social_automation.models import SocialContent


class Command(BaseCommand):
    help = 'Remove somente candidatos LIKELY_RUNAWAY da automacao social. Dry-run por padrao.'

    def add_arguments(self, parser):
        parser.add_argument('--profile-id', type=int)
        parser.add_argument('--username', default='')
        parser.add_argument('--content-type', choices=[choice[0] for choice in SocialContent.MediaType.choices], default='')
        parser.add_argument('--execute', action='store_true')

    def handle(self, *args, **options):
        if not options['profile_id'] and not options['username']:
            raise CommandError('Cleanup exige --profile-id ou --username. Execucao global nao permitida.')
        profiles = list(filtered_profiles(profile_id=options['profile_id'], username=options['username']))
        if not profiles:
            self.stdout.write('Nenhum perfil encontrado.')
            return
        if len(profiles) != 1:
            raise CommandError('Filtro retornou mais de um perfil. Refine --profile-id ou --username.')

        result = cleanup_runaway(profiles[0], execute=options['execute'], content_type=options['content_type'])
        mode = 'EXECUTE' if options['execute'] else 'DRY RUN'
        self.stdout.write(f'Modo: {mode}')
        self.stdout.write(f'Perfil: {result["profile"].nome} ({result["profile"].username})')
        self.stdout.write(f'before_reserved = {result["before_reserved"]}')
        self.stdout.write(f'hypothetical_deleted = {result["hypothetical_deleted"]}')
        self.stdout.write(f'after_reserved = {result["after_reserved"]}')
        self.stdout.write(f'target = {result["target"]}')
        self.stdout.write(f'minimum = {result["minimum"]}')
        self.stdout.write(f'deleted = {result["deleted"]}')
        self.stdout.write(f'files_deleted = {result["files_deleted"]}')
        self.stdout.write(f'candidate_ids = {", ".join(str(item) for item in result["candidate_ids"]) if result["candidate_ids"] else "-"}')
        if result['after_reserved'] < result['minimum']:
            self.stdout.write(self.style.WARNING('Atencao: a limpeza hipotetica ficaria abaixo do minimo operacional.'))
