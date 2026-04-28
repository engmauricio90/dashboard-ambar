from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from controles.models import OrcamentoRadarObra

from .models import Proposta


class PropostaTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='comercial', password='senha-forte-123')
        self.client.force_login(self.user)

    def _payload_base(self):
        return {
            'cliente': 'CYRELA',
            'tipo_execucao': 'EXECUCAO DE DRENAGEM PLUVIAL',
            'data_proposta': '2026-04-16',
            'servico_incluso': 'Escavacao, assentamento de tubulacao e recomposicao final.',
            'prazo_execucao': 'a definir',
            'forma_pagamento': 'Entrada de 30% e saldo em medicao.',
            'observacoes': 'Observacao importante.',
            'incluir_planilha': 'on',
            'bdi_percentual': '20.00',
            'local_fechamento': 'Campo Bom/RS',
            'data_encerramento': '2026-04-16',
            'engenheiro_nome': 'Eng. Civil Patrick Ruppenthal de Lima',
            'engenheiro_crea': 'CREA/RS: 198.404',
            'situacao': 'aguardando_resposta',
            'resumo-TOTAL_FORMS': '2',
            'resumo-INITIAL_FORMS': '0',
            'resumo-MIN_NUM_FORMS': '0',
            'resumo-MAX_NUM_FORMS': '1000',
            'resumo-0-ordem': '1',
            'resumo-0-descricao': 'Execucao de drenagem pluvial',
            'resumo-0-quantidade_descricao': '1 vb',
            'resumo-0-valor': '8806.00',
            'resumo-1-ordem': '',
            'resumo-1-descricao': '',
            'resumo-1-quantidade_descricao': '',
            'resumo-1-valor': '',
            'planilha-TOTAL_FORMS': '3',
            'planilha-INITIAL_FORMS': '0',
            'planilha-MIN_NUM_FORMS': '0',
            'planilha-MAX_NUM_FORMS': '1000',
            'planilha-0-ordem': '1',
            'planilha-0-descricao': 'Escavacao mecanizada',
            'planilha-0-unidade': 'vb',
            'planilha-0-quantidade': '1',
            'planilha-0-preco_unit_material': '0',
            'planilha-0-preco_unit_mao_obra': '1680.00',
            'planilha-1-ordem': '2',
            'planilha-1-descricao': 'Tubo concreto DN 300',
            'planilha-1-unidade': 'm',
            'planilha-1-quantidade': '15',
            'planilha-1-preco_unit_material': '137.20',
            'planilha-1-preco_unit_mao_obra': '56.00',
            'planilha-2-ordem': '',
            'planilha-2-descricao': '',
            'planilha-2-unidade': '',
            'planilha-2-quantidade': '',
            'planilha-2-preco_unit_material': '',
            'planilha-2-preco_unit_mao_obra': '',
        }

    def test_cria_proposta_com_numero_e_radar(self):
        response = self.client.post(reverse('nova_proposta'), self._payload_base())

        proposta = Proposta.objects.get()
        self.assertRedirects(response, reverse('editar_proposta', args=[proposta.id]))
        self.assertEqual(proposta.numero_formatado, '001/2026')
        self.assertEqual(proposta.radar.numero, '001/2026')
        self.assertEqual(proposta.radar.cliente, 'CYRELA')
        self.assertEqual(proposta.radar.situacao, 'aguardando_resposta')
        self.assertEqual(proposta.itens_resumo.count(), 1)
        self.assertEqual(proposta.itens_planilha.count(), 2)
        self.assertEqual(proposta.total_resumo, Decimal('8806.00'))
        self.assertGreater(proposta.total_planilha, Decimal('0'))

    def test_lista_propostas_carrega(self):
        proposta = Proposta.objects.create(
            numero_sequencial=1,
            ano=2026,
            cliente='Cliente Teste',
            tipo_execucao='Execucao teste',
            data_proposta='2026-04-16',
            servico_incluso='Servico teste',
        )
        proposta.sincronizar_radar()

        response = self.client.get(reverse('lista_propostas'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Propostas Comerciais')
        self.assertContains(response, 'Cliente Teste')
        self.assertTrue(OrcamentoRadarObra.objects.filter(numero='001/2026').exists())

    def test_cria_proposta_aceitando_virgula_nos_valores(self):
        payload = self._payload_base()
        payload['bdi_percentual'] = '20,00'
        payload['planilha-0-preco_unit_mao_obra'] = '1.680,00'
        payload['planilha-1-preco_unit_material'] = '137,20'
        payload['planilha-1-preco_unit_mao_obra'] = '56,00'

        response = self.client.post(reverse('nova_proposta'), payload)

        proposta = Proposta.objects.latest('id')
        self.assertRedirects(response, reverse('editar_proposta', args=[proposta.id]))
        self.assertGreater(proposta.total_planilha, Decimal('0'))
