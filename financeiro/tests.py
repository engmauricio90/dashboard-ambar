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

    def test_lista_contas_pagar_mostra_apenas_abertas(self):
        ContaPagar.objects.create(
            fornecedor='Fornecedor Aberto',
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            descricao='Aberta',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('350.00'),
        )
        ContaPagar.objects.create(
            fornecedor='Fornecedor Pago',
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            descricao='Paga',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            data_pagamento=date(2026, 4, 21),
            valor=Decimal('200.00'),
            status=ContaPagar.STATUS_PAGO,
        )

        response = self.client.get(reverse('lista_contas_pagar'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fornecedor Aberto')
        self.assertNotContains(response, 'Fornecedor Pago')

    def test_acao_massa_marca_contas_como_pagas(self):
        conta_1 = ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            categoria='material',
            descricao='Conta 1',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('100.00'),
        )
        conta_2 = ContaPagar.objects.create(
            fornecedor='Fornecedor B',
            obra=self.obra,
            categoria='material',
            descricao='Conta 2',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('150.00'),
        )

        response = self.client.post(
            reverse('acao_massa_contas_pagar'),
            {
                'contas': [str(conta_1.id), str(conta_2.id)],
                'acao': 'pagar',
                'data_baixa': '2026-04-25',
            },
        )

        self.assertRedirects(response, reverse('lista_contas_pagas'))
        conta_1.refresh_from_db()
        conta_2.refresh_from_db()
        self.assertEqual(conta_1.status, ContaPagar.STATUS_PAGO)
        self.assertEqual(conta_1.data_pagamento, date(2026, 4, 25))
        self.assertEqual(conta_2.status, ContaPagar.STATUS_PAGO)

    def test_acao_massa_cancela_e_remove_despesa_da_obra(self):
        conta = ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            categoria='material',
            descricao='Conta cancelada',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('100.00'),
        )
        self.assertTrue(DespesaObra.objects.filter(descricao='Conta cancelada').exists())

        response = self.client.post(
            reverse('acao_massa_contas_pagar'),
            {
                'contas': [str(conta.id)],
                'acao': 'cancelar',
            },
        )

        self.assertRedirects(response, reverse('lista_contas_pagar_canceladas'))
        conta.refresh_from_db()
        self.assertEqual(conta.status, ContaPagar.STATUS_CANCELADO)
        self.assertFalse(DespesaObra.objects.filter(descricao='Conta cancelada').exists())

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
