from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import Assinatura
from billing.services.mercadopago import (
    MercadoPagoError,
    MercadoPagoUnavailable,
    aplicar_assinatura_gateway,
    consultar_assinatura_gateway,
)


class Command(BaseCommand):
    help = 'Reconcilia assinaturas recorrentes com o gateway de billing.'

    def add_arguments(self, parser):
        parser.add_argument('--assinatura', type=int, help='ID de uma assinatura especifica.')

    def handle(self, *args, **options):
        assinaturas = Assinatura.objects.all().order_by('id')
        if options.get('assinatura'):
            assinaturas = assinaturas.filter(pk=options['assinatura'])

        processadas = 0
        indisponiveis = 0
        for assinatura in assinaturas:
            assinatura.avaliar_suspensao(agora=timezone.now())
            if not assinatura.gateway_subscription_id:
                processadas += 1
                continue
            try:
                data = consultar_assinatura_gateway(assinatura.gateway_subscription_id)
            except MercadoPagoUnavailable:
                indisponiveis += 1
                self.stdout.write(self.style.WARNING(f'Gateway indisponivel para assinatura {assinatura.id}; estado local preservado.'))
                continue
            except MercadoPagoError:
                self.stdout.write(self.style.WARNING(f'Falha ao consultar assinatura {assinatura.id}; estado local preservado.'))
                continue

            aplicar_assinatura_gateway(data)
            processadas += 1

        self.stdout.write(self.style.SUCCESS(f'Reconciliacao concluida. processadas={processadas} gateway_indisponivel={indisponiveis}'))
