from decimal import Decimal


def calcular_total(*values):
    total = Decimal('0')
    for value in values:
        total += value or Decimal('0')
    return total


def calcular_total_multiplicacao(quantidade, valor_unitario):
    return (quantidade or Decimal('0')) * (valor_unitario or Decimal('0'))
