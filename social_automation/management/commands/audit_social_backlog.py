from django.core.management.base import BaseCommand, CommandError

from social_automation.backlog import KEEP, LIKELY_RUNAWAY, REVIEW_REQUIRED, UNSAFE_TO_DELETE, audit_backlog
from social_automation.models import SocialContent


class Command(BaseCommand):
    help = 'Audita backlog da automacao social sem alterar banco, arquivos ou chamadas externas.'

    def add_arguments(self, parser):
        parser.add_argument('--profile-id', type=int)
        parser.add_argument('--username', default='')
        parser.add_argument('--content-type', choices=[choice[0] for choice in SocialContent.MediaType.choices], default='')
        parser.add_argument('--verbose', action='store_true')

    def handle(self, *args, **options):
        if not options['profile_id'] and not options['username']:
            raise CommandError('Informe --profile-id ou --username para evitar auditoria ampla acidental.')
        result = audit_backlog(
            profile_id=options['profile_id'],
            username=options['username'],
            content_type=options['content_type'],
        )
        if not result:
            self.stdout.write('Nenhum perfil encontrado.')
            return
        for data in result.values():
            profile = data['profile']
            summary = data['summary']
            classifications = summary['classifications']
            self.stdout.write(f'Perfil: {profile.nome} ({profile.username})')
            self.stdout.write(f'Total: {summary["total"]}')
            for key in [KEEP, LIKELY_RUNAWAY, REVIEW_REQUIRED, UNSAFE_TO_DELETE]:
                ids = [str(item.content.id) for item in data['items'] if item.classification == key]
                self.stdout.write(f'{key}: {classifications[key]}')
                self.stdout.write(f'IDs {key}: {", ".join(ids) if ids else "-"}')
            self.stdout.write(f'Por status: {dict(summary["by_status"])}')
            self.stdout.write(f'Por tipo: {dict(summary["by_type"])}')
            self.stdout.write(f'Por origem: {dict(summary["by_origin"])}')
            self.stdout.write(f'Por slot: {dict(summary["by_slot"])}')
            self.stdout.write(f'Reservado: {summary["reserved_total"]} / alvo {summary["target"]} / minimo {summary["minimum"]}')
            if options['verbose']:
                for item in data['items']:
                    content = item.content
                    attempts = list(content.publish_attempts.all())
                    runs = list(content.carousel_generation_runs.all())
                    slides = list(content.carousel_slides.all())
                    assets = int(bool(content.final_image)) + int(bool(content.final_video)) + sum(1 for slide in slides if slide.rendered_image or slide.ai_composed_image)
                    origin = 'auto' if content.events.filter(acao='gerado_ia').exists() or content.carousel_generation_runs.all() else 'manual'
                    self.stdout.write(
                        'content={id} class={klass} status={status} type={type} created={created} '
                        'scheduled_for={scheduled} published_at={published} origin={origin} attempts={attempts} '
                        'external_post_id={external} runs={runs} slides={slides} assets={assets} reasons={reasons}'.format(
                            id=content.id,
                            klass=item.classification,
                            status=content.status,
                            type=content.media_type,
                            created=content.created_at.isoformat(),
                            scheduled=content.scheduled_at.isoformat() if content.scheduled_at else '-',
                            published=content.published_at.isoformat() if content.published_at else '-',
                            origin=origin,
                            attempts=len(attempts),
                            external=bool(content.external_post_id),
                            runs={run.status: sum(1 for item_run in runs if item_run.status == run.status) for run in runs},
                            slides={slide.ai_composition_status: sum(1 for item_slide in slides if item_slide.ai_composition_status == slide.ai_composition_status) for slide in slides},
                            assets=assets,
                            reasons=';'.join(item.reasons),
                        )
                    )
