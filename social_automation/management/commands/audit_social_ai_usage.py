from datetime import date

from django.core.management.base import BaseCommand, CommandError

from social_automation.diagnostics import audit_ai_usage, find_social_profile


def bool_label(value):
    return 'SIM' if value else 'NAO'


class Command(BaseCommand):
    help = 'Audita usos de IA social por perfil/data sem alterar dados nem chamar provedores externos.'

    def add_arguments(self, parser):
        parser.add_argument('--profile-id', type=int)
        parser.add_argument('--username', default='')
        parser.add_argument('--date', required=True, help='Data local do perfil no formato AAAA-MM-DD.')

    def handle(self, *args, **options):
        if not options['profile_id'] and not options['username']:
            raise CommandError('Informe --profile-id ou --username.')
        try:
            target_date = date.fromisoformat(options['date'])
        except ValueError as exc:
            raise CommandError('Informe --date no formato AAAA-MM-DD.') from exc
        profile = find_social_profile(username=options['username'], profile_id=options['profile_id'])
        report = audit_ai_usage(profile, target_date)

        self.stdout.write(f'Perfil: {profile.nome} ({profile.username})')
        self.stdout.write(f'Data local: {report["date"].isoformat()}')
        self.stdout.write(f'Timezone do perfil: {report["timezone"]}')
        self.stdout.write(f'Janela local: {report["local_start"].isoformat()} -> {report["local_end"].isoformat()}')
        self.stdout.write(f'Janela UTC: {report["start_utc"].isoformat()} -> {report["end_utc"].isoformat()}')
        self.stdout.write(f'Limite configurado: {report["configured_limit"]}')
        self.stdout.write(f'Limite efetivo: {report["effective_limit"]}')
        self.stdout.write(f'Fonte do limite: {report["limit_source"]}')
        self.stdout.write(f'Total mostrado pelo health do perfil: {report["health_total"]}')
        self.stdout.write(f'Total relevante para quota de imagem/composicao: {report["quota_relevant_success"]}')
        self.stdout.write(f'Chamadas provedoras de imagem/composicao: {report["provider_image_composition_calls"]}')
        self.stdout.write('')
        self.stdout.write('Breakdown por finalidade:')
        self.stdout.write('Purpose | Operation | Count | Successful | Failed | Provider called | Contents | Carousels | Slides | Quota | Composition | Review | Health')
        for row in report['breakdown']:
            self.stdout.write(
                '{purpose} | {operation} | {count} | {successful} | {failed} | {provider_called} | {content_count} | {carousel_count} | {slide_count} | {quota} | {composition} | {review} | {health}'.format(
                    purpose=row['purpose'],
                    operation=row['operation'],
                    count=row['count'],
                    successful=row['successful'],
                    failed=row['failed'],
                    provider_called=row['provider_called'],
                    content_count=row['content_count'],
                    carousel_count=row['carousel_count'],
                    slide_count=row['slide_count'],
                    quota=bool_label(row['quota']),
                    composition=bool_label(row['composition']),
                    review=bool_label(row['review']),
                    health=bool_label(row['health']),
                )
            )
        self.stdout.write('')
        self.stdout.write('Mapa de operacoes:')
        self.stdout.write('Operation | Description | Provider called | Quota | Composition | Review | Health | Daily profile limit')
        for policy in report['policies']:
            self.stdout.write(
                '{operation} | {description} | {provider} | {quota} | {composition} | {review} | {health} | {daily}'.format(
                    operation=policy['operation'],
                    description=policy['description'],
                    provider=bool_label(policy['provider_called_by_design']),
                    quota=bool_label(policy['quota']),
                    composition=bool_label(policy['composition']),
                    review=bool_label(policy['review']),
                    health=bool_label(policy['health']),
                    daily=bool_label(policy['daily_profile_limit']),
                )
            )
