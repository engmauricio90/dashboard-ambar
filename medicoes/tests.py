from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from obras.models import Obra

from .models import (
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

        self.assertRedirects(response, reverse('medicoes_home'))
        self.assertFalse(MedicaoEmpreiteiro.objects.filter(id=medicao.id).exists())
