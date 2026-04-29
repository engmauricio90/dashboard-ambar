from datetime import date
from decimal import Decimal

from django.db import migrations


def _d(value):
    return Decimal(value)


ORLA_LAMI_NOTAS = [
    ('2025-03-20', '102 / T', '49297.18', '43547.01', '1368.36', '94212.55', '2355.32', '150.52', '4710.63'),
    ('2025-03-24', '106 / T', '57623.30', '12597.55', '39977.91', '110198.76', '2754.97', '4397.57', '5509.94'),
    ('2025-04-25', '122 / T', '45992.82', '48256.93', '33917.78', '128167.53', '3204.18', '3730.96', '6408.38'),
    ('2025-04-25', '123 / T', '49735.80', '-3220.61', '17692.32', '64207.51', '1605.19', '1946.16', '3210.38'),
    ('2025-05-15', '129 / T', '257664.26', '37006.60', '114434.90', '409105.76', '10227.65', '12587.84', '20455.29'),
    ('2025-05-15', '130 / T', '38079.28', '20917.50', '2412.90', '61409.68', '1535.24', '265.42', '3070.48'),
    ('2025-06-16', '145 / T', '313572.36', '35070.65', '124465.99', '473109.00', '11827.73', '13691.26', '23655.45'),
    ('2025-06-18', '151 / T', '18632.98', '21671.80', '3092.40', '43397.18', '1084.92', '340.16', '2169.86'),
    ('2025-07-10', '157 / T', '153981.35', '37609.37', '76605.78', '268196.50', '6704.90', '8426.64', '13409.83'),
    ('2025-07-10', '158 / T', '15670.12', '20957.20', '3513.96', '40141.28', '1003.53', '386.54', '2007.06'),
    ('2025-07-22', '170 / T', '5389.02', '0.00', '1869.02', '7258.04', '181.46', '205.59', '362.90'),
    ('2025-07-22', '171 / T', '2367.20', '0.00', '1309.59', '3676.79', '91.92', '144.05', '183.84'),
    ('2025-08-14', '188 / T', '557490.37', '27390.45', '221054.19', '805935.01', '20148.37', '24315.96', '40296.75'),
    ('2025-08-14', '189 / T', '45.56', '25760.90', '5502.78', '31309.24', '782.73', '605.31', '1565.46'),
    ('2025-08-14', '190 / T', '9255.54', '0.00', '4749.02', '14004.56', '350.12', '522.39', '700.23'),
    ('2025-08-14', '191 / T', '3393.96', '0.00', '1802.11', '5196.07', '129.90', '198.23', '259.80'),
    ('2025-09-10', '222 / T', '411521.19', '31718.91', '210982.83', '654222.93', '16355.57', '23208.11', '32711.15'),
    ('2025-09-12', '223 / T', '27626.21', '0.00', '8720.28', '36346.49', '908.67', '959.23', '1817.32'),
    ('2025-09-12', '224 / T', '16956.85', '0.00', '9959.19', '26916.04', '672.90', '1095.51', '1345.80'),
    ('2025-10-10', '245 / T', '6449.50', '0.00', '2064.65', '8514.15', '212.86', '227.11', '425.71'),
    ('2025-10-10', '246 / T', '8950.55', '0.00', '4794.54', '13745.09', '343.62', '527.40', '687.25'),
    ('2025-10-13', '247 / T', '338391.24', '39232.96', '198796.60', '576420.80', '14410.52', '21867.63', '28821.04'),
    ('2025-11-17', '277 / T', '201019.25', '31135.38', '122362.04', '354516.67', '8862.91', '13459.82', '17725.83'),
    ('2025-11-17', '278 / T', '28042.81', '0.00', '10185.55', '38228.36', '955.71', '1120.41', '1911.42'),
    ('2025-11-17', '279 / T', '28346.23', '0.00', '16292.45', '44638.68', '1115.97', '1792.17', '2231.93'),
    ('2025-12-16', '299 / T', '139378.55', '30506.97', '100431.81', '270317.33', '6757.93', '11047.50', '13515.87'),
    ('2025-12-16', '300 / T', '10212.68', '0.00', '2904.10', '13116.78', '327.92', '319.45', '655.84'),
    ('2025-12-16', '301 / T', '16743.10', '0.00', '9433.21', '24484.25', '654.41', '1037.65', '1308.82'),
    ('2025-12-19', '306 / T', '111748.58', '0.00', '68797.46', '180546.04', '4513.65', '7567.72', '9027.30'),
    ('2026-01-16', '312 / T', '4771.14', '0.00', '2002.73', '6384.22', '169.35', '220.30', '338.69'),
    ('2026-01-16', '313 / T', '33035.73', '25750.00', '24220.96', '83006.69', '2075.16', '2664.31', '4150.33'),
    ('2026-01-19', '314 / T', '19956.54', '0.00', '19879.63', '39836.17', '995.90', '2186.76', '1991.81'),
]


def encontrar_obra_lami(Obra):
    for termo in ('ORLA DO LAMI', 'LAMI'):
        obra = Obra.objects.filter(nome_obra__iexact=termo).first()
        if obra:
            return obra
    return Obra.objects.filter(nome_obra__icontains='lami').order_by('id').first()


def carregar_orla_lami(apps, schema_editor):
    Obra = apps.get_model('obras', 'Obra')
    NotaFiscal = apps.get_model('obras', 'NotaFiscal')
    RetencaoNotaFiscal = apps.get_model('obras', 'RetencaoNotaFiscal')
    RetencaoTecnicaObra = apps.get_model('obras', 'RetencaoTecnicaObra')

    obra = encontrar_obra_lami(Obra)
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
    ) in ORLA_LAMI_NOTAS:
        data_emissao = date.fromisoformat(data_text)
        nota, _ = NotaFiscal.objects.update_or_create(
            obra=obra,
            numero=numero,
            defaults={
                'data_emissao': data_emissao,
                'valor_bruto': _d(total_bruto),
                'status': 'emitida',
                'observacoes': (
                    f'Importado da planilha Orla do Lami. Material: R$ {material}; '
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
        data_referencia=date(2025, 12, 16),
        descricao='PG RETENCAO - data nao informada na planilha',
        defaults={
            'valor': _d('80000.00'),
            'data_devolucao': date(2025, 12, 16),
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('obras', '0005_carrega_dados_ipanema_por_nome_parcial'),
    ]

    operations = [
        migrations.RunPython(carregar_orla_lami, migrations.RunPython.noop),
    ]
