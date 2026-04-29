from datetime import date
from decimal import Decimal

from django.db import migrations


def _d(value):
    return Decimal(value)


IPANEMA_NOTAS = [
    ('2024-11-05', '58 / T', '120482.00', '85054.70', '137481.91', '343018.61', '8575.47', '15123.01', '17150.93'),
    ('2024-12-02', '64 / T', '229784.20', '85093.70', '229373.90', '544251.80', '13606.30', '25231.13', '27212.59'),
    ('2025-01-08', '77 / T', '618719.26', '65092.40', '306435.56', '990247.22', '24756.18', '33707.91', '49512.36'),
    ('2025-02-13', '89 / T', '946241.85', '53751.30', '392874.81', '1392867.96', '34821.70', '43216.23', '69643.40'),
    ('2025-03-10', '95 / T', '430536.97', '28742.90', '251547.67', '710827.54', '17770.68', '27670.24', '35541.38'),
    ('2025-03-20', '103 / T', '160189.65', '72854.87', '125885.61', '358930.13', '8973.25', '13847.42', '17946.51'),
    ('2025-04-11', '112 / T', '344595.17', '28663.19', '215019.54', '588277.90', '14706.95', '23652.15', '29413.90'),
    ('2025-04-11', '113 / T', '53264.49', '77.62', '12630.96', '65973.07', '1649.32', '1389.41', '3298.65'),
    ('2025-05-21', '133 / T', '330122.54', '26211.00', '230733.08', '587066.62', '14676.67', '25380.64', '29353.33'),
    ('2025-05-21', '134 / T', '10784.34', '18927.78', '37710.24', '67422.36', '1685.56', '4148.13', '3371.12'),
    ('2025-06-13', '141 / T', '65620.65', '24660.00', '125501.94', '215782.59', '5394.57', '13805.21', '10789.13'),
    ('2025-06-16', '144 / T', '62573.85', '18130.08', '51103.94', '131807.87', '3295.20', '5621.43', '6590.39'),
    ('2025-07-15', '161 / T', '253245.89', '359.31', '49690.75', '303295.95', '7582.40', '5465.98', '15164.80'),
    ('2025-07-15', '162 / T', '28152.43', '21.15', '10806.65', '38980.23', '974.51', '1188.73', '1949.01'),
    ('2025-08-18', '197 / T', '530934.52', '235.55', '157749.10', '688919.17', '17222.98', '17352.40', '34445.96'),
    ('2025-08-18', '198 / T', '290936.71', '36628.90', '11344.77', '338910.38', '8472.76', '1247.92', '16945.52'),
    ('2025-08-19', '199 / T', '4859.39', '3415.76', '4278.16', '12553.31', '313.82', '470.60', '627.67'),
    ('2025-09-19', '232 / T', '424236.06', '1440.44', '143110.49', '568786.99', '14219.67', '15742.15', '28439.35'),
    ('2025-09-19', '233 / T', '21187.82', '0.00', '5296.95', '26484.77', '662.12', '582.66', '1324.24'),
    ('2025-10-16', '250 / T', '263877.92', '944.20', '120655.31', '385477.43', '9636.94', '13272.08', '19273.87'),
    ('2025-10-16', '251 / T', '17442.52', '0.00', '4360.63', '21803.15', '545.08', '479.67', '1090.16'),
    ('2025-10-16', '252 / T', '70720.47', '17312.59', '11303.41', '99336.47', '2483.41', '1243.38', '4966.82'),
    ('2025-11-13', '273 / T', '134879.58', '803.48', '51823.18', '187506.24', '4687.66', '5700.55', '9375.31'),
    ('2025-11-13', '274 / T', '18215.66', '15.00', '3875.79', '22106.45', '552.66', '426.34', '1105.32'),
    ('2025-11-13', '275 / T', '152831.60', '24798.85', '45665.79', '223296.24', '5582.40', '5023.24', '11164.81'),
    ('2025-12-18', '303 / T', '307782.96', '968.08', '71630.54', '380381.58', '9509.53', '7879.36', '19019.08'),
    ('2025-12-18', '304 / T', '23061.02', '11.30', '4514.28', '27586.60', '689.67', '496.57', '1379.33'),
    ('2025-12-18', '305 / T', '34860.69', '0.00', '7134.96', '41995.65', '1049.89', '784.85', '2099.78'),
    ('2026-02-19', '336', '255640.47', '1923.53', '77010.23', '334574.23', '8364.36', '8471.12', '16728.71'),
]


def encontrar_obra_ipanema(Obra):
    obra_exata = Obra.objects.filter(nome_obra__iexact='IPANEMA').first()
    if obra_exata:
        return obra_exata
    return Obra.objects.filter(nome_obra__icontains='ipanema').order_by('id').first()


def carregar_ipanema(apps, schema_editor):
    Obra = apps.get_model('obras', 'Obra')
    NotaFiscal = apps.get_model('obras', 'NotaFiscal')
    RetencaoNotaFiscal = apps.get_model('obras', 'RetencaoNotaFiscal')
    RetencaoTecnicaObra = apps.get_model('obras', 'RetencaoTecnicaObra')

    obra = encontrar_obra_ipanema(Obra)
    if obra is None:
        return

    for (
        data_text,
        numero,
        material,
        equipamento,
        mao_obra,
        total_bruto,
        issqn,
        inss,
        retencao_tecnica,
    ) in IPANEMA_NOTAS:
        data_emissao = date.fromisoformat(data_text)
        nota, _ = NotaFiscal.objects.update_or_create(
            obra=obra,
            numero=numero,
            defaults={
                'data_emissao': data_emissao,
                'valor_bruto': _d(total_bruto),
                'status': 'emitida',
                'observacoes': (
                    f'Importado da planilha Ipanema. Material: R$ {material}; '
                    f'Equipamento: R$ {equipamento}; Mao de obra: R$ {mao_obra}.'
                ),
            },
        )
        RetencaoNotaFiscal.objects.update_or_create(
            nota_fiscal=nota,
            tipo='iss',
            descricao='ISSQN retido',
            defaults={'valor': _d(issqn)},
        )
        RetencaoNotaFiscal.objects.update_or_create(
            nota_fiscal=nota,
            tipo='inss',
            descricao='INSS retido',
            defaults={'valor': _d(inss)},
        )
        RetencaoTecnicaObra.objects.update_or_create(
            obra=obra,
            tipo='retencao',
            data_referencia=data_emissao,
            descricao=f'Retencao tecnica NF {numero}',
            defaults={'valor': _d(retencao_tecnica)},
        )

    RetencaoTecnicaObra.objects.update_or_create(
        obra=obra,
        tipo='devolucao',
        data_referencia=date(2025, 12, 18),
        descricao='PG RETENCAO - data nao informada na planilha',
        defaults={
            'valor': _d('220000.00'),
            'data_devolucao': date(2025, 12, 18),
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('obras', '0004_retencaotecnicaobra_data_devolucao_and_more'),
    ]

    operations = [
        migrations.RunPython(carregar_ipanema, migrations.RunPython.noop),
    ]
