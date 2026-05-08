from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from obras.models import DespesaObra, NotaFiscal, Obra
from controles.models import ItemOrdemCompraGeral, NotaFiscalOrdemCompraGeral, OrdemCompraGeral

from .models import CentroCusto, ContaPagar, ContaReceber, ItemContaPagarOrdemCompra


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

    def test_conta_pagar_com_oc_cria_nota_vinculada_na_oc(self):
        ordem = OrdemCompraGeral.objects.create(
            fornecedor='Fornecedor OC',
            obra=self.obra,
            centro_custo=self.centro,
            categoria_despesa='material',
            data_emissao=date(2026, 5, 1),
        )
        item = ItemOrdemCompraGeral.objects.create(
            ordem=ordem,
            item=1,
            descricao='Po de brita',
            quantidade=Decimal('200.00'),
            unidade='ton',
            valor_unitario=Decimal('80.00'),
        )
        item_2 = ItemOrdemCompraGeral.objects.create(
            ordem=ordem,
            item=2,
            descricao='Pedrisco',
            quantidade=Decimal('100.00'),
            unidade='ton',
            valor_unitario=Decimal('50.00'),
        )

        conta = ContaPagar.objects.create(
            fornecedor='Fornecedor OC',
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            ordem_compra=ordem,
            numero_nf='1001',
            descricao='NF 1001 - po de brita',
            data_emissao=date(2026, 5, 8),
            data_vencimento=date(2026, 5, 20),
            valor=Decimal('0.00'),
        )
        ItemContaPagarOrdemCompra.objects.create(conta=conta, item_ordem_compra=item, quantidade=Decimal('30.00'))
        ItemContaPagarOrdemCompra.objects.create(conta=conta, item_ordem_compra=item_2, quantidade=Decimal('10.00'))
        conta.recalcular_valor_por_itens_oc()
        conta.save()

        notas = NotaFiscalOrdemCompraGeral.objects.order_by('item__item')
        self.assertEqual(notas.count(), 2)
        self.assertEqual(notas[0].conta_pagar, conta)
        self.assertEqual(notas[0].item, item)
        self.assertEqual(notas[0].quantidade, Decimal('30.00'))
        self.assertEqual(notas[0].valor_total, Decimal('2400.00'))
        self.assertEqual(notas[1].item, item_2)
        self.assertEqual(notas[1].valor_total, Decimal('500.00'))
        self.assertEqual(conta.valor, Decimal('2900.00'))
        self.assertEqual(ordem.total_faturado, Decimal('2900.00'))
        self.assertEqual(item.saldo_quantidade, Decimal('170.00'))

    def test_form_conta_pagar_permite_sem_oc(self):
        response = self.client.post(
            reverse('nova_conta_pagar'),
            {
                'fornecedor': 'Fornecedor sem OC',
                'fornecedor_cadastro': '',
                'obra': self.obra.id,
                'centro_custo': self.centro.id,
                'categoria': 'material',
                'ordem_compra': '',
                'numero_nf': '',
                'descricao': 'Despesa sem OC',
                'data_emissao': '2026-05-08',
                'data_vencimento': '2026-05-20',
                'data_pagamento': '',
                'valor': '100.00',
                'status': ContaPagar.STATUS_ABERTO,
                'observacoes': '',
                'itens_oc-TOTAL_FORMS': '5',
                'itens_oc-INITIAL_FORMS': '0',
                'itens_oc-MIN_NUM_FORMS': '0',
                'itens_oc-MAX_NUM_FORMS': '1000',
                'itens_oc-0-item_ordem_compra': '',
                'itens_oc-0-quantidade': '',
                'itens_oc-1-item_ordem_compra': '',
                'itens_oc-1-quantidade': '',
                'itens_oc-2-item_ordem_compra': '',
                'itens_oc-2-quantidade': '',
                'itens_oc-3-item_ordem_compra': '',
                'itens_oc-3-quantidade': '',
                'itens_oc-4-item_ordem_compra': '',
                'itens_oc-4-quantidade': '',
            },
        )

        self.assertRedirects(response, reverse('lista_contas_pagar'))
        self.assertEqual(ContaPagar.objects.get().descricao, 'Despesa sem OC')
        self.assertFalse(NotaFiscalOrdemCompraGeral.objects.exists())

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
        self.assertEqual(conta_1.valor_pago, Decimal('100.00'))
        self.assertEqual(conta_2.status, ContaPagar.STATUS_PAGO)

    def test_conta_paga_aceita_valor_pago_diferente(self):
        conta = ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            categoria='material',
            descricao='Conta com juros',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('100.00'),
        )

        response = self.client.post(
            reverse('editar_conta_pagar', args=[conta.id]),
            {
                'fornecedor': 'Fornecedor A',
                'fornecedor_cadastro': '',
                'obra': self.obra.id,
                'centro_custo': '',
                'categoria': 'material',
                'ordem_compra': '',
                'numero_nf': '',
                'descricao': 'Conta com juros',
                'data_emissao': '2026-04-02',
                'data_vencimento': '2026-04-20',
                'data_pagamento': '2026-04-25',
                'valor': '100.00',
                'valor_pago': '112.50',
                'status': ContaPagar.STATUS_PAGO,
                'observacoes': '',
                'itens_oc-TOTAL_FORMS': '5',
                'itens_oc-INITIAL_FORMS': '0',
                'itens_oc-MIN_NUM_FORMS': '0',
                'itens_oc-MAX_NUM_FORMS': '1000',
                'itens_oc-0-item_ordem_compra': '',
                'itens_oc-0-quantidade': '',
                'itens_oc-1-item_ordem_compra': '',
                'itens_oc-1-quantidade': '',
                'itens_oc-2-item_ordem_compra': '',
                'itens_oc-2-quantidade': '',
                'itens_oc-3-item_ordem_compra': '',
                'itens_oc-3-quantidade': '',
                'itens_oc-4-item_ordem_compra': '',
                'itens_oc-4-quantidade': '',
            },
        )

        self.assertRedirects(response, reverse('lista_contas_pagar'))
        conta.refresh_from_db()
        self.assertEqual(conta.valor_pago_efetivo, Decimal('112.50'))
        self.assertEqual(conta.diferenca_pagamento, Decimal('12.50'))

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
