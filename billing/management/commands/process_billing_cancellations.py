from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import Assinatura
from billing.services.mercadopago import MercadoPagoError, cancelar_assinatura_gateway


class Command(BaseCommand):
    help = 'Processa cancelamentos agendados antes da proxima renovacao.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--lead-minutes',
            type=int,
            default=60,
            help='Antecedencia minima para cancelar no gateway antes do fim do periodo.',
        )

    def handle(self, *args, **options):
        agora = timezone.now()
        antecedencia = timezone.timedelta(minutes=max(options['lead_minutes'], 0))
        assinaturas = Assinatura.objects.filter(cancel_at_period_end=True).order_by('id')
        processadas = 0
        falhas = 0

        for assinatura in assinaturas:
            if not assinatura.data_fim_periodo:
                self.stdout.write(self.style.WARNING(
                    f'Assinatura {assinatura.id} sem data_fim_periodo; cancelamento nao processado.'
                ))
                falhas += 1
                continue

            limite_gateway = assinatura.data_fim_periodo - antecedencia
            if assinatura.canceled_at is None and agora >= limite_gateway:
                try:
                    cancelar_assinatura_gateway(assinatura)
                except MercadoPagoError:
                    self.stdout.write(self.style.WARNING(
                        f'Falha ao cancelar assinatura {assinatura.id} no gateway; estado local preservado.'
                    ))
                    falhas += 1
                    continue
                assinatura.canceled_at = agora
                assinatura.save(update_fields=['canceled_at', 'atualizado_em'])

            if assinatura.canceled_at is not None and agora >= assinatura.data_fim_periodo:
                assinatura.status = Assinatura.Status.CANCELADA
                assinatura.proxima_cobranca = None
                assinatura.save(update_fields=['status', 'proxima_cobranca', 'atualizado_em'])
            processadas += 1

        self.stdout.write(self.style.SUCCESS(
            f'Cancelamentos processados. processadas={processadas} falhas={falhas}'
        ))
