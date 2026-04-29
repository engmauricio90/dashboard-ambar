from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from obras.models import DespesaObra, NotaFiscal, Obra

from .models import CentroCusto, ContaPagar, ContaReceber


class FinanceiroIntegracaoObraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='financeiro', password='senha-forte-123')
        self.client.force_login(self.user)
        self.obra = Obra.objects.create(nome_obra='Obra Financeira', cliente='Cliente X')
        self.centro = CentroCusto.objects.create(nome='Obras')

    def test_conta_receber_cria_nota_e_retencoes_na_obra(self):
        conta = ContaReceber.objects.create(
            cliente='Cliente X',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-FIN-1',
            descricao='Medicao mensal',
            data_emissao=date(2026, 4, 1),
            data_vencimento=date(2026, 4, 30),
            valor_bruto=Decimal('1000.00'),
            issqn_retido=Decimal('25.00'),
            inss_retido=Decimal('30.00'),
            retencao_tecnica=Decimal('50.00'),
        )

        nota = NotaFiscal.objects.get(obra=self.obra, numero='NF-FIN-1')
        self.assertEqual(conta.nota_fiscal, nota)
        self.assertEqual(nota.valor_bruto, Decimal('1000.00'))
        self.assertEqual(nota.retencoes.count(), 2)
        self.assertEqual(self.obra.retencoes_tecnicas_registradas.count(), 1)
        self.assertEqual(self.obra.total_retencoes_tecnicas, Decimal('50.00'))

    def test_conta_pagar_cria_despesa_na_obra(self):
        conta = ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            descricao='Material de obra',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('350.00'),
        )

        despesa = DespesaObra.objects.get(obra=self.obra, descricao='Material de obra')
        self.assertEqual(conta.despesa_obra, despesa)
        self.assertEqual(despesa.valor, Decimal('350.00'))
        self.assertEqual(self.obra.total_despesa_real, Decimal('350.00'))

    def test_dashboard_financeiro_responde(self):
        response = self.client.get(reverse('financeiro_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Financeiro')
        self.assertContains(response, 'Fluxo de caixa')

    def test_relatorio_pdf_responde_pdf(self):
        response = self.client.get(reverse('relatorio_financeiro_pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
