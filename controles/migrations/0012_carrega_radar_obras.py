from datetime import date
from decimal import Decimal

from django.db import migrations


RADAR_OBRAS = [
    ('RAD-2025-001', date(2025, 6, 10), '6860834.31', 'Drenagem e eletrica', 'Hospital Mae de Deus', 'aguardando_resposta'),
    ('RAD-2025-002', date(2025, 6, 18), '1116938.24', 'Construcao civil', 'Agrofel', 'aguardando_resposta'),
    ('RAD-2025-003', date(2025, 9, 17), '6377201.27', 'Terraplanagem, drenagem e pavimentacao', 'Fort Atacadista', 'aguardando_resposta'),
    ('RAD-2025-004', date(2025, 11, 10), '4610467.40', 'Execucao clinica tomografia', 'Cliente Adriano', 'aguardando_resposta'),
    ('RAD-2025-005', date(2025, 11, 12), '2729008.86', 'Pavimentacao', 'Terraville', 'aguardando_resposta'),
    ('RAD-2025-006', date(2025, 12, 9), '0.00', 'Revitalizacao de calcadas Canoas', 'MAC', 'aguardando_resposta'),
    ('RAD-2025-007', date(2025, 12, 10), '1200.00', 'Alas', 'Novalternativa', 'fechada'),
    ('RAD-2025-008', date(2025, 12, 17), '243075.39', 'Drenagem, rede de agua e pavimentacao', 'Flavio Rosa', 'aguardando_resposta'),
    ('RAD-2026-001', date(2026, 1, 12), '832507.95', 'Loteamento', 'ALF', 'aguardando_resposta'),
    ('RAD-2026-002', date(2026, 1, 20), '2940515.45', 'Terraplanagem Erechim', 'Obra Pronta', 'aguardando_resposta'),
    ('RAD-2026-003', date(2026, 1, 21), '1209033.04', 'Terraplanagem', 'Suelo', 'fechada'),
    ('RAD-2026-004', date(2026, 1, 23), '391431.00', 'Rede cloacal', 'MC3', 'aguardando_resposta'),
    ('RAD-2026-005', date(2026, 1, 23), '268752.00', 'Rede de agua', 'MC3', 'aguardando_resposta'),
    ('RAD-2026-006', date(2026, 1, 26), '229972.09', 'Pavimentacao', 'Savar', 'aguardando_resposta'),
    ('RAD-2026-007', date(2026, 1, 26), '106344.91', 'Reforma escritorio', 'GMA Sul Engenharia', 'aguardando_resposta'),
    ('RAD-2026-008', date(2026, 1, 30), '1926623.35', 'Terraplanagem e pavimentacao', 'Reserva Clube RNI', 'nao_foi_para_frente'),
    ('RAD-2026-009', date(2026, 1, 28), '495000.00', 'Bota-fora', 'Savar', 'aguardando_resposta'),
    ('RAD-2026-010', date(2026, 1, 30), '13802196.04', 'Loteamento e condominios', 'Suelo', 'aguardando_resposta'),
    ('RAD-2026-011', date(2026, 2, 5), '363138.00', 'Reboco e pintura', 'Dwell', 'aguardando_resposta'),
    ('RAD-2026-012', date(2026, 2, 13), '308627.20', 'Drenagem pluvial e esgoto POA', 'MC3', 'aguardando_resposta'),
    ('RAD-2026-013', date(2026, 2, 14), '5739047.33', 'Terraplanagem, redes e pavimentacao', 'Pro Engenharia', 'aguardando_resposta'),
    ('RAD-2026-014', date(2026, 2, 14), '1247296.19', 'Terraplanagem, drenagem e pavimentacao (Contrapartida)', 'Pro Engenharia', 'aguardando_resposta'),
    ('RAD-2026-015', date(2026, 2, 18), '634891.23', 'Terraplanagem Itaim Bibi', 'Obra Pronta', 'aguardando_resposta'),
    ('RAD-2026-016', date(2026, 2, 19), '250742.80', 'Redes pluvial, agua e esgoto em Canoas', 'Abaco', 'aguardando_resposta'),
    ('RAD-2026-017', date(2026, 2, 19), '3500000.00', 'Gabioes Sao Jose', 'Obra Pronta', 'aguardando_resposta'),
    ('RAD-2026-018', date(2026, 2, 20), '23489.60', 'Impermeabilizacao de paredes', 'Kley Hertz', 'aguardando_resposta'),
    ('RAD-2026-019', date(2026, 2, 20), '453000.00', 'Pavimentacao', 'Residencial Dona Celia', 'aguardando_resposta'),
    ('RAD-2026-020', date(2026, 3, 3), '196000.00', 'Redes pluvial, agua e esgoto', 'Cassol', 'fechada'),
    ('RAD-2026-021', date(2026, 3, 3), '35800.00', 'Pintura e impermeabilizacao', '', 'aguardando_resposta'),
    ('RAD-2026-022', date(2026, 3, 6), '791889.48', 'Drenagem', 'MAC', 'aguardando_resposta'),
    ('RAD-2026-023', date(2026, 3, 9), '385100.80', 'Pavimentacao', 'Execute Engenharia', 'aguardando_resposta'),
    ('RAD-2026-024', date(2026, 3, 11), '745875.61', 'Drenagem, redes e pavimentacao', 'Giancarlo', 'aguardando_resposta'),
    ('RAD-2026-025', date(2026, 3, 11), '118465.20', 'Terraplanagem', '', 'aguardando_resposta'),
    ('RAD-2026-026', date(2026, 3, 13), '615066.78', 'Execucao de Redes de Drenagem e Agua', 'Baliza', 'aguardando_resposta'),
    ('RAD-2026-027', date(2026, 3, 13), '232941.15', 'Execucao de Redes de Esgoto e Agua', 'Baliza', 'aguardando_resposta'),
    ('RAD-2026-028', date(2026, 3, 20), '400000.00', 'Reforma da rua da caldeira', 'Santher', 'aguardando_resposta'),
    ('RAD-2026-029', date(2026, 3, 24), '513684.06', 'Pavimentacao', 'DBN', 'aguardando_resposta'),
    ('RAD-2026-030', date(2026, 3, 30), '1712878.55', 'Mao de obra blocos de fundacao', 'UDF', 'aguardando_resposta'),
    ('RAD-2026-031', date(2026, 3, 31), '114646.46', 'Rede de Esgoto e Agua', 'Uilian', 'aguardando_resposta'),
    ('RAD-2026-032', date(2026, 3, 27), '330374.80', 'Mao de obra drenagem e Pavimentacao', 'Uilian (Garopaba)', 'aguardando_resposta'),
    ('RAD-2026-033', date(2026, 3, 25), '240032.70', 'Mao de obra redes de agua, esgoto e drenagem', 'Uilian (Garopaba)', 'aguardando_resposta'),
    ('RAD-2026-034', date(2026, 3, 26), '149367.53', 'Rede de agua', 'Baliza (Uilian)', 'aguardando_resposta'),
    ('RAD-2026-035', date(2026, 4, 1), '2650.00', 'Projeto estrutural', 'Jennifer e Gustavo', 'aguardando_resposta'),
    ('RAD-2026-036', date(2026, 4, 15), '497752.50', 'Pavimentacao', 'Cassol', 'aguardando_resposta'),
    ('RAD-2026-037', date(2026, 4, 15), '58288.23', 'Pavimentacao', 'Terraville', 'aguardando_resposta'),
    ('RAD-2026-038', date(2026, 4, 7), '95144.00', 'Reforma da churrascaria', 'GAM3', 'aguardando_resposta'),
    ('RAD-2026-039', date(2026, 4, 16), '8806.00', 'drenagem orla 3', 'CYRELA', 'aguardando_resposta'),
    ('RAD-2026-040', date(2026, 4, 17), '1062000.00', 'Casa na praia', 'Familia brehm', 'aguardando_resposta'),
    ('RAD-2026-041', date(2026, 4, 10), '252574.04', 'Pavimentacao e drenagem - Glorinha', 'Bhios', 'aguardando_resposta'),
    ('RAD-2026-042', date(2026, 4, 7), '11660753.53', 'Loteamento 2 - Passo de Torres', '', 'aguardando_resposta'),
    ('RAD-2026-043', date(2026, 4, 7), '3361480.33', 'Loteamento 1 - Passo de Torres', '', 'aguardando_resposta'),
    ('RAD-2026-044', date(2026, 4, 6), '74747.09', 'Germania Park Mall', 'Phorbis', 'aguardando_resposta'),
]


def carregar_radar(apps, schema_editor):
    OrcamentoRadarObra = apps.get_model('controles', 'OrcamentoRadarObra')
    for numero, data_orcamento, valor, descricao, cliente, situacao in RADAR_OBRAS:
        OrcamentoRadarObra.objects.update_or_create(
            numero=numero,
            defaults={
                'cliente': cliente or 'Nao informado',
                'descricao': descricao,
                'data_orcamento': data_orcamento,
                'situacao': situacao,
                'valor_estimado': Decimal(valor),
                'responsavel': '',
                'observacoes': 'Importado da planilha de radar de obras.',
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('controles', '0011_contratoconcretagem_fornecedor_cadastro_and_more'),
    ]

    operations = [
        migrations.RunPython(carregar_radar, migrations.RunPython.noop),
    ]
