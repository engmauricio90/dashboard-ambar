from django.core.management.base import BaseCommand, CommandError

from social_automation.backlog import CleanupRunawayError, cleanup_runaway, filtered_profiles
from social_automation.models import SocialContent


class Command(BaseCommand):
    help = 'Remove somente candidatos LIKELY_RUNAWAY da automacao social. Dry-run por padrao.'

    def add_arguments(self, parser):
        parser.add_argument('--profile-id', type=int)
        parser.add_argument('--username', default='')
        parser.add_argument('--content-type', choices=[choice[0] for choice in SocialContent.MediaType.choices], default='')
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--include-technical-shell', action='store_true')
        parser.add_argument('--expected-count', type=int)
        parser.add_argument('--confirm-profile', default='')

    def handle(self, *args, **options):
        if not options['profile_id'] and not options['username']:
            raise CommandError('Cleanup exige --profile-id ou --username. Execucao global nao permitida.')
        profiles = list(filtered_profiles(profile_id=options['profile_id'], username=options['username']))
        if not profiles:
            self.stdout.write('Nenhum perfil encontrado.')
            return
        if len(profiles) != 1:
            raise CommandError('Filtro retornou mais de um perfil. Refine --profile-id ou --username.')

        profile = profiles[0]
        if options['include_technical_shell'] and options['execute']:
            if options['expected_count'] is None:
                raise CommandError('Cleanup TECHNICAL_SHELL exige --expected-count.')
            if not options['confirm_profile']:
                raise CommandError('Cleanup TECHNICAL_SHELL exige --confirm-profile.')

        try:
            result = cleanup_runaway(
                profile,
                execute=options['execute'],
                content_type=options['content_type'],
                include_technical_shell=options['include_technical_shell'],
                expected_count=options['expected_count'],
                confirm_profile=options['confirm_profile'],
            )
        except CleanupRunawayError as exc:
            raise CommandError(str(exc)) from exc
        mode = 'EXECUTE' if options['execute'] else 'DRY RUN'
        self.stdout.write(f'Modo: {mode}')
        self.stdout.write(f'Perfil: {result["profile"].nome} ({result["profile"].username})')
        if profile.modo_operacao == profile.ModoOperacao.AUTOMATICO:
            self.stdout.write(self.style.WARNING('WARNING: Recomenda-se colocar o perfil em modo Manual antes do cleanup.'))
        self.stdout.write(f'include_technical_shell = {result["include_technical_shell"]}')
        self.stdout.write(f'Eligible EMPTY = {result["eligible_empty"]}')
        self.stdout.write(f'Eligible TECHNICAL_SHELL = {result["eligible_technical_shell"]}')
        self.stdout.write(f'Protected = {result["protected"]}')
        self.stdout.write(f'Review required = {result["review_required"]}')
        self.stdout.write(f'Total hypothetical delete = {result["hypothetical_deleted"]}')
        self.stdout.write(f'before_reserved = {result["before_reserved"]}')
        self.stdout.write(f'after_reserved = {result["after_reserved"]}')
        self.stdout.write(f'target = {result["target"]}')
        self.stdout.write(f'minimum = {result["minimum"]}')
        self.stdout.write(f'deleted = {result["deleted"]}')
        self.stdout.write(f'files_deleted = {result["files_deleted"]}')
        self.stdout.write(f'candidate_ids = {", ".join(str(item) for item in result["candidate_ids"]) if result["candidate_ids"] else "-"}')
        for burst in result['bursts']:
            self.stdout.write(
                f'Burst {burst.id}: start={burst.start.isoformat()} end={burst.end.isoformat()} '
                f'count={burst.size} ids={", ".join(str(item) for item in burst.content_ids)}'
            )
        if result['after_reserved'] < result['minimum']:
            self.stdout.write(self.style.WARNING(
                'Apos o cleanup, o estoque reservado ficara abaixo do minimo. '
                'Isso e esperado quando conteudo invalido estava sendo contado como estoque. '
                'O scheduler podera recompor estoque legitimo posteriormente.'
            ))
