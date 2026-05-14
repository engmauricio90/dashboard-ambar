from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from controles.models import FaturamentoDireto

from .models import AditivoContrato, DespesaObra, NotaFiscal, Obra, RetencaoTecnicaObra


class ObraFluxoFinanceiroTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='analista', password='senha-forte-123')
        self.client.force_login(self.user)
        self.obra = Obra.objects.create(
            nome_obra='Obra Centro',
            cliente='Cliente XPTO',
            valor_contrato=Decimal('1000.00'),
            projecao_despesa=Decimal('700.00'),
        )

    def test_detalhe_obra_carrega(self):
        response = self.client.get(reverse('detalhe_obra', args=[self.obra.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Obra Centro')
        self.assertContains(response, 'graficoEvolucaoObra')
        self.assertIn('grafico_evolucao', response.context)
        self.assertIn('grafico_composicao', response.context)
        self.assertContains(response, reverse('lista_notas_obra', args=[self.obra.id]))
        self.assertContains(response, reverse('lista_faturamentos_diretos_obra', args=[self.obra.id]))

    def test_listagens_completas_da_obra_carregam(self):
        NotaFiscal.objects.create(
            obra=self.obra,
            numero='NF-LISTA',
            data_emissao=date(2026, 4, 20),
            valor_bruto=Decimal('90.00'),
            status='emitida',
        )
        DespesaObra.objects.create(
            obra=self.obra,
            data_referencia=date(2026, 4, 20),
            categoria='material',
            descricao='Despesa completa',
            valor=Decimal('80.00'),
        )
        FaturamentoDireto.objects.create(
            obra=self.obra,
            data_lancamento=date(2026, 4, 21),
            numero_ordem_compra='OC-LISTA',
            empresa_comprou='Cliente',
            valor_nota=Decimal('70.00'),
            descricao='Compra direta completa',
            vencimento_boleto='30/60',
        )
        AditivoContrato.objects.create(
            obra=self.obra,
            data_referencia=date(2026, 4, 22),
            tipo=AditivoContrato.TIPO_ADITIVO,
            descricao='Aditivo completo',
            valor=Decimal('60.00'),
        )
        RetencaoTecnicaObra.objects.create(
            obra=self.obra,
            data_referencia=date(2026, 4, 23),
            descricao='Retencao completa',
            valor=Decimal('50.00'),
        )

        casos = [
            ('lista_notas_obra', 'NF-LISTA'),
            ('lista_despesas_obra', 'Despesa completa'),
            ('lista_faturamentos_diretos_obra', 'Compra direta completa'),
            ('lista_aditivos_obra', 'Aditivo completo'),
            ('lista_retencoes_tecnicas_obra', 'Retencao completa'),
        ]
        for url_name, texto in casos:
            response = self.client.get(reverse(url_name, args=[self.obra.id]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, texto)

    def test_nova_nota_fiscal_redireciona_para_financeiro(self):
        response = self.client.post(
            reverse('nova_nota_fiscal', args=[self.obra.id]),
            {
                'numero': 'NF-001',
                'data_emissao': '2026-04-20',
                'valor_bruto': '250.00',
                'status': 'emitida',
                'observacoes': 'Primeiro faturamento',
                'retencoes-TOTAL_FORMS': '2',
                'retencoes-INITIAL_FORMS': '0',
                'retencoes-MIN_NUM_FORMS': '0',
                'retencoes-MAX_NUM_FORMS': '1000',
                'retencoes-0-tipo': 'inss',
                'retencoes-0-descricao': 'INSS',
                'retencoes-0-valor': '15.00',
                'retencoes-1-tipo': '',
                'retencoes-1-descricao': '',
                'retencoes-1-valor': '',
                'impostos-TOTAL_FORMS': '2',
                'impostos-INITIAL_FORMS': '0',
                'impostos-MIN_NUM_FORMS': '0',
                'impostos-MAX_NUM_FORMS': '1000',
                'impostos-0-tipo': 'simples',
                'impostos-0-descricao': 'Simples',
                'impostos-0-valor': '10.00',
                'impostos-1-tipo': '',
                'impostos-1-descricao': '',
                'impostos-1-valor': '',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'{reverse("nova_conta_receber")}?obra={self.obra.id}')
        self.assertFalse(NotaFiscal.objects.filter(obra=self.obra, numero='NF-001').exists())

    def test_nova_despesa_redireciona_para_financeiro(self):
        response = self.client.post(
            reverse('nova_despesa', args=[self.obra.id]),
            {
                'data_referencia': '2026-04-20',
                'categoria': 'material',
                'descricao': 'Compra de material',
                'valor': '120.00',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'{reverse("nova_conta_pagar")}?obra={self.obra.id}')
        self.assertFalse(DespesaObra.objects.filter(obra=self.obra, descricao='Compra de material').exists())

    def test_cria_aditivo_e_agregado_da_obra_e_atualizado(self):
        AditivoContrato.objects.create(
            obra=self.obra,
            data_referencia=date(2026, 4, 20),
            tipo='aditivo',
            descricao='Aditivo complementar',
            valor=Decimal('150.00'),
        )
        AditivoContrato.objects.create(
            obra=self.obra,
            data_referencia=date(2026, 4, 21),
            tipo='supressao',
            descricao='Supressao parcial',
            valor=Decimal('50.00'),
        )

        self.obra.refresh_from_db()
        self.assertEqual(self.obra.total_aditivos, Decimal('150.00'))
        self.assertEqual(self.obra.total_supressoes, Decimal('50.00'))
        self.assertEqual(self.obra.contrato_atualizado, Decimal('1100.00'))

    def test_cria_despesa_atualiza_total_real(self):
        DespesaObra.objects.create(
            obra=self.obra,
            data_referencia=date(2026, 4, 20),
            categoria='material',
            descricao='Compra de material',
            valor=Decimal('80.00'),
        )

        self.obra.refresh_from_db()
        self.assertEqual(self.obra.total_despesa_real, Decimal('80.00'))

    def test_campos_legados_nao_entram_nos_totais_sem_lancamentos_novos(self):
        obra = Obra.objects.create(
            nome_obra='Obra Legada',
            valor_contrato=Decimal('1000.00'),
            aditivos=Decimal('50.00'),
            despesa_real=Decimal('40.00'),
            retencoes_tecnicas=Decimal('10.00'),
            impostos=Decimal('5.00'),
            valor_notas=Decimal('200.00'),
        )

        self.assertEqual(obra.total_aditivos, Decimal('0'))
        self.assertEqual(obra.total_despesa_real, Decimal('0'))
        self.assertEqual(obra.total_retencoes, Decimal('0'))
        self.assertEqual(obra.total_impostos, Decimal('0'))
        self.assertEqual(obra.total_notas_fiscais, Decimal('0'))

    def test_retencao_tecnica_entra_no_total_de_retencoes(self):
        RetencaoTecnicaObra.objects.create(
            obra=self.obra,
            data_referencia=date(2026, 4, 20),
            descricao='Retencao contratual',
            valor=Decimal('22.00'),
        )

        self.obra.refresh_from_db()
        self.assertEqual(self.obra.total_retencoes_tecnicas, Decimal('22.00'))
        self.assertEqual(self.obra.total_retencoes, Decimal('22.00'))

    def test_excluir_despesa_remove_do_historico(self):
        despesa = DespesaObra.objects.create(
            obra=self.obra,
            data_referencia=date(2026, 4, 20),
            categoria='material',
            descricao='Excluir esta despesa',
            valor=Decimal('30.00'),
        )

        response = self.client.post(reverse('excluir_despesa', args=[self.obra.id, despesa.id]))

        self.assertRedirects(response, reverse('historico_financeiro', args=[self.obra.id]))
        self.assertFalse(DespesaObra.objects.filter(id=despesa.id).exists())

    def test_excluir_nota_fiscal_remove_registro(self):
        nota = NotaFiscal.objects.create(
            obra=self.obra,
            numero='NF-DELETE',
            data_emissao=date(2026, 4, 20),
            valor_bruto=Decimal('90.00'),
            status='emitida',
        )

        response = self.client.post(reverse('excluir_nota_fiscal', args=[self.obra.id, nota.id]))

        self.assertRedirects(response, reverse('historico_financeiro', args=[self.obra.id]))
        self.assertFalse(NotaFiscal.objects.filter(id=nota.id).exists())

    def test_editar_nota_fiscal_atualiza_registro(self):
        nota = NotaFiscal.objects.create(
            obra=self.obra,
            numero='NF-EDITAR',
            data_emissao=date(2026, 4, 20),
            valor_bruto=Decimal('90.00'),
            status='emitida',
            observacoes='Versao inicial',
        )

        response = self.client.post(
            reverse('editar_nota_fiscal', args=[self.obra.id, nota.id]),
            {
                'numero': 'NF-EDITADA',
                'data_emissao': '2026-04-21',
                'valor_bruto': '125.50',
                'status': 'recebida',
                'observacoes': 'Versao corrigida',
                'retencoes-TOTAL_FORMS': '2',
                'retencoes-INITIAL_FORMS': '0',
                'retencoes-MIN_NUM_FORMS': '0',
                'retencoes-MAX_NUM_FORMS': '1000',
                'retencoes-0-tipo': 'iss',
                'retencoes-0-descricao': 'ISS',
                'retencoes-0-valor': '12.00',
                'retencoes-1-tipo': '',
                'retencoes-1-descricao': '',
                'retencoes-1-valor': '',
                'impostos-TOTAL_FORMS': '2',
                'impostos-INITIAL_FORMS': '0',
                'impostos-MIN_NUM_FORMS': '0',
                'impostos-MAX_NUM_FORMS': '1000',
                'impostos-0-tipo': 'iss',
                'impostos-0-descricao': 'ISS',
                'impostos-0-valor': '5.50',
                'impostos-1-tipo': '',
                'impostos-1-descricao': '',
                'impostos-1-valor': '',
            },
        )

        nota.refresh_from_db()
        self.assertRedirects(response, reverse('detalhe_nota_fiscal', args=[self.obra.id, nota.id]))
        self.assertEqual(nota.numero, 'NF-EDITADA')
        self.assertEqual(nota.valor_bruto, Decimal('125.50'))
        self.assertEqual(nota.status, 'recebida')
        self.assertEqual(nota.observacoes, 'Versao corrigida')
        self.assertEqual(nota.total_retencoes, Decimal('12.00'))
        self.assertEqual(nota.total_impostos, Decimal('5.50'))

    def test_relatorio_obra_filtra_por_periodo(self):
        NotaFiscal.objects.create(
            obra=self.obra,
            numero='NF-ANTIGA',
            data_emissao=date(2026, 4, 1),
            valor_bruto=Decimal('100.00'),
            status='emitida',
        )
        NotaFiscal.objects.create(
            obra=self.obra,
            numero='NF-RECENTE',
            data_emissao=date(2026, 4, 20),
            valor_bruto=Decimal('250.00'),
            status='emitida',
        )

        response = self.client.get(
            reverse('relatorio_obra', args=[self.obra.id]),
            {'data_inicial': '2026-04-10', 'data_final': '2026-04-30'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Relatorio da Obra')
        self.assertContains(response, 'NF-RECENTE')
        self.assertNotContains(response, 'NF-ANTIGA')

    def test_relatorio_obra_mostra_erro_quando_periodo_invertido(self):
        response = self.client.get(
            reverse('relatorio_obra', args=[self.obra.id]),
            {'data_inicial': '2026-04-30', 'data_final': '2026-04-10'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A data inicial nao pode ser maior que a data final')
