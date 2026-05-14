from datetime import date
from decimal import Decimal
import re
import sys
import unicodedata

from django.db import migrations, models


def normalizar(valor):
    sem_acento = unicodedata.normalize('NFKD', valor or '').encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', sem_acento).strip().casefold()


def obter_obra_park_mall(Obra):
    alvos = {
        'park mall cassol',
        'park mall - cassol',
        'germania park mall',
        'germânia park mall',
    }
    for obra in Obra.objects.all():
        if normalizar(obra.nome_obra) in {normalizar(alvo) for alvo in alvos}:
            return obra
    obra, _ = Obra.objects.get_or_create(nome_obra='Park Mall - Cassol')
    return obra


def carregar_faturamentos_diretos(apps, schema_editor):
    if 'test' in sys.argv:
        return

    Obra = apps.get_model('obras', 'Obra')
    FaturamentoDireto = apps.get_model('controles', 'FaturamentoDireto')
    obra = obter_obra_park_mall(Obra)

    dados = [
        {
            'data_lancamento': date(2026, 4, 30),
            'numero_ordem_compra': '1413',
            'empresa_comprou': 'Giassi Ferro e Aco',
            'descricao': 'Barras de aco',
            'valor_nota': Decimal('10439.60'),
            'observacoes': (
                'Aco 6,3 mm = 43 und // Aco 8 mm = 13 und // Aco 10 mm = 71 und // '
                'Aco 12,5 mm = 20 und // Aco 16 mm = 16 und // Aco 20 mm = 8 und // Aco 25 mm = 13 und'
            ),
            'vencimento_boleto': '24/04/2026',
            'medicao_desconto': 'Medicao 01',
        },
        {
            'data_lancamento': date(2026, 5, 4),
            'numero_ordem_compra': '1415',
            'empresa_comprou': 'Cassol Materiais de Construcao',
            'descricao': 'Tubos PVC',
            'valor_nota': Decimal('7800.58'),
            'observacoes': (
                'PVC B 100 mm = 6 und // PVC B 150 mm = 9 und // PVC B 200 mm = 2 und // '
                'PVC R 100 mm = 21 und // PVC R 75 mm = 2 und // PVC R 50 mm = 4 und // '
                'PVC R 40 mm = 4 und // PVC M 25 mm = 5 und // PVC M 32 mm = 23 und // PVC M 50 mm = 6 und'
            ),
            'vencimento_boleto': '30/60/90',
            'medicao_desconto': 'Medicao 01',
        },
        {
            'data_lancamento': date(2026, 4, 28),
            'numero_ordem_compra': '1414',
            'empresa_comprou': 'Industria de Artefatos de Cimento Palmares',
            'descricao': 'Tubos de Concreto',
            'valor_nota': Decimal('11679.50'),
            'observacoes': 'PB 30X100 = 83 m e PB 40X100 = 55 m',
            'vencimento_boleto': '27/04/2026',
            'medicao_desconto': 'Medicao 01',
        },
        {
            'data_lancamento': date(2026, 5, 6),
            'numero_ordem_compra': '1425',
            'empresa_comprou': 'Cassol Materiais de Construcao',
            'descricao': 'Cimento, prego e arame',
            'valor_nota': Decimal('613.15'),
            'observacoes': '10 cimentos / 5 kg de arame / 5 kg de prego',
            'vencimento_boleto': '03/06/2026',
            'medicao_desconto': 'Medicao 01',
        },
        {
            'data_lancamento': date(2026, 5, 7),
            'numero_ordem_compra': '1426',
            'empresa_comprou': 'JP Com. De Chapas e Madeira',
            'descricao': 'Chapas e caibros',
            'valor_nota': Decimal('2770.00'),
            'observacoes': 'Chapa 9 mm = 38 und // caibro = 30 und',
            'vencimento_boleto': '06/06/2026',
            'medicao_desconto': 'Medicao 01',
        },
        {
            'data_lancamento': date(2026, 5, 7),
            'numero_ordem_compra': '1435',
            'empresa_comprou': 'JP Com. De Chapas e Madeira',
            'descricao': 'Chapas e caibros',
            'valor_nota': Decimal('996.00'),
            'observacoes': 'Ripa 5x5 = 35 und // Ripa 2,5x7 = 30 und // Tabua 2,5 x 10 = 25 und',
            'vencimento_boleto': '11/06/2026',
            'medicao_desconto': 'Medicao 01',
        },
    ]

    for item in dados:
        FaturamentoDireto.objects.update_or_create(
            obra=obra,
            numero_ordem_compra=item['numero_ordem_compra'],
            defaults={
                'numero_nf': '',
                **item,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('controles', '0016_faturamentodireto'),
    ]

    operations = [
        migrations.AddField(
            model_name='faturamentodireto',
            name='data_lancamento',
            field=models.DateField(blank=True, null=True, verbose_name='Data'),
        ),
        migrations.AddField(
            model_name='faturamentodireto',
            name='numero_ordem_compra',
            field=models.CharField(blank=True, max_length=80, verbose_name='Ordem de compra'),
        ),
        migrations.AlterField(
            model_name='faturamentodireto',
            name='numero_nf',
            field=models.CharField(blank=True, max_length=80, verbose_name='Nr da NF'),
        ),
        migrations.AlterField(
            model_name='faturamentodireto',
            name='vencimento_boleto',
            field=models.CharField(max_length=80, verbose_name='Vencimento do boleto'),
        ),
        migrations.AlterModelOptions(
            name='faturamentodireto',
            options={
                'ordering': ['-data_lancamento', '-id'],
                'verbose_name': 'Faturamento direto',
                'verbose_name_plural': 'Faturamentos diretos',
            },
        ),
        migrations.RunPython(carregar_faturamentos_diretos, migrations.RunPython.noop),
    ]
