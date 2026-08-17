from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def _to_decimal(value):
    if value in (None, ''):
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal('0')


def format_money_br(value):
    amount = _to_decimal(value)
    formatted = f'{abs(amount):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    prefix = '-R$ ' if amount < 0 else 'R$ '
    return f'{prefix}{formatted}'


def format_decimal_br(value, places=2):
    amount = _to_decimal(value)
    formatted = f'{amount:,.{places}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return formatted


def format_percent_br(value, places=2):
    return f'{format_decimal_br(value, places)}%'


def format_date_br(value):
    if not value:
        return '-'
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime('%d/%m/%Y')
    return str(value)
