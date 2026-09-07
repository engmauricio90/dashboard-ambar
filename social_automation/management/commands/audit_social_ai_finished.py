from django.core.management.base import BaseCommand, CommandError

from social_automation.diagnostics import audit_ai_finished, find_social_profile


class Command(BaseCommand):
    help = 'Audita runs AI_FINISHED por perfil sem alterar dados nem retomar geracao.'

    def add_arguments(self, parser):
        parser.add_argument('--profile-id', type=int)
        parser.add_argument('--username', default='')

    def handle(self, *args, **options):
        if not options['profile_id'] and not options['username']:
            raise CommandError('Informe --profile-id ou --username.')
        profile = find_social_profile(username=options['username'], profile_id=options['profile_id'])
        report = audit_ai_finished(profile)

        self.stdout.write(f'Perfil: {profile.nome} ({profile.username})')
        self.stdout.write(f'Conteudos carrossel reservados: {report["reserved_count"]}')
        self.stdout.write(f'Runs AI_FINISHED totais: {report["runs_total"]}')
        self.stdout.write(f'Runs parciais totais: {report["partial_runs_total"]}')
        self.stdout.write(f'Runs parciais operacionais: {report["operational_partial_runs"]}')
        self.stdout.write(f'Runs parciais historicos: {report["historical_partial_runs"]}')
        self.stdout.write(f'Runs ativos duplicados: {report["duplicate_active_runs"]}')
        self.stdout.write(f'Por status: {report["run_status_counts"]}')
        self.stdout.write(f'Slides em carrosseis reservados: {report["slide_counts"]}')
        self.stdout.write('')
        self.stdout.write('Conteudos reservados:')
        self.stdout.write('Content | Runs | Latest run | Latest status | Ready | Pending | Assets')
        for row in report['content_rows']:
            latest = row['latest_run']
            latest_id = latest.id if latest else '-'
            self.stdout.write(
                '{content_id} | {runs} | {latest_id} | {latest_status} | {ready} | {pending} | {assets}'.format(
                    content_id=row['content'].id,
                    runs=row['runs'],
                    latest_id=latest_id,
                    latest_status=row['latest_status'],
                    ready=row['ready'],
                    pending=row['pending'],
                    assets=row['assets'],
                )
            )
