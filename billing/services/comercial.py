import calendar
from decimal import Decimal

from django.utils import timezone

from billing.models import Assinatura


PERIODICIDADE_CONFIG = {
    Assinatura.Periodicidade.MENSAL: {
        'valor': Decimal('149.90'),
        'meses': 1,
        'rotulo': 'Mensal',
    },
    Assinatura.Periodicidade.SEMESTRAL: {
        'valor': Decimal('799.00'),
        'meses': 6,
        'rotulo': 'Semestral',
    },
    Assinatura.Periodicidade.ANUAL: {
        'valor': Decimal('1399.00'),
        'meses': 12,
        'rotulo': 'Anual',
    },
}


def valor_periodicidade(periodicidade):
    return PERIODICIDADE_CONFIG[periodicidade]['valor']


def meses_periodicidade(periodicidade):
    return PERIODICIDADE_CONFIG[periodicidade]['meses']


def adicionar_meses(data, meses):
    month = data.month - 1 + meses
    year = data.year + month // 12
    month = month % 12 + 1
    day = min(data.day, calendar.monthrange(year, month)[1])
    return data.replace(year=year, month=month, day=day)


def periodo_inicial(periodicidade, inicio=None):
    inicio = inicio or timezone.now()
    fim = adicionar_meses(inicio, meses_periodicidade(periodicidade))
    return inicio, fim, fim
