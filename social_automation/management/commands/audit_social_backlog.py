import csv

from django.core.management.base import BaseCommand, CommandError

from social_automation.backlog import (
    LIKELY_RUNAWAY_EMPTY,
    LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL,
    SUMMARY_CLASSIFICATIONS,
    audit_backlog,
)
from social_automation.models import SocialContent


class Command(BaseCommand):
    help = 'Audita backlog da automacao social sem alterar banco, arquivos ou chamadas externas.'

    def add_arguments(self, parser):
        parser.add_argument('--profile-id', type=int)
        parser.add_argument('--username', default='')
        parser.add_argument('--content-type', choices=[choice[0] for choice in SocialContent.MediaType.choices], default='')
        parser.add_argument('--verbose', action='store_true')
        parser.add_argument('--format', choices=['text', 'csv'], default='text')
        parser.add_argument('--output', default='')

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
        if options['format'] == 'csv':
            self._write_csv(result, options['output'])
            return
        for data in result.values():
            profile = data['profile']
            summary = data['summary']
            classifications = summary['classifications']
            self.stdout.write(f'Perfil: {profile.nome} ({profile.username})')
            self.stdout.write(f'Total: {summary["total"]}')
            for key in SUMMARY_CLASSIFICATIONS:
                ids = [str(item.content.id) for item in data['items'] if item.classification == key]
                self.stdout.write(f'{key}: {classifications[key]}')
                self.stdout.write(f'IDs {key}: {", ".join(ids) if ids else "-"}')
            self.stdout.write(f'Por status: {dict(summary["by_status"])}')
            self.stdout.write(f'Por tipo: {dict(summary["by_type"])}')
            self.stdout.write(f'Por origem: {dict(summary["by_origin"])}')
            self.stdout.write(f'Por slot: {dict(summary["by_slot"])}')
            self.stdout.write(f'Reservado: {summary["reserved_total"]} / alvo {summary["target"]} / minimo {summary["minimum"]}')
            self.stdout.write(f'Burst clusters found: {len(summary["bursts"])}')
            for cluster in summary['bursts']:
                self.stdout.write(
                    f'Cluster {cluster.id}: {cluster.start.isoformat()} -> {cluster.end.isoformat()} '
                    f'count={cluster.size} ids={",".join(str(item) for item in cluster.content_ids)} types={dict(cluster.types)}'
                )
            self.stdout.write(
                'Hypothetical cleanup A empty only: removed={removed} after_reserved={after}'.format(
                    removed=classifications[LIKELY_RUNAWAY_EMPTY],
                    after=summary['cleanup_empty_after_reserved'],
                )
            )
            self.stdout.write(
                'Hypothetical cleanup B empty + technical shell: removed={removed} after_reserved={after}'.format(
                    removed=classifications[LIKELY_RUNAWAY_EMPTY] + classifications[LIKELY_RUNAWAY_WITH_TECHNICAL_SHELL],
                    after=summary['cleanup_empty_shell_after_reserved'],
                )
            )
            self.stdout.write(f'Assets: {dict(summary["asset_summary"])}')
            if options['verbose']:
                for item in data['items']:
                    content = item.content
                    forensic = item.forensics
                    self.stdout.write(
                        'ID={id} Created={created} Status={status} Type={type} Origin={origin} Scheduled={scheduled} '
                        'Run={run} RunStatus={run_status} Slides={slides} Ready={ready} Pending={pending} '
                        'Assets={assets} Reviewed={reviewed} Burst={burst} Classification={klass} Reason={reasons}'.format(
                            id=content.id,
                            created=content.created_at.isoformat(),
                            status=content.status,
                            type=content.media_type,
                            origin=forensic.origin,
                            scheduled=content.scheduled_at.isoformat() if content.scheduled_at else '-',
                            run=forensic.run_id or '-',
                            run_status=forensic.run_status or '-',
                            slides=forensic.total_slides,
                            ready=forensic.ready_slides,
                            pending=forensic.pending_slides,
                            assets=forensic.useful_asset_count,
                            reviewed=forensic.reviewed_slides,
                            burst=forensic.burst_cluster_id or '-',
                            klass=item.classification,
                            reasons=';'.join(item.reasons),
                        )
                    )

    def _write_csv(self, result, output):
        rows = []
        for data in result.values():
            for item in data['items']:
                content = item.content
                forensic = item.forensics
                rows.append(
                    {
                        'profile': content.profile.username,
                        'id': content.id,
                        'created': content.created_at.isoformat(),
                        'status': content.status,
                        'type': content.media_type,
                        'origin': forensic.origin,
                        'scheduled': content.scheduled_at.isoformat() if content.scheduled_at else '',
                        'run': forensic.run_id or '',
                        'run_status': forensic.run_status,
                        'slides': forensic.total_slides,
                        'ready': forensic.ready_slides,
                        'pending': forensic.pending_slides,
                        'assets': forensic.useful_asset_count,
                        'reviewed': forensic.reviewed_slides,
                        'burst': forensic.burst_cluster_id or '',
                        'classification': item.classification,
                        'reasons': ';'.join(item.reasons),
                    }
                )
        fieldnames = ['profile', 'id', 'created', 'status', 'type', 'origin', 'scheduled', 'run', 'run_status', 'slides', 'ready', 'pending', 'assets', 'reviewed', 'burst', 'classification', 'reasons']
        if output:
            with open(output, 'w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write(f'CSV gerado: {output}')
            return
        writer = csv.DictWriter(self.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
