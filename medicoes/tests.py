from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from obras.models import Obra
from controles.models import FaturamentoDireto

from .models import (
    FaturamentoDiretoMedicao,
    ItemMedicaoConstrutora,
    ItemMedicaoEmpreiteiro,
    ItemOrcamentoMedicao,
    MedicaoConstrutora,
    MedicaoEmpreiteiro,
    OrcamentoMedicao,
)


class MedicoesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='usuario', password='senha')
        self.client.force_login(self.user)
        self.obra = Obra.objects.create(nome_obra='Obra Teste', cliente='Cliente')

    def _orcamento(self):
        orcamento = OrcamentoMedicao.objects.create(
            obra=self.obra,
            nome='Orcamento principal',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )
        item = ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            item='1.1',
            descricao='Escavacao',
            unidade='m3',
            quantidade=Decimal('100.0000'),
            preco_unitario_material=Decimal('10.00'),
            preco_unitario_mao_obra=Decimal('5.00'),
            preco_unitario_equipamentos=Decimal('2.00'),
        )
        return orcamento, item

    def test_importa_orcamento_csv(self):
        arquivo = SimpleUploadedFile(
            'orcamento.csv',
            (
                'item;descricao;unidade;quantidade;preco unitario material;preco unitario mao de obra;preco unitario equipamentos\n'
                '1;Drenagem;m;10,5;100,00;20,00;5,00\n'
            ).encode('utf-8-sig'),
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('importar_orcamento_medicao'),
            {
                'obra': self.obra.id,
                'nome': 'Planilha da obra',
                'tipo': OrcamentoMedicao.TIPO_CONSTRUTORA,
                'arquivo': arquivo,
            },
        )

        self.assertEqual(response.status_code, 302)
        orcamento = OrcamentoMedicao.objects.get(nome='Planilha da obra')
        item = orcamento.itens.get()
        self.assertEqual(item.quantidade, Decimal('10.5'))
        self.assertEqual(item.preco_unitario_total, Decimal('125.00'))

    def test_importa_planilha_com_preco_unitario_simples(self):
        arquivo = SimpleUploadedFile(
            'planilha.csv',
            (
                'referencia;descricao;un;quantidade;preco unitario\n'
                '1.1;Servico medido;m2;10;45,50\n'
            ).encode('utf-8-sig'),
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('importar_orcamento_medicao'),
            {
                'obra': self.obra.id,
                'nome': 'Planilha com unitario',
                'tipo': OrcamentoMedicao.TIPO_CONSTRUTORA,
                'arquivo': arquivo,
            },
        )

        self.assertEqual(response.status_code, 302)
        item = OrcamentoMedicao.objects.get(nome='Planilha com unitario').itens.get()
        self.assertEqual(item.preco_unitario_total, Decimal('45.50'))

    def test_importacao_sem_cabecalho_retorna_erro_no_formulario(self):
        arquivo = SimpleUploadedFile(
            'orcamento.csv',
            '1;Drenagem;m;10,5\n'.encode('utf-8'),
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('importar_orcamento_medicao'),
            {
                'obra': self.obra.id,
                'nome': 'Planilha invalida',
                'tipo': OrcamentoMedicao.TIPO_CONSTRUTORA,
                'arquivo': arquivo,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(OrcamentoMedicao.objects.filter(nome='Planilha invalida').exists())

    def test_abre_formulario_medicao_simples(self):
        response = self.client.get(reverse('nova_medicao_empreiteiro_simples'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recibo simples de medicao')

    def test_telas_separadas_de_medicao_carregam(self):
        orcamento, item = self._orcamento()
        response_construtora = self.client.get(reverse('medicoes_construtora_home'))
        response_empreiteiros = self.client.get(reverse('medicoes_empreiteiros_home'))
        response_obra = self.client.get(reverse('medicoes_obra', args=[self.obra.id]))

        self.assertContains(response_construtora, 'Medicao da construtora')
        self.assertContains(response_construtora, orcamento.nome)
        self.assertContains(response_empreiteiros, 'Medicao de empreiteiro')
        self.assertContains(response_obra, 'Painel operacional da obra')

    def test_medicao_construtora_calcula_acumulado_e_liquido(self):
        orcamento, item = self._orcamento()
        primeira = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        ItemMedicaoConstrutora.objects.create(medicao=primeira, item_orcamento=item, quantidade_periodo=Decimal('20'))
        segunda = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=2,
            periodo_inicio=date(2026, 2, 1),
            periodo_fim=date(2026, 2, 28),
            data_medicao=date(2026, 2, 28),
            retencao_tecnica=Decimal('10.00'),
            issqn=Decimal('5.00'),
            inss=Decimal('3.00'),
            desconto_adicional=Decimal('2.00'),
        )
        item_segunda = ItemMedicaoConstrutora.objects.create(
            medicao=segunda,
            item_orcamento=item,
            quantidade_periodo=Decimal('30'),
        )

        self.assertEqual(item_segunda.quantidade_acumulada_anterior, Decimal('20'))
        self.assertEqual(item_segunda.quantidade_acumulada_atual, Decimal('50'))
        self.assertEqual(segunda.subtotal_periodo, Decimal('510.00'))
        self.assertEqual(segunda.total_liquido, Decimal('490.00'))

        pdf = self.client.get(reverse('medicao_construtora_pdf', args=[segunda.id]))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')

    def test_medicao_construtora_desconta_faturamento_direto_fora_da_base_de_impostos(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
            issqn_percentual=Decimal('5.00'),
            inss_percentual=Decimal('10.00'),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('20'))
        faturamento = FaturamentoDireto.objects.create(
            obra=self.obra,
            numero_nf='FD-1',
            empresa_comprou='Cliente',
            valor_nota=Decimal('100.00'),
            descricao='Material comprado direto',
            vencimento_boleto='30 dias',
        )
        FaturamentoDiretoMedicao.objects.create(medicao=medicao, faturamento_direto=faturamento)

        self.assertEqual(medicao.total_bruto, Decimal('340.00'))
        self.assertEqual(medicao.total_faturamento_direto, Decimal('100.00'))
        self.assertEqual(medicao.base_impostos, Decimal('240.00'))
        self.assertEqual(medicao.total_mao_obra_periodo, Decimal('100.00'))

        response = self.client.post(
            reverse('editar_medicao_construtora', args=[medicao.id]),
            {
                'numero': '1',
                'periodo_inicio': '2026-01-01',
                'periodo_fim': '2026-01-31',
                'data_medicao': '2026-01-31',
                'retencao_tecnica': '0',
                'retencao_tecnica_percentual': '0',
                'issqn': '0',
                'issqn_percentual': '5',
                'inss': '0',
                'inss_percentual': '10',
                'desconto_adicional': '0',
                'desconto_adicional_percentual': '0',
                'observacoes': '',
                'faturamentos_diretos': [str(faturamento.id)],
                'itens-TOTAL_FORMS': '1',
                'itens-INITIAL_FORMS': '1',
                'itens-MIN_NUM_FORMS': '0',
                'itens-MAX_NUM_FORMS': '1000',
                'itens-0-id': str(medicao.itens.get().id),
                'itens-0-quantidade_periodo': '20',
            },
        )

        self.assertRedirects(response, reverse('editar_medicao_construtora', args=[medicao.id]))
        medicao.refresh_from_db()
        faturamento.refresh_from_db()
        self.assertEqual(medicao.issqn, Decimal('12.00'))
        self.assertEqual(medicao.inss, Decimal('10.00'))
        self.assertEqual(medicao.total_liquido, Decimal('218.00'))
        self.assertEqual(faturamento.medicao_desconto, 'Medicao 1')

    def test_percentuais_sao_calculados_mesmo_sem_valor_salvo(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
            issqn_percentual=Decimal('3.00'),
            inss_percentual=Decimal('1.00'),
            retencao_tecnica_percentual=Decimal('5.00'),
            desconto_adicional_percentual=Decimal('2.00'),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('10'))

        self.assertEqual(medicao.subtotal_periodo, Decimal('170.00'))
        self.assertEqual(medicao.base_impostos, Decimal('170.00'))
        self.assertEqual(medicao.total_mao_obra_periodo, Decimal('50.00'))
        self.assertEqual(medicao.issqn_calculado, Decimal('5.10'))
        self.assertEqual(medicao.inss_calculado, Decimal('0.50'))
        self.assertEqual(medicao.retencao_tecnica_calculada, Decimal('8.50'))
        self.assertEqual(medicao.desconto_adicional_calculado, Decimal('3.40'))
        self.assertEqual(medicao.total_liquido, Decimal('152.50'))

    def test_exclui_medicao_construtora(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('20'))

        response = self.client.post(reverse('excluir_medicao_construtora', args=[medicao.id]))

        self.assertRedirects(response, reverse('detalhe_orcamento_medicao', args=[orcamento.id]))
        self.assertFalse(MedicaoConstrutora.objects.filter(id=medicao.id).exists())
        self.assertTrue(OrcamentoMedicao.objects.filter(id=orcamento.id).exists())

    def test_medicao_empreiteiro_simples_e_exportacoes(self):
        medicao = MedicaoEmpreiteiro.objects.create(
            tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
            obra=self.obra,
            empreiteiro='Empreiteiro',
            cpf_cnpj='00.000.000/0001-00',
            pix='pix@teste.com',
            numero=1,
            periodo_inicio=date(2026, 3, 1),
            periodo_fim=date(2026, 3, 31),
            data_medicao=date(2026, 3, 31),
            retencao_tecnica=Decimal('15.00'),
        )
        ItemMedicaoEmpreiteiro.objects.create(
            medicao=medicao,
            item='1',
            descricao='Servico simples',
            unidade='un',
            quantidade_periodo=Decimal('2'),
            valor_unitario=Decimal('100.00'),
        )

        self.assertEqual(medicao.total_liquido, Decimal('185.00'))
        pdf = self.client.get(reverse('medicao_empreiteiro_pdf', args=[medicao.id]))
        excel = self.client.get(reverse('medicao_empreiteiro_excel', args=[medicao.id]))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertEqual(excel.status_code, 200)
        self.assertIn('spreadsheetml', excel['Content-Type'])

    def test_exclui_medicao_empreiteiro_simples(self):
        medicao = MedicaoEmpreiteiro.objects.create(
            tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
            obra=self.obra,
            empreiteiro='Empreiteiro',
            numero=1,
            periodo_inicio=date(2026, 3, 1),
            periodo_fim=date(2026, 3, 31),
            data_medicao=date(2026, 3, 31),
        )
        ItemMedicaoEmpreiteiro.objects.create(
            medicao=medicao,
            item='1',
            descricao='Servico simples',
            unidade='un',
            quantidade_periodo=Decimal('2'),
            valor_unitario=Decimal('100.00'),
        )

        response = self.client.post(reverse('excluir_medicao_empreiteiro', args=[medicao.id]))

        self.assertRedirects(response, reverse('medicoes_empreiteiros_home'))
        self.assertFalse(MedicaoEmpreiteiro.objects.filter(id=medicao.id).exists())
