from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from obras.models import DespesaObra, NotaFiscal, Obra, RetencaoTecnicaObra
from controles.models import ItemOrdemCompraGeral, NotaFiscalOrdemCompraGeral, OrdemCompraGeral

from .models import CentroCusto, ContaPagar, ContaReceber, Fornecedor, ItemContaPagarOrdemCompra


class FinanceiroIntegracaoObraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='financeiro', password='senha-forte-123')
        self.user.groups.add(Group.objects.get_or_create(name='Financeiro')[0])
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

    def test_form_conta_receber_usa_cliente_da_obra_e_cria_em_aberto(self):
        response_get = self.client.get(reverse('nova_conta_receber'))

        self.assertEqual(response_get.status_code, 200)
        self.assertNotContains(response_get, 'name="cliente"')
        self.assertNotContains(response_get, 'name="status"')
        self.assertNotContains(response_get, 'name="data_recebimento"')

        response = self.client.post(
            reverse('nova_conta_receber'),
            {
                'obra': self.obra.id,
                'centro_custo': self.centro.id,
                'numero_nf': 'NF-FORM-1',
                'descricao': 'Receita pelo formulario',
                'data_emissao': '2026-04-01',
                'data_vencimento': '2026-04-30',
                'valor_bruto': '1000.00',
                'issqn_retido': '25.00',
                'inss_retido': '30.00',
                'retencao_tecnica': '50.00',
                'outras_retencoes': '0.00',
                'observacoes': '',
            },
        )

        self.assertRedirects(response, reverse('lista_contas_receber'))
        conta = ContaReceber.objects.get(numero_nf='NF-FORM-1')
        self.assertEqual(conta.cliente, 'Cliente X')
        self.assertEqual(conta.status, ContaReceber.STATUS_ABERTO)
        self.assertIsNone(conta.data_recebimento)
        self.assertEqual(conta.nota_fiscal.status, NotaFiscal.STATUS_EMITIDA)

    def test_recebimento_conta_receber_tem_tela_propria_com_data(self):
        conta = ContaReceber.objects.create(
            cliente='Cliente X',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-REC',
            descricao='NF a receber',
            data_emissao=date(2026, 4, 1),
            data_vencimento=date(2026, 4, 30),
            valor_bruto=Decimal('1000.00'),
        )

        response_get = self.client.get(reverse('baixar_conta_receber', args=[conta.id]))
        self.assertContains(response_get, 'Registrar recebimento')
        self.assertContains(response_get, 'name="data_recebimento"')

        response = self.client.post(
            reverse('baixar_conta_receber', args=[conta.id]),
            {
                'data_recebimento': '2026-05-05',
                'observacoes': 'Recebido via transferencia',
            },
        )

        self.assertRedirects(response, reverse('lista_contas_receber'))
        conta.refresh_from_db()
        self.assertEqual(conta.status, ContaReceber.STATUS_RECEBIDO)
        self.assertEqual(conta.data_recebimento, date(2026, 5, 5))
        self.assertIn('Recebido via transferencia', conta.observacoes)
        self.assertEqual(conta.nota_fiscal.status, NotaFiscal.STATUS_RECEBIDA)

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

    def test_conta_pagar_sem_obra_remove_despesa_anterior(self):
        conta = ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            descricao='Despesa removida',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('350.00'),
        )
        despesa_id = conta.despesa_obra_id

        conta.obra = None
        conta.save()

        conta.refresh_from_db()
        self.assertIsNone(conta.despesa_obra)
        self.assertFalse(DespesaObra.objects.filter(id=despesa_id).exists())

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

        item.valor_unitario = Decimal('90.00')
        item.save()
        self.assertEqual(item.valor_total, Decimal('18000.00'))

        nota = notas[0]
        nota.quantidade = Decimal('20.00')
        nota.valor_unitario = Decimal('90.00')
        nota.save()
        self.assertEqual(nota.valor_total, Decimal('1800.00'))

    def test_form_conta_pagar_permite_sem_oc(self):
        response_get = self.client.get(reverse('nova_conta_pagar'))
        self.assertNotContains(response_get, 'name="data_pagamento"')
        self.assertNotContains(response_get, 'name="valor_pago"')
        self.assertNotContains(response_get, 'name="status"')

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
        conta = ContaPagar.objects.get()
        self.assertEqual(conta.descricao, 'Despesa sem OC')
        self.assertEqual(conta.status, ContaPagar.STATUS_ABERTO)
        self.assertIsNone(conta.data_pagamento)
        self.assertEqual(conta.valor_pago, Decimal('0'))
        self.assertFalse(NotaFiscalOrdemCompraGeral.objects.exists())

    def test_form_conta_pagar_adiciona_itens_oc_por_botao(self):
        response = self.client.get(reverse('nova_conta_pagar'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Adicionar item')
        self.assertContains(response, 'name="itens_oc-TOTAL_FORMS" value="0"')

    def test_exclui_fornecedor_sem_apagar_lancamentos(self):
        fornecedor = Fornecedor.objects.create(nome='Fornecedor Cadastro', cpf_cnpj='00.000.000/0001-00')
        conta = ContaPagar.objects.create(
            fornecedor='Fornecedor Cadastro',
            fornecedor_cadastro=fornecedor,
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            descricao='Despesa vinculada',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('100.00'),
        )

        response_get = self.client.get(reverse('excluir_fornecedor', args=[fornecedor.id]))
        self.assertContains(response_get, 'Excluir fornecedor')

        response_post = self.client.post(reverse('excluir_fornecedor', args=[fornecedor.id]))

        self.assertRedirects(response_post, reverse('lista_fornecedores'))
        self.assertFalse(Fornecedor.objects.filter(id=fornecedor.id).exists())
        conta.refresh_from_db()
        self.assertEqual(conta.fornecedor, 'Fornecedor Cadastro')
        self.assertIsNone(conta.fornecedor_cadastro)

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

    def test_tela_pagamento_aceita_valor_pago_diferente(self):
        conta = ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            categoria='material',
            descricao='Conta com juros',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('100.00'),
        )

        response_get = self.client.get(reverse('baixar_conta_pagar', args=[conta.id]))
        self.assertContains(response_get, 'Registrar pagamento')
        self.assertContains(response_get, 'name="data_pagamento"')
        self.assertContains(response_get, 'name="valor_pago"')

        response = self.client.post(
            reverse('baixar_conta_pagar', args=[conta.id]),
            {
                'data_pagamento': '2026-04-25',
                'valor_pago': '112.50',
                'observacoes': 'Pago com juros',
            },
        )

        self.assertRedirects(response, reverse('lista_contas_pagas'))
        conta.refresh_from_db()
        self.assertEqual(conta.status, ContaPagar.STATUS_PAGO)
        self.assertEqual(conta.data_pagamento, date(2026, 4, 25))
        self.assertEqual(conta.valor_pago_efetivo, Decimal('112.50'))
        self.assertEqual(conta.diferenca_pagamento, Decimal('12.50'))
        self.assertEqual(conta.despesa_obra.valor, Decimal('112.50'))
        self.assertIn('Pago com juros', conta.observacoes)

    def test_pagamento_conta_pagar_tem_tela_propria(self):
        conta = ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            categoria='material',
            descricao='Conta baixa post',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 20),
            valor=Decimal('100.00'),
        )

        response_get = self.client.get(reverse('baixar_conta_pagar', args=[conta.id]))
        self.assertEqual(response_get.status_code, 200)
        self.assertContains(response_get, 'Registrar pagamento')

        response_post = self.client.post(
            reverse('baixar_conta_pagar', args=[conta.id]),
            {
                'data_pagamento': '2026-04-30',
                'valor_pago': '100.00',
                'observacoes': '',
            },
        )
        self.assertRedirects(response_post, reverse('lista_contas_pagas'))
        conta.refresh_from_db()
        self.assertEqual(conta.status, ContaPagar.STATUS_PAGO)

    def test_conta_receber_cancelada_nao_entra_no_total_da_obra(self):
        ContaReceber.objects.create(
            cliente='Cliente X',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-OK',
            descricao='NF valida',
            data_emissao=date(2026, 4, 1),
            data_vencimento=date(2026, 4, 30),
            valor_bruto=Decimal('1000.00'),
            issqn_retido=Decimal('25.00'),
        )
        ContaReceber.objects.create(
            cliente='Cliente X',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-CAN',
            descricao='NF cancelada',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 30),
            valor_bruto=Decimal('500.00'),
            issqn_retido=Decimal('10.00'),
            status=ContaReceber.STATUS_CANCELADO,
        )

        self.assertEqual(self.obra.total_notas_fiscais, Decimal('1000.00'))
        self.assertEqual(self.obra.total_retencoes_nf, Decimal('25.00'))

    def test_conta_receber_cancelada_nao_mostra_botao_receber(self):
        ContaReceber.objects.create(
            cliente='Cliente X',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-CAN-BOTAO',
            descricao='NF cancelada',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 30),
            valor_bruto=Decimal('500.00'),
            status=ContaReceber.STATUS_CANCELADO,
        )

        response = self.client.get(reverse('lista_contas_receber'))

        self.assertContains(response, 'Cancelado')
        self.assertNotContains(response, 'btn-outline-success">Receber</button>')

    def test_conta_receber_cancelada_nao_pode_ser_baixada_por_post(self):
        conta = ContaReceber.objects.create(
            cliente='Cliente X',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-CAN-POST',
            descricao='NF cancelada',
            data_emissao=date(2026, 4, 2),
            data_vencimento=date(2026, 4, 30),
            valor_bruto=Decimal('500.00'),
            status=ContaReceber.STATUS_CANCELADO,
        )

        response = self.client.post(reverse('baixar_conta_receber', args=[conta.id]))

        self.assertRedirects(response, reverse('lista_contas_receber'))
        conta.refresh_from_db()
        self.assertEqual(conta.status, ContaReceber.STATUS_CANCELADO)
        self.assertIsNone(conta.data_recebimento)

    def test_conta_receber_sem_obra_desvincula_nota_e_retencao_tecnica(self):
        conta = ContaReceber.objects.create(
            cliente='Cliente X',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-DESV',
            descricao='NF desvinculada',
            data_emissao=date(2026, 4, 1),
            data_vencimento=date(2026, 4, 30),
            valor_bruto=Decimal('1000.00'),
            retencao_tecnica=Decimal('50.00'),
        )
        nota_id = conta.nota_fiscal_id
        retencao_id = conta.retencao_tecnica_obra_id

        conta.obra = None
        conta.save()

        conta.refresh_from_db()
        nota = NotaFiscal.objects.get(id=nota_id)
        self.assertEqual(nota.status, NotaFiscal.STATUS_CANCELADA)
        self.assertIsNone(conta.nota_fiscal)
        self.assertIsNone(conta.retencao_tecnica_obra)
        self.assertFalse(RetencaoTecnicaObra.objects.filter(id=retencao_id).exists())

    def test_conta_receber_cancelada_remove_retencao_tecnica(self):
        conta = ContaReceber.objects.create(
            cliente='Cliente X',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-RET-CAN',
            descricao='NF com retencao cancelada',
            data_emissao=date(2026, 4, 1),
            data_vencimento=date(2026, 4, 30),
            valor_bruto=Decimal('1000.00'),
            retencao_tecnica=Decimal('50.00'),
        )
        retencao_id = conta.retencao_tecnica_obra_id

        conta.status = ContaReceber.STATUS_CANCELADO
        conta.save()

        conta.refresh_from_db()
        self.assertEqual(conta.nota_fiscal.status, NotaFiscal.STATUS_CANCELADA)
        self.assertIsNone(conta.retencao_tecnica_obra)
        self.assertFalse(RetencaoTecnicaObra.objects.filter(id=retencao_id).exists())

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

    def test_tela_importacao_credores_explica_modelo_csv(self):
        response = self.client.get(reverse('importar_contas_pagar_sienge'))

        self.assertContains(response, 'Como preparar o arquivo no Excel')
        self.assertContains(response, 'Colunas do CSV padrao')
        self.assertContains(response, '<code>fornecedor</code>')
        self.assertContains(response, '<code>data_vencimento</code>')
        self.assertContains(response, '<code>valor_pago</code>')
        self.assertContains(response, 'fornecedor;cpf_cnpj;obra;centro_custo')

    def test_importa_despesas_csv_padrao_ambar(self):
        Obra.objects.create(nome_obra='Orla de Ipanema')
        csv_text = (
            'fornecedor;cpf_cnpj;obra;centro_custo;categoria;numero_nf;descricao;data_emissao;data_vencimento;valor;status;data_pagamento;valor_pago;observacoes;codigo_externo\n'
            'Fornecedor Obra;00.000.000/0001-00;Orla de Ipanema;;material;NFM. 123;Compra de tubos;01/04/2026;08/04/2026;1.005,00;aberto;;;;AMB-1\n'
            'Fornecedor Pago;;;Maquinas E Veiculos;equipamento;NFS. 88;Manutencao maquina;10/05/2026;10/05/2026;500,00;pago;12/05/2026;515,00;Pago com acrescimo;AMB-2\n'
        )
        arquivo = SimpleUploadedFile('despesas.csv', csv_text.encode('utf-8-sig'), content_type='text/csv')

        response = self.client.post(
            reverse('importar_contas_pagar_sienge'),
            {'tipo_relatorio': 'aberto', 'arquivo': arquivo},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContaPagar.objects.count(), 2)
        conta_obra = ContaPagar.objects.get(codigo_externo='AMB-1')
        self.assertEqual(conta_obra.obra.nome_obra, 'Orla de Ipanema')
        self.assertEqual(conta_obra.categoria, 'material')
        self.assertEqual(conta_obra.status, ContaPagar.STATUS_ABERTO)
        self.assertEqual(conta_obra.valor, Decimal('1005.00'))
        self.assertTrue(DespesaObra.objects.filter(obra__nome_obra='Orla de Ipanema', valor=Decimal('1005.00')).exists())
        conta_paga = ContaPagar.objects.get(codigo_externo='AMB-2')
        self.assertEqual(conta_paga.centro_custo.nome, 'Maquinas E Veiculos')
        self.assertEqual(conta_paga.status, ContaPagar.STATUS_PAGO)
        self.assertEqual(conta_paga.data_pagamento, date(2026, 5, 12))
        self.assertEqual(conta_paga.valor_pago, Decimal('515.00'))
        self.assertEqual(conta_paga.diferenca_pagamento, Decimal('15.00'))

    def test_importa_credores_sienge_cria_contas_e_despesas(self):
        Obra.objects.create(nome_obra='IPANEMA')
        csv_text = (
            '"";\n'
            '"Centro de Custo: ";"4 - Orla de Ipanema";\n'
            '"Credor";"Documento";"Lançamento";"Qt.";"Ind.";"Data vencto";"%";"Dias";"Valor no vencto";"Acréscimo";"Desconto";"Total";\n'
            '"Fornecedor Obra";"NFM. 123";"1706/1";"1";"0";"08/04/2026";"100,00";"34";"1.000,00";"10,00";"5,00";"1.005,00";\n'
            '"                          Obs: BOLETO";\n'
            '"Centro de Custo: ";"14 - Maquinas E Veículos";\n'
            '"Credor";"Documento";"Lançamento";"Qt.";"Ind.";"Data vencto";"%";"Dias";"Valor no vencto";"Acréscimo";"Desconto";"Total";\n'
            '"Fornecedor Centro";"NFS. 88";"2000/1";"1";"0";"10/05/2026";"100,00";"0";"500,00";"0,00";"0,00";"500,00";\n'
        )
        arquivo = SimpleUploadedFile('credores.csv', csv_text.encode('cp1252'), content_type='text/csv')

        response = self.client.post(
            reverse('importar_contas_pagar_sienge'),
            {'tipo_relatorio': 'aberto', 'arquivo': arquivo},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContaPagar.objects.count(), 2)
        conta_obra = ContaPagar.objects.get(fornecedor='Fornecedor Obra')
        self.assertEqual(conta_obra.obra.nome_obra, 'Orla de Ipanema')
        self.assertIsNone(conta_obra.centro_custo)
        self.assertEqual(conta_obra.valor, Decimal('1005.00'))
        self.assertTrue(DespesaObra.objects.filter(obra__nome_obra='Orla de Ipanema', valor=Decimal('1005.00')).exists())
        self.assertIn('BOLETO', conta_obra.observacoes)
        conta_centro = ContaPagar.objects.get(fornecedor='Fornecedor Centro')
        self.assertIsNone(conta_centro.obra)
        self.assertEqual(conta_centro.centro_custo.nome, 'Maquinas E Veículos')

    def test_importa_credores_sienge_e_idempotente(self):
        csv_text = (
            '"Centro de Custo: ";"35 - Orla 1 - Ambulantes";\n'
            '"Credor";"Documento";"Lançamento";"Qt.";"Ind.";"Data vencto";"%";"Dias";"Valor no vencto";"Acréscimo";"Desconto";"Total";\n'
            '"Fornecedor Orla";"NFM. 77";"3000/1";"1";"0";"12/05/2026";"100,00";"0";"300,00";"0,00";"0,00";"300,00";\n'
        )

        for _ in range(2):
            arquivo = SimpleUploadedFile('credores.csv', csv_text.encode('cp1252'), content_type='text/csv')
            self.client.post(
                reverse('importar_contas_pagar_sienge'),
                {'tipo_relatorio': 'aberto', 'arquivo': arquivo},
            )

        self.assertEqual(ContaPagar.objects.count(), 1)
        conta = ContaPagar.objects.get()
        self.assertEqual(conta.obra.nome_obra, 'ORLA 1')

    def test_reimportacao_preserva_status_baixado(self):
        csv_text = (
            '"Centro de Custo: ";"35 - Orla 1 - Ambulantes";\n'
            '"Credor";"Documento";"Lançamento";"Qt.";"Ind.";"Data vencto";"%";"Dias";"Valor no vencto";"Acréscimo";"Desconto";"Total";\n'
            '"Fornecedor Orla";"NFM. 77";"3000/1";"1";"0";"12/05/2026";"100,00";"0";"300,00";"0,00";"0,00";"300,00";\n'
        )

        arquivo = SimpleUploadedFile('credores.csv', csv_text.encode('cp1252'), content_type='text/csv')
        self.client.post(
            reverse('importar_contas_pagar_sienge'),
            {'tipo_relatorio': 'aberto', 'arquivo': arquivo},
        )
        conta = ContaPagar.objects.get()
        conta.status = ContaPagar.STATUS_PAGO
        conta.data_pagamento = date(2026, 5, 20)
        conta.valor_pago = Decimal('305.00')
        conta.save()

        arquivo = SimpleUploadedFile('credores.csv', csv_text.encode('cp1252'), content_type='text/csv')
        self.client.post(
            reverse('importar_contas_pagar_sienge'),
            {'tipo_relatorio': 'aberto', 'arquivo': arquivo},
        )

        conta.refresh_from_db()
        self.assertEqual(conta.status, ContaPagar.STATUS_PAGO)
        self.assertEqual(conta.valor_pago, Decimal('305.00'))

    def test_importa_credores_pagos_sienge_cria_contas_pagas(self):
        csv_text = (
            'Centro de custo;4 - Orla de Ipanema;;;;;;;;;\n'
            'Credor;Cd. cred.;Documento;Lançamento;Qt.;Dt. pagto.;Seq.;Valor baixa;Acréscimo;Desconto;Líquido\n'
            'Fornecedor Pago;133;NFM.7284;2548/1;1;13/06/2025;1;1.000,00T;15,50;0;1.015,50\n'
            'Centro de custo;14 - Maquinas E Veículos;;;;;;;;;\n'
            'Credor;Cd. cred.;Documento;Lançamento;Qt.;Dt. pagto.;Seq.;Valor baixa;Acréscimo;Desconto;Líquido\n'
            'Fornecedor Centro Pago;200;NFS.10;3000/1;1;14/06/2025;1;500,00T;0;25,00;475,00\n'
        )
        arquivo = SimpleUploadedFile('pagas.csv', csv_text.encode('cp1252'), content_type='text/csv')

        response = self.client.post(
            reverse('importar_contas_pagar_sienge'),
            {'tipo_relatorio': 'pago', 'arquivo': arquivo},
        )

        self.assertEqual(response.status_code, 200)
        conta_obra = ContaPagar.objects.get(fornecedor='Fornecedor Pago')
        self.assertEqual(conta_obra.status, ContaPagar.STATUS_PAGO)
        self.assertEqual(conta_obra.data_pagamento, date(2025, 6, 13))
        self.assertEqual(conta_obra.valor, Decimal('1000.00'))
        self.assertEqual(conta_obra.valor_pago, Decimal('1015.50'))
        self.assertEqual(conta_obra.diferenca_pagamento, Decimal('15.50'))
        self.assertEqual(conta_obra.obra.nome_obra, 'Orla de Ipanema')
        self.assertTrue(DespesaObra.objects.filter(obra__nome_obra='Orla de Ipanema', valor=Decimal('1015.50')).exists())
        conta_centro = ContaPagar.objects.get(fornecedor='Fornecedor Centro Pago')
        self.assertIsNone(conta_centro.obra)
        self.assertEqual(conta_centro.centro_custo.nome, 'Maquinas E Veículos')
        self.assertEqual(conta_centro.valor_pago, Decimal('475.00'))

    def test_dashboard_financeiro_responde(self):
        response = self.client.get(reverse('financeiro_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Financeiro')
        self.assertContains(response, 'Fluxo de caixa')

    def test_dashboard_financeiro_agrupa_fluxo_por_semana(self):
        ContaReceber.objects.create(
            cliente='Cliente A',
            obra=self.obra,
            centro_custo=self.centro,
            numero_nf='NF-SEM-1',
            descricao='Receita da semana',
            data_emissao=date(2026, 5, 1),
            data_vencimento=date(2026, 5, 4),
            valor_bruto=Decimal('100.00'),
        )
        ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            descricao='Despesa da mesma semana',
            data_emissao=date(2026, 5, 1),
            data_vencimento=date(2026, 5, 8),
            valor=Decimal('40.00'),
        )
        ContaPagar.objects.create(
            fornecedor='Fornecedor B',
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            descricao='Despesa da semana seguinte',
            data_emissao=date(2026, 5, 1),
            data_vencimento=date(2026, 5, 11),
            valor=Decimal('25.00'),
        )

        response = self.client.get(reverse('financeiro_home'))

        grafico = response.context['grafico_fluxo']
        self.assertEqual(grafico['labels'], ['04/05 a 10/05', '11/05 a 17/05'])
        self.assertEqual(grafico['receber'], [100.0, 0.0])
        self.assertEqual(grafico['pagar'], [40.0, 25.0])

    def test_relatorio_financeiro_agrupa_por_centro_e_ordena_por_data(self):
        centro_maquinas = CentroCusto.objects.create(nome='Maquinas')
        ContaPagar.objects.create(
            fornecedor='Fornecedor B',
            obra=self.obra,
            centro_custo=centro_maquinas,
            categoria='material',
            descricao='Despesa posterior',
            data_emissao=date(2026, 5, 2),
            data_vencimento=date(2026, 5, 20),
            valor=Decimal('200.00'),
        )
        ContaPagar.objects.create(
            fornecedor='Fornecedor A',
            obra=self.obra,
            centro_custo=self.centro,
            categoria='material',
            descricao='Despesa anterior',
            data_emissao=date(2026, 5, 1),
            data_vencimento=date(2026, 5, 10),
            valor=Decimal('100.00'),
        )

        response = self.client.get(
            reverse('relatorio_financeiro'),
            {'tipo': 'pagar', 'ordenacao': 'data_asc', 'agrupamento': 'centro_custo'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Obras')
        self.assertContains(response, 'Maquinas')
        content = response.content.decode()
        self.assertLess(content.index('Despesa anterior'), content.index('Despesa posterior'))

    def test_relatorio_pdf_responde_pdf(self):
        response = self.client.get(
            reverse('relatorio_financeiro_pdf'),
            {'tipo': 'pagar', 'ordenacao': 'data_asc', 'agrupamento': 'centro_custo'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
