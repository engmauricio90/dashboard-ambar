from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import load_workbook

from empresas.models import Empresa, UsuarioEmpresa
from obras.models import Obra
from controles.models import FaturamentoDireto
from documentos.pdf import PdfDocument, PdfTableColumn

from .forms import RelatorioMedicoesForm
from .models import (
    Empreiteiro,
    FaturamentoDiretoMedicao,
    ItemMedicaoConstrutora,
    ItemMedicaoEmpreiteiro,
    ItemOrcamentoMedicao,
    MedicaoConstrutora,
    MedicaoEmpreiteiro,
    OrcamentoMedicao,
)
from .services import (
    anotar_resumo_medicoes_construtora,
    anotar_resumo_planilhas_construtora,
    calcular_resumo_construtora,
    itens_construtora_com_grupos,
    itens_empreiteiro_com_acumulados,
)


class MedicoesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='usuario', password='senha')
        self.empresa = Empresa.objects.get(slug='ambar')
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.empresa)
        self.client.force_login(self.user)
        self.obra = Obra.objects.create(empresa=self.empresa, nome_obra='Obra Teste', cliente='Cliente')

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

    def _orcamento_com_itens(self, quantidade=30, tipo=OrcamentoMedicao.TIPO_CONSTRUTORA):
        orcamento = OrcamentoMedicao.objects.create(
            obra=self.obra,
            nome=f'Orcamento {tipo} {quantidade}',
            tipo=tipo,
        )
        itens = []
        for index in range(1, quantidade + 1):
            itens.append(
                ItemOrcamentoMedicao.objects.create(
                    orcamento=orcamento,
                    item=str(index),
                    descricao=f'Servico de performance {index}',
                    unidade='m2',
                    quantidade=Decimal('1000.0000'),
                    preco_unitario_material=Decimal('12.3456') if tipo == OrcamentoMedicao.TIPO_CONSTRUTORA else Decimal('0'),
                    preco_unitario_mao_obra=Decimal('5.4321') if tipo == OrcamentoMedicao.TIPO_CONSTRUTORA else Decimal('10.0000'),
                    preco_unitario_equipamentos=Decimal('1.2345') if tipo == OrcamentoMedicao.TIPO_CONSTRUTORA else Decimal('0'),
                )
            )
        return orcamento, itens

    def _medicao_construtora_com_itens(self, quantidade=30):
        orcamento, itens = self._orcamento_com_itens(quantidade)
        primeira = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        segunda = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=2,
            periodo_inicio=date(2026, 2, 1),
            periodo_fim=date(2026, 2, 28),
            data_medicao=date(2026, 2, 28),
            retencao_tecnica_percentual=Decimal('2.0000'),
            issqn_percentual=Decimal('5.0000'),
            inss_percentual=Decimal('11.0000'),
            desconto_adicional_percentual=Decimal('1.0000'),
        )
        terceira = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=3,
            periodo_inicio=date(2026, 3, 1),
            periodo_fim=date(2026, 3, 31),
            data_medicao=date(2026, 3, 31),
        )
        for item in itens:
            ItemMedicaoConstrutora.objects.create(medicao=primeira, item_orcamento=item, quantidade_periodo=Decimal('10.0000'))
            ItemMedicaoConstrutora.objects.create(medicao=segunda, item_orcamento=item, quantidade_periodo=Decimal('15.0000'))
            ItemMedicaoConstrutora.objects.create(medicao=terceira, item_orcamento=item, quantidade_periodo=Decimal('20.0000'))
        return orcamento, itens, primeira, segunda, terceira

    def _medicao_empreiteiro_cumulativa_com_itens(self, quantidade=30):
        orcamento, itens = self._orcamento_com_itens(quantidade, tipo=OrcamentoMedicao.TIPO_EMPREITEIRO)
        empreiteiro = Empreiteiro.objects.create(empresa=self.empresa, nome='Empreiteiro Performance')
        primeira = MedicaoEmpreiteiro.objects.create(
            empresa=self.empresa,
            obra=self.obra,
            orcamento=orcamento,
            tipo=MedicaoEmpreiteiro.TIPO_CUMULATIVA,
            empreiteiro_cadastro=empreiteiro,
            empreiteiro=empreiteiro.nome,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        segunda = MedicaoEmpreiteiro.objects.create(
            empresa=self.empresa,
            obra=self.obra,
            orcamento=orcamento,
            tipo=MedicaoEmpreiteiro.TIPO_CUMULATIVA,
            empreiteiro_cadastro=empreiteiro,
            empreiteiro=empreiteiro.nome,
            numero=2,
            periodo_inicio=date(2026, 2, 1),
            periodo_fim=date(2026, 2, 28),
            data_medicao=date(2026, 2, 28),
        )
        for item in itens:
            ItemMedicaoEmpreiteiro.objects.create(
                medicao=primeira,
                item_orcamento=item,
                item=item.item,
                descricao=item.descricao,
                unidade=item.unidade,
                quantidade_periodo=Decimal('10.0000'),
                valor_unitario=Decimal('10.00'),
            )
            ItemMedicaoEmpreiteiro.objects.create(
                medicao=segunda,
                item_orcamento=item,
                item=item.item,
                descricao=item.descricao,
                unidade=item.unidade,
                quantidade_periodo=Decimal('15.0000'),
                valor_unitario=Decimal('10.00'),
            )
        return orcamento, itens, primeira, segunda

    def test_importa_orcamento_csv(self):
        arquivo = SimpleUploadedFile(
            'orcamento.csv',
            (
                'item;descricao;unidade;quantidade;preco unitario material;preco unitario mao de obra;preco unitario equipamentos\n'
                '1;Drenagem;m;10,5;100,1234;20,0001;5,0000\n'
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
        self.assertEqual(item.preco_unitario_total, Decimal('125.1235'))

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

    def test_importa_planilha_com_grupos_e_itens_mediveis(self):
        arquivo = SimpleUploadedFile(
            'planilha_grupos.csv',
            (
                'item;tipo;descricao;unidade;quantidade;preco_unitario_material;preco_unitario_mao_obra;preco_unitario_equipamentos\n'
                '1;grupo;SERVICOS PRELIMINARES;;;;;\n'
                '1.1;item;Mobilizacao do canteiro;mes;6;0;3500;0\n'
                '2;;TERRAPLANAGEM;;0;0;0;0\n'
                '2.1;;Escavacao;m3;10;1;2;3\n'
            ).encode('utf-8-sig'),
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('importar_orcamento_medicao'),
            {
                'obra': self.obra.id,
                'nome': 'Planilha com grupos',
                'tipo': OrcamentoMedicao.TIPO_CONSTRUTORA,
                'arquivo': arquivo,
            },
        )

        self.assertEqual(response.status_code, 302)
        orcamento = OrcamentoMedicao.objects.get(nome='Planilha com grupos')
        self.assertEqual(orcamento.itens.filter(tipo=ItemOrcamentoMedicao.TIPO_GRUPO).count(), 2)
        self.assertEqual(orcamento.itens.filter(tipo=ItemOrcamentoMedicao.TIPO_ITEM).count(), 2)
        self.assertEqual(orcamento.total_orcamento, Decimal('21060.0000'))

    def test_tela_medicao_mostra_detalhes_e_historico_do_faturamento_direto(self):
        orcamento, item = self._orcamento()
        medicao_atual = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=2,
            periodo_inicio=date(2026, 2, 1),
            periodo_fim=date(2026, 2, 28),
            data_medicao=date(2026, 2, 28),
        )
        medicao_anterior = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        disponivel = FaturamentoDireto.objects.create(
            obra=self.obra,
            numero_nf='1414',
            empresa_comprou='Fornecedor livre',
            valor_nota=Decimal('1000.00'),
            descricao='Tubos de concreto',
            vencimento_boleto='27/04/2026',
        )
        usado = FaturamentoDireto.objects.create(
            obra=self.obra,
            numero_nf='1413',
            empresa_comprou='Fornecedor usado',
            valor_nota=Decimal('500.00'),
            descricao='Barras de aco',
            vencimento_boleto='24/04/2026',
            medicao_desconto='Medicao 1',
        )
        FaturamentoDiretoMedicao.objects.create(medicao=medicao_anterior, faturamento_direto=usado)

        response = self.client.get(reverse('editar_medicao_construtora', args=[medicao_atual.id]))

        self.assertContains(response, '1414')
        self.assertContains(response, 'Fornecedor livre')
        self.assertContains(response, 'R$ 1.000,00')
        self.assertContains(response, '100,00%')
        self.assertContains(response, 'Historico de faturamento direto ja descontado')
        self.assertContains(response, 'Fornecedor usado')

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

    def test_edita_itens_da_planilha_importada(self):
        orcamento, item = self._orcamento()

        response = self.client.post(
            reverse('editar_itens_orcamento_medicao', args=[orcamento.id]),
            {
                'itens-TOTAL_FORMS': '2',
                'itens-INITIAL_FORMS': '1',
                'itens-MIN_NUM_FORMS': '0',
                'itens-MAX_NUM_FORMS': '1000',
                'itens-0-id': str(item.id),
                'itens-0-tipo': ItemOrcamentoMedicao.TIPO_ITEM,
                'itens-0-ordem': '0',
                'itens-0-item': '1.1',
                'itens-0-descricao': 'Escavacao revisada',
                'itens-0-unidade': 'm3',
                'itens-0-quantidade': '120.1234',
                'itens-0-preco_unitario_material': '10.1111',
                'itens-0-preco_unitario_mao_obra': '5.2222',
                'itens-0-preco_unitario_equipamentos': '2.3333',
                'itens-1-id': '',
                'itens-1-tipo': ItemOrcamentoMedicao.TIPO_ITEM,
                'itens-1-ordem': '1',
                'itens-1-item': '1.2',
                'itens-1-descricao': 'Transporte',
                'itens-1-unidade': 'm3',
                'itens-1-quantidade': '10.0000',
                'itens-1-preco_unitario_material': '1.0000',
                'itens-1-preco_unitario_mao_obra': '0.0000',
                'itens-1-preco_unitario_equipamentos': '0.0000',
            },
        )

        self.assertRedirects(response, reverse('detalhe_orcamento_medicao', args=[orcamento.id]))
        item.refresh_from_db()
        self.assertEqual(item.descricao, 'Escavacao revisada')
        self.assertEqual(item.quantidade, Decimal('120.1234'))
        self.assertEqual(item.preco_unitario_total, Decimal('17.6666'))
        self.assertEqual(orcamento.itens.count(), 2)

    def test_insere_grupo_antes_do_primeiro_item_da_planilha(self):
        orcamento, item = self._orcamento()

        response = self.client.post(
            reverse('editar_itens_orcamento_medicao', args=[orcamento.id]),
            {
                'itens-TOTAL_FORMS': '2',
                'itens-INITIAL_FORMS': '1',
                'itens-MIN_NUM_FORMS': '0',
                'itens-MAX_NUM_FORMS': '1000',
                'itens-0-id': str(item.id),
                'itens-0-tipo': ItemOrcamentoMedicao.TIPO_ITEM,
                'itens-0-ordem': '1',
                'itens-0-item': '1.1',
                'itens-0-descricao': 'Escavacao',
                'itens-0-unidade': 'm3',
                'itens-0-quantidade': '100.0000',
                'itens-0-preco_unitario_material': '10.0000',
                'itens-0-preco_unitario_mao_obra': '5.0000',
                'itens-0-preco_unitario_equipamentos': '2.0000',
                'itens-1-id': '',
                'itens-1-tipo': ItemOrcamentoMedicao.TIPO_GRUPO,
                'itens-1-ordem': '0',
                'itens-1-item': '1',
                'itens-1-descricao': 'TERRAPLANAGEM',
                'itens-1-unidade': '',
                'itens-1-quantidade': '',
                'itens-1-preco_unitario_material': '',
                'itens-1-preco_unitario_mao_obra': '',
                'itens-1-preco_unitario_equipamentos': '',
            },
        )

        self.assertRedirects(response, reverse('detalhe_orcamento_medicao', args=[orcamento.id]))
        itens = list(orcamento.itens.order_by('ordem', 'id'))
        self.assertEqual(itens[0].tipo, ItemOrcamentoMedicao.TIPO_GRUPO)
        self.assertEqual(itens[0].descricao, 'TERRAPLANAGEM')
        self.assertEqual(itens[1].id, item.id)
        self.assertEqual(orcamento.total_orcamento, Decimal('1700.00000000'))

    def test_saldo_contratual_construtora_mostra_somente_itens_com_saldo(self):
        orcamento, item = self._orcamento()
        item_medido_total = ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            item='2.1',
            descricao='Servico ja concluido',
            unidade='m',
            quantidade=Decimal('10.0000'),
            preco_unitario_material=Decimal('1.0000'),
            preco_unitario_mao_obra=Decimal('1.0000'),
            preco_unitario_equipamentos=Decimal('0.0000'),
        )
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        ItemMedicaoConstrutora.objects.create(
            medicao=medicao,
            item_orcamento=item,
            quantidade_periodo=Decimal('40.0000'),
        )
        ItemMedicaoConstrutora.objects.create(
            medicao=medicao,
            item_orcamento=item_medido_total,
            quantidade_periodo=Decimal('10.0000'),
        )

        response = self.client.get(reverse('saldo_contratual_construtora', args=[orcamento.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Escavacao')
        self.assertContains(response, '60,0000')
        self.assertContains(response, 'R$ 1.020,00')
        self.assertNotContains(response, 'Servico ja concluido')

        pdf = self.client.get(reverse('saldo_contratual_construtora_pdf', args=[orcamento.id]))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))

        excel = self.client.get(reverse('saldo_contratual_construtora_excel', args=[orcamento.id]))
        self.assertEqual(excel.status_code, 200)
        self.assertIn('spreadsheetml', excel['Content-Type'])
        wb = load_workbook(BytesIO(excel.content))
        ws = wb.active
        self.assertEqual(ws['A1'].value, 'Saldo contratual da construtora')
        self.assertIn('Escavacao', [cell.value for cell in ws['B']])

    def test_cria_planilha_manual_e_medicao_construtora(self):
        response = self.client.post(
            reverse('novo_orcamento_manual_medicao'),
            {
                'obra': self.obra.id,
                'nome': 'Planilha manual construtora',
                'tipo': OrcamentoMedicao.TIPO_CONSTRUTORA,
                'observacoes': '',
            },
        )

        orcamento = OrcamentoMedicao.objects.get(nome='Planilha manual construtora')
        self.assertRedirects(response, reverse('editar_itens_orcamento_medicao', args=[orcamento.id]))

        self.client.post(
            reverse('editar_itens_orcamento_medicao', args=[orcamento.id]),
            {
                'itens-TOTAL_FORMS': '1',
                'itens-INITIAL_FORMS': '0',
                'itens-MIN_NUM_FORMS': '0',
                'itens-MAX_NUM_FORMS': '1000',
                'itens-0-id': '',
                'itens-0-tipo': ItemOrcamentoMedicao.TIPO_ITEM,
                'itens-0-ordem': '0',
                'itens-0-item': '1',
                'itens-0-descricao': 'Servico manual',
                'itens-0-unidade': 'm2',
                'itens-0-quantidade': '10.0000',
                'itens-0-preco_unitario_material': '2.0000',
                'itens-0-preco_unitario_mao_obra': '3.0000',
                'itens-0-preco_unitario_equipamentos': '0.0000',
            },
        )

        response = self.client.post(
            reverse('nova_medicao_construtora', args=[orcamento.id]),
            {
                'numero': '1',
                'periodo_inicio': '2026-01-01',
                'periodo_fim': '2026-01-31',
                'data_medicao': '2026-01-31',
                'observacoes': '',
            },
        )

        medicao = MedicaoConstrutora.objects.get(orcamento=orcamento)
        self.assertRedirects(response, reverse('editar_medicao_construtora', args=[medicao.id]))
        self.assertEqual(medicao.itens.count(), 1)

    def test_cria_planilha_manual_e_medicao_cumulativa_empreiteiro(self):
        empreiteiro = Empreiteiro.objects.create(
            empresa=self.empresa,
            nome='Empreiteiro cadastrado',
            cpf_cnpj='11.111.111/0001-11',
            pix='pix@empreiteiro.com',
        )
        response = self.client.post(
            reverse('novo_orcamento_manual_medicao'),
            {
                'obra': self.obra.id,
                'nome': 'Planilha manual empreiteiro',
                'tipo': OrcamentoMedicao.TIPO_EMPREITEIRO,
                'observacoes': '',
            },
        )

        orcamento = OrcamentoMedicao.objects.get(nome='Planilha manual empreiteiro')
        self.assertRedirects(response, reverse('editar_itens_orcamento_medicao', args=[orcamento.id]))

        self.client.post(
            reverse('editar_itens_orcamento_medicao', args=[orcamento.id]),
            {
                'itens-TOTAL_FORMS': '1',
                'itens-INITIAL_FORMS': '0',
                'itens-MIN_NUM_FORMS': '0',
                'itens-MAX_NUM_FORMS': '1000',
                'itens-0-id': '',
                'itens-0-tipo': ItemOrcamentoMedicao.TIPO_ITEM,
                'itens-0-ordem': '0',
                'itens-0-item': '1',
                'itens-0-descricao': 'Servico empreiteiro manual',
                'itens-0-unidade': 'm',
                'itens-0-quantidade': '20.0000',
                'itens-0-preco_unitario_material': '0.0000',
                'itens-0-preco_unitario_mao_obra': '15.0000',
                'itens-0-preco_unitario_equipamentos': '0.0000',
            },
        )

        response = self.client.post(
            reverse('nova_medicao_empreiteiro_cumulativa', args=[orcamento.id]),
            {
                'obra': self.obra.id,
                'empreiteiro_cadastro': empreiteiro.id,
                'empreiteiro': '',
                'cpf_cnpj': '',
                'pix': '',
                'numero': '1',
                'periodo_inicio': '2026-02-01',
                'periodo_fim': '2026-02-28',
                'data_medicao': '2026-02-28',
                'observacoes': '',
            },
        )

        medicao = MedicaoEmpreiteiro.objects.get(orcamento=orcamento)
        self.assertRedirects(response, reverse('editar_medicao_empreiteiro', args=[medicao.id]))
        self.assertEqual(medicao.tipo, MedicaoEmpreiteiro.TIPO_CUMULATIVA)
        self.assertEqual(medicao.empreiteiro_cadastro, empreiteiro)
        self.assertEqual(medicao.empreiteiro, 'Empreiteiro cadastrado')
        self.assertEqual(medicao.itens.count(), 1)
        item_medicao = medicao.itens.get()
        item_medicao.quantidade_periodo = Decimal('5.0000')
        item_medicao.save()

        response_obra = self.client.get(reverse('medicoes_obra', args=[self.obra.id]))

        self.assertContains(response_obra, 'Pago/Liquido')
        self.assertContains(response_obra, '% concluida')
        self.assertContains(response_obra, 'R$ 300,00')
        self.assertContains(response_obra, 'R$ 75,00')
        self.assertContains(response_obra, 'R$ 225,00')
        self.assertContains(response_obra, '25,00%')

        response_detalhe = self.client.get(reverse('detalhe_orcamento_medicao', args=[orcamento.id]))
        self.assertContains(response_detalhe, 'Contratado')
        self.assertContains(response_detalhe, 'Medido')
        self.assertContains(response_detalhe, 'Saldo contratual')
        self.assertContains(response_detalhe, 'R$ 300,00')
        self.assertContains(response_detalhe, 'R$ 75,00')
        self.assertContains(response_detalhe, 'R$ 225,00')
        self.assertContains(response_detalhe, '25,00% concluida')

    def test_relatorio_gerencial_medicoes_filtra_colunas_e_exporta(self):
        orcamento, item = self._orcamento()
        medicao_construtora = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 3, 1),
            periodo_fim=date(2026, 3, 31),
            data_medicao=date(2026, 3, 31),
        )
        ItemMedicaoConstrutora.objects.create(
            medicao=medicao_construtora,
            item_orcamento=item,
            quantidade_periodo=Decimal('10.0000'),
        )
        empreiteiro = Empreiteiro.objects.create(empresa=self.empresa, nome='Empreiteiro Relatorio')
        medicao_empreiteiro = MedicaoEmpreiteiro.objects.create(
            empresa=self.empresa,
            tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
            obra=self.obra,
            empreiteiro_cadastro=empreiteiro,
            empreiteiro='Empreiteiro Relatorio',
            numero=2,
            periodo_inicio=date(2026, 4, 1),
            periodo_fim=date(2026, 4, 30),
            data_medicao=date(2026, 4, 30),
        )
        ItemMedicaoEmpreiteiro.objects.create(
            medicao=medicao_empreiteiro,
            item='1',
            descricao='Servico relatorio',
            quantidade_periodo=Decimal('2.0000'),
            valor_unitario=Decimal('50.00'),
        )
        for index in range(16):
            extra = MedicaoEmpreiteiro.objects.create(
                empresa=self.empresa,
                tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
                obra=self.obra,
                empreiteiro_cadastro=empreiteiro,
                empreiteiro='Empreiteiro Relatorio',
                numero=index + 3,
                periodo_inicio=date(2026, 4, 1),
                periodo_fim=date(2026, 4, 30),
                data_medicao=date(2026, 4, 30),
            )
            ItemMedicaoEmpreiteiro.objects.create(
                medicao=extra,
                item='1',
                descricao='Servico relatorio extra',
                quantidade_periodo=Decimal('1.0000'),
                valor_unitario=Decimal('10.00'),
            )

        response = self.client.get(
            reverse('relatorio_medicoes'),
            {
                'tipo': 'empreiteiro',
                'empreiteiro': empreiteiro.id,
                'colunas': ['tipo', 'empreiteiro', 'data_medicao', 'medido', 'liquido'],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Relatorio gerencial de medicoes')
        self.assertContains(response, 'Empreiteiro Relatorio')
        self.assertContains(response, '30/04/2026')
        self.assertContains(response, 'R$ 100,00')
        self.assertNotContains(response, 'R$ 170,00')

        excel = self.client.get(
            reverse('relatorio_medicoes'),
            {
                'tipo': 'empreiteiro',
                'empreiteiro': empreiteiro.id,
                'colunas': ['tipo', 'empreiteiro', 'data_medicao', 'medido'],
                'export': 'excel',
            },
        )
        self.assertEqual(excel.status_code, 200)
        self.assertIn('spreadsheetml', excel['Content-Type'])
        wb = load_workbook(BytesIO(excel.content))
        ws = wb.active
        self.assertEqual(ws['A1'].value, 'Relatorio gerencial de medicoes')
        header_row = next(row for row in ws.iter_rows(values_only=True) if row and row[0] == 'Tipo')
        self.assertEqual(header_row[:4], ('Tipo', 'Contratado', 'Data da medicao', 'Valor medido'))
        empreiteiro_row = next(row for row in ws.iter_rows(values_only=True) if row and row[1] == 'Empreiteiro Relatorio')
        self.assertEqual(empreiteiro_row[1], 'Empreiteiro Relatorio')
        self.assertTrue(ws.auto_filter.ref)
        self.assertTrue(ws.freeze_panes)

        pdf = self.client.get(
            reverse('relatorio_medicoes'),
            {
                'tipo': 'empreiteiro',
                'empreiteiro': empreiteiro.id,
                'colunas': [choice[0] for choice in RelatorioMedicoesForm.COLUNAS_CHOICES],
                'export': 'pdf',
            },
        )
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_exclui_planilha_importada(self):
        orcamento, item = self._orcamento()

        response = self.client.post(reverse('excluir_orcamento_medicao', args=[orcamento.id]))

        self.assertRedirects(response, reverse('medicoes_obra', args=[self.obra.id]))
        self.assertFalse(OrcamentoMedicao.objects.filter(id=orcamento.id).exists())
        self.assertFalse(ItemOrcamentoMedicao.objects.filter(id=item.id).exists())

    def test_abre_formulario_medicao_simples(self):
        response = self.client.get(reverse('nova_medicao_empreiteiro_simples'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recibo simples de medição')
        self.assertContains(response, 'Adicionar item')
        self.assertContains(response, 'Buscar por nome, CPF/CNPJ ou PIX')
        self.assertNotContains(response, 'Empreiteiro novo/manual')
        self.assertContains(response, 'name="itens-TOTAL_FORMS" value="0"')

    def test_telas_separadas_de_medicao_carregam(self):
        orcamento, item = self._orcamento()
        del item
        response_construtora = self.client.get(reverse('medicoes_construtora_home'))
        response_empreiteiros = self.client.get(reverse('medicoes_empreiteiros_home'))
        response_obra = self.client.get(reverse('medicoes_obra', args=[self.obra.id]))

        self.assertContains(response_construtora, 'Medicao da construtora')
        self.assertNotContains(response_construtora, orcamento.nome)
        self.assertContains(response_empreiteiros, 'Medicoes de contratados')
        self.assertContains(response_obra, 'Medições da construtora')

    def test_homes_de_medicoes_sao_paineis_leves(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 5, 1),
            periodo_fim=date(2026, 5, 31),
            data_medicao=date(2026, 5, 31),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('10'))
        contratado = Empreiteiro.objects.create(empresa=self.empresa, nome='Contratado Oculto')
        medicao_contratado = MedicaoEmpreiteiro.objects.create(
            empresa=self.empresa,
            tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
            obra=self.obra,
            empreiteiro_cadastro=contratado,
            empreiteiro=contratado.nome,
            numero=1,
            periodo_inicio=date(2026, 5, 1),
            periodo_fim=date(2026, 5, 31),
            data_medicao=date(2026, 5, 31),
        )
        ItemMedicaoEmpreiteiro.objects.create(
            medicao=medicao_contratado,
            item='1',
            descricao='Servico que nao deve aparecer na home',
            quantidade_periodo=Decimal('1'),
            valor_unitario=Decimal('100.00'),
        )

        response_home = self.client.get(reverse('medicoes_home'))
        response_construtora = self.client.get(reverse('medicoes_construtora_home'))
        response_contratados = self.client.get(reverse('medicoes_empreiteiros_home'))

        self.assertContains(response_home, 'Painel operacional')
        self.assertNotContains(response_home, orcamento.nome)
        self.assertNotContains(response_home, 'Contratado Oculto')
        self.assertNotContains(response_home, 'Ultimas medicoes')
        self.assertNotContains(response_construtora, 'Obras com medicao da construtora')
        self.assertNotContains(response_construtora, orcamento.nome)
        self.assertNotContains(response_construtora, 'Ultimas medicoes')
        self.assertNotContains(response_contratados, 'Servico que nao deve aparecer na home')
        self.assertNotContains(response_contratados, 'Empreiteiros')
        self.assertContains(response_contratados, 'Contratados')

    def test_urls_principais_de_medicoes_foram_preservadas(self):
        urls = [
            'medicoes_home',
            'medicoes_construtora_home',
            'medicoes_empreiteiros_home',
            'lista_orcamentos_medicao',
            'relatorio_medicoes',
        ]
        for url_name in urls:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)

    def test_contadores_das_homes_respeitam_empresa_ativa(self):
        outra_empresa = Empresa.objects.create(nome='Empresa Fora do Tenant', slug='fora-do-tenant')
        outra_obra = Obra.objects.create(empresa=outra_empresa, nome_obra='Obra Fora', cliente='Cliente Fora')
        OrcamentoMedicao.objects.create(
            obra=outra_obra,
            nome='Planilha Fora do Tenant',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )
        outro_contratado = Empreiteiro.objects.create(empresa=outra_empresa, nome='Contratado Fora')
        MedicaoEmpreiteiro.objects.create(
            empresa=outra_empresa,
            tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
            obra=outra_obra,
            empreiteiro_cadastro=outro_contratado,
            empreiteiro=outro_contratado.nome,
            numero=1,
            periodo_inicio=date(2026, 6, 1),
            periodo_fim=date(2026, 6, 30),
            data_medicao=date(2026, 6, 30),
        )

        orcamento, item = self._orcamento()
        del orcamento, item
        contratado = Empreiteiro.objects.create(empresa=self.empresa, nome='Contratado do Tenant')
        MedicaoEmpreiteiro.objects.create(
            empresa=self.empresa,
            tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
            obra=self.obra,
            empreiteiro_cadastro=contratado,
            empreiteiro=contratado.nome,
            numero=1,
            periodo_inicio=date(2026, 6, 1),
            periodo_fim=date(2026, 6, 30),
            data_medicao=date(2026, 6, 30),
        )

        response_home = self.client.get(reverse('medicoes_home'))
        response_construtora = self.client.get(reverse('medicoes_construtora_home'))
        response_contratados = self.client.get(reverse('medicoes_empreiteiros_home'))

        self.assertEqual(response_home.context['total_planilhas_construtora'], 1)
        self.assertEqual(response_home.context['total_contratados_ativos'], 1)
        self.assertEqual(response_construtora.context['total_planilhas'], 1)
        self.assertEqual(response_construtora.context['total_obras_com_planilha'], 1)
        self.assertEqual(response_contratados.context['total_simples'], 1)
        self.assertNotContains(response_home, 'Fora do Tenant')

    def test_homes_de_medicoes_mantem_baixo_numero_de_queries(self):
        self._medicao_construtora_com_itens(quantidade=8)
        self._medicao_empreiteiro_cumulativa_com_itens(quantidade=8)

        for url_name in ['medicoes_home', 'medicoes_construtora_home', 'medicoes_empreiteiros_home']:
            with self.subTest(url_name=url_name):
                with CaptureQueriesContext(connection) as captured:
                    response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertLessEqual(len(captured), 35)

    def test_resumo_otimizado_planilhas_construtora_equivale_as_properties(self):
        orcamento, item = self._orcamento()
        ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            tipo=ItemOrcamentoMedicao.TIPO_GRUPO,
            ordem=0,
            item='1',
            descricao='Grupo que nao deve somar',
        )
        segunda_medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=2,
            periodo_inicio=date(2026, 7, 1),
            periodo_fim=date(2026, 7, 31),
            data_medicao=date(2026, 7, 31),
        )
        terceira_medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=3,
            periodo_inicio=date(2026, 8, 1),
            periodo_fim=date(2026, 8, 31),
            data_medicao=date(2026, 8, 31),
        )
        ItemMedicaoConstrutora.objects.create(medicao=segunda_medicao, item_orcamento=item, quantidade_periodo=Decimal('10'))
        ItemMedicaoConstrutora.objects.create(medicao=terceira_medicao, item_orcamento=item, quantidade_periodo=Decimal('15'))
        zero = OrcamentoMedicao.objects.create(
            obra=self.obra,
            nome='Planilha zero',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )

        planilhas = {
            planilha.id: planilha
            for planilha in anotar_resumo_planilhas_construtora(
                OrcamentoMedicao.objects.filter(id__in=[orcamento.id, zero.id])
            )
        }

        otimizada = planilhas[orcamento.id]
        self.assertEqual(otimizada.total_contrato_otimizado, orcamento.total_orcamento)
        self.assertEqual(otimizada.total_medido_otimizado, orcamento.total_medido_construtora)
        self.assertEqual(otimizada.saldo_otimizado, orcamento.saldo_medir_construtora)
        self.assertEqual(otimizada.percentual_medido_otimizado.quantize(Decimal('0.01')), orcamento.percentual_medido_construtora)
        self.assertEqual(otimizada.quantidade_medicoes, 2)

        zero_otimizada = planilhas[zero.id]
        self.assertEqual(zero_otimizada.total_contrato_otimizado, Decimal('0'))
        self.assertEqual(zero_otimizada.total_medido_otimizado, Decimal('0'))
        self.assertEqual(zero_otimizada.saldo_otimizado, Decimal('0'))
        self.assertEqual(zero_otimizada.percentual_medido_otimizado, Decimal('0'))

    def test_lista_planilhas_construtora_filtra_busca_e_preserva_tenant(self):
        orcamento, item = self._orcamento()
        del item
        orcamento.nome = 'Planilha Alpha'
        orcamento.save(update_fields=['nome'])
        outra_obra = Obra.objects.create(empresa=self.empresa, nome_obra='Obra Beta', cliente='Cliente')
        OrcamentoMedicao.objects.create(
            obra=outra_obra,
            nome='Planilha Beta',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )
        outra_empresa = Empresa.objects.create(nome='Empresa B', slug='empresa-b-planilhas')
        obra_externa = Obra.objects.create(empresa=outra_empresa, nome_obra='Obra Externa', cliente='Cliente')
        OrcamentoMedicao.objects.create(
            obra=obra_externa,
            nome='Planilha Externa',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )

        response_busca = self.client.get(reverse('lista_planilhas_construtora'), {'q': 'Alpha'})
        self.assertContains(response_busca, 'Planilha Alpha')
        self.assertNotContains(response_busca, 'Planilha Beta')
        self.assertNotContains(response_busca, 'Planilha Externa')

        response_obra = self.client.get(reverse('lista_planilhas_construtora'), {'obra': outra_obra.id})
        self.assertContains(response_obra, 'Planilha Beta')
        self.assertNotContains(response_obra, 'Planilha Alpha')

        response_cross_tenant = self.client.get(reverse('lista_planilhas_construtora'), {'obra': obra_externa.id})
        self.assertNotContains(response_cross_tenant, 'Planilha Externa')
        self.assertEqual(response_cross_tenant.context['total_resultados'], 0)

    def test_lista_planilhas_construtora_filtra_saldo_ordena_e_pagina(self):
        for index in range(30):
            orcamento = OrcamentoMedicao.objects.create(
                obra=self.obra,
                nome=f'Planilha paginada {index:02d}',
                tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
            )
            item = ItemOrcamentoMedicao.objects.create(
                orcamento=orcamento,
                item=str(index),
                descricao='Servico paginado',
                unidade='m2',
                quantidade=Decimal('10.0000'),
                preco_unitario_material=Decimal('10.0000'),
            )
            if index % 2 == 0:
                medicao = MedicaoConstrutora.objects.create(
                    orcamento=orcamento,
                    numero=1,
                    periodo_inicio=date(2026, 9, 1),
                    periodo_fim=date(2026, 9, 30),
                    data_medicao=date(2026, 9, 30),
                )
                ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('10.0000'))

        response = self.client.get(reverse('lista_planilhas_construtora'), {'ordem': 'saldo'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['planilhas']), 25)
        self.assertContains(response, 'page=2')

        response_page_2 = self.client.get(reverse('lista_planilhas_construtora'), {'ordem': 'saldo', 'page': 2})
        self.assertEqual(len(response_page_2.context['planilhas']), 5)

        response_com_saldo = self.client.get(reverse('lista_planilhas_construtora'), {'saldo': 'com'})
        self.assertEqual(response_com_saldo.context['total_resultados'], 15)

        response_sem_saldo = self.client.get(reverse('lista_planilhas_construtora'), {'saldo': 'sem'})
        self.assertEqual(response_sem_saldo.context['total_resultados'], 15)

    def test_lista_planilhas_construtora_nao_cresce_queries_por_planilha(self):
        for index in range(35):
            orcamento = OrcamentoMedicao.objects.create(
                obra=self.obra,
                nome=f'Planilha query {index:02d}',
                tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
            )
            ItemOrcamentoMedicao.objects.create(
                orcamento=orcamento,
                item=str(index),
                descricao='Servico query',
                unidade='m2',
                quantidade=Decimal('1.0000'),
                preco_unitario_material=Decimal('100.0000'),
            )

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse('lista_planilhas_construtora'))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(captured), 20)

    def test_resumo_otimizado_medicoes_construtora_equivale_ao_service_oficial(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 10, 1),
            periodo_fim=date(2026, 10, 31),
            data_medicao=date(2026, 10, 31),
            retencao_tecnica_percentual=Decimal('2.0000'),
            issqn_percentual=Decimal('5.0000'),
            inss_percentual=Decimal('11.0000'),
            desconto_adicional_percentual=Decimal('10.0000'),
            desconto_adicional_reduz_base_nf=True,
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('20'))
        faturamento = FaturamentoDireto.objects.create(
            obra=self.obra,
            data_lancamento=date(2026, 10, 15),
            numero_nf='FD-1',
            empresa_comprou='Cliente teste',
            valor_nota=Decimal('100.00'),
            descricao='Material faturado direto',
            vencimento_boleto='30/10/2026',
        )
        FaturamentoDiretoMedicao.objects.create(
            medicao=medicao,
            faturamento_direto=faturamento,
            percentual_descontado=Decimal('50.0000'),
        )
        resumo = calcular_resumo_construtora(medicao)
        otimizada = anotar_resumo_medicoes_construtora(MedicaoConstrutora.objects.filter(id=medicao.id)).get()

        self.assertEqual(otimizada.subtotal_otimizado.quantize(Decimal('0.01')), resumo.subtotal_periodo.quantize(Decimal('0.01')))
        self.assertEqual(otimizada.faturamento_direto_otimizado.quantize(Decimal('0.01')), resumo.total_faturamento_direto.quantize(Decimal('0.01')))
        self.assertEqual(otimizada.desconto_adicional_otimizado.quantize(Decimal('0.01')), resumo.desconto_adicional_calculado.quantize(Decimal('0.01')))
        self.assertEqual(otimizada.retencao_tecnica_otimizada.quantize(Decimal('0.01')), resumo.retencao_tecnica_calculada.quantize(Decimal('0.01')))
        self.assertEqual(otimizada.issqn_otimizado.quantize(Decimal('0.01')), resumo.issqn_calculado.quantize(Decimal('0.01')))
        self.assertEqual(otimizada.inss_otimizado.quantize(Decimal('0.01')), resumo.inss_calculado.quantize(Decimal('0.01')))
        self.assertEqual(otimizada.impostos_otimizados.quantize(Decimal('0.01')), (resumo.issqn_calculado + resumo.inss_calculado).quantize(Decimal('0.01')))
        self.assertEqual(otimizada.total_liquido_otimizado.quantize(Decimal('0.01')), resumo.total_liquido.quantize(Decimal('0.01')))

    def test_lista_medicoes_construtora_filtra_por_obra_planilha_numero_e_datas(self):
        orcamento, item = self._orcamento()
        primeira = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        ItemMedicaoConstrutora.objects.create(medicao=primeira, item_orcamento=item, quantidade_periodo=Decimal('10'))
        segunda = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=2,
            periodo_inicio=date(2026, 2, 1),
            periodo_fim=date(2026, 2, 28),
            data_medicao=date(2026, 2, 28),
        )
        ItemMedicaoConstrutora.objects.create(medicao=segunda, item_orcamento=item, quantidade_periodo=Decimal('20'))
        outra_obra = Obra.objects.create(empresa=self.empresa, nome_obra='Obra de outra medicao', cliente='Cliente')
        outro_orcamento = OrcamentoMedicao.objects.create(
            obra=outra_obra,
            nome='Planilha outra obra',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )
        outro_item = ItemOrcamentoMedicao.objects.create(
            orcamento=outro_orcamento,
            item='1',
            descricao='Servico outra obra',
            unidade='m2',
            quantidade=Decimal('1'),
            preco_unitario_material=Decimal('1'),
        )
        terceira = MedicaoConstrutora.objects.create(
            orcamento=outro_orcamento,
            numero=1,
            periodo_inicio=date(2026, 3, 1),
            periodo_fim=date(2026, 3, 31),
            data_medicao=date(2026, 3, 31),
        )
        ItemMedicaoConstrutora.objects.create(medicao=terceira, item_orcamento=outro_item, quantidade_periodo=Decimal('1'))

        response_planilha = self.client.get(reverse('lista_medicoes_construtora'), {'planilha': orcamento.id})
        self.assertEqual([medicao.orcamento_id for medicao in response_planilha.context['medicoes']], [orcamento.id, orcamento.id])

        response_obra = self.client.get(reverse('lista_medicoes_construtora'), {'obra': outra_obra.id})
        self.assertEqual([medicao.id for medicao in response_obra.context['medicoes']], [terceira.id])

        response_numero = self.client.get(reverse('lista_medicoes_construtora'), {'numero': 2})
        self.assertEqual([medicao.id for medicao in response_numero.context['medicoes']], [segunda.id])

        response_data = self.client.get(
            reverse('lista_medicoes_construtora'),
            {'data_inicio': '2026-02-01', 'data_fim': '2026-02-28'},
        )
        self.assertEqual([medicao.id for medicao in response_data.context['medicoes']], [segunda.id])

        response_invalido = self.client.get(reverse('lista_medicoes_construtora'), {'numero': 'abc', 'data_inicio': 'invalida'})
        self.assertEqual(response_invalido.status_code, 200)

    def test_lista_medicoes_construtora_preserva_tenant_e_get_cross_tenant(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 4, 1),
            periodo_fim=date(2026, 4, 30),
            data_medicao=date(2026, 4, 30),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('10'))
        outra_empresa = Empresa.objects.create(nome='Empresa Medicao Fora', slug='empresa-medicao-fora')
        obra_externa = Obra.objects.create(empresa=outra_empresa, nome_obra='Obra externa medicao', cliente='Cliente')
        planilha_externa = OrcamentoMedicao.objects.create(
            obra=obra_externa,
            nome='Planilha externa medicao',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )
        item_externo = ItemOrcamentoMedicao.objects.create(
            orcamento=planilha_externa,
            item='1',
            descricao='Servico externo',
            unidade='m2',
            quantidade=Decimal('1'),
            preco_unitario_material=Decimal('1'),
        )
        medicao_externa = MedicaoConstrutora.objects.create(
            orcamento=planilha_externa,
            numero=1,
            periodo_inicio=date(2026, 4, 1),
            periodo_fim=date(2026, 4, 30),
            data_medicao=date(2026, 4, 30),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao_externa, item_orcamento=item_externo, quantidade_periodo=Decimal('1'))

        response_obra = self.client.get(reverse('lista_medicoes_construtora'), {'obra': obra_externa.id})
        self.assertEqual(response_obra.context['total_resultados'], 0)
        self.assertNotContains(response_obra, 'Planilha externa medicao')

        response_planilha = self.client.get(reverse('lista_medicoes_construtora'), {'planilha': planilha_externa.id})
        self.assertEqual(response_planilha.context['total_resultados'], 0)
        self.assertNotContains(response_planilha, 'Obra externa medicao')

    def test_lista_medicoes_construtora_pagina_ordena_acoes_e_querystring(self):
        orcamento, item = self._orcamento()
        for index in range(30):
            medicao = MedicaoConstrutora.objects.create(
                orcamento=orcamento,
                numero=index + 1,
                periodo_inicio=date(2026, 5, 1),
                periodo_fim=date(2026, 5, 31),
                data_medicao=date(2026, 5, 1 if index < 15 else 2),
            )
            ItemMedicaoConstrutora.objects.create(
                medicao=medicao,
                item_orcamento=item,
                quantidade_periodo=Decimal(index + 1),
            )

        response = self.client.get(reverse('lista_medicoes_construtora'), {'obra': self.obra.id, 'ordem': 'bruto'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['medicoes']), 25)
        self.assertContains(response, 'page=2')
        self.assertContains(response, f'obra={self.obra.id}')
        self.assertContains(response, reverse('medicao_construtora_pdf', args=[response.context['medicoes'][0].id]))
        self.assertContains(response, reverse('medicao_construtora_excel', args=[response.context['medicoes'][0].id]))
        self.assertContains(response, reverse('excluir_medicao_construtora', args=[response.context['medicoes'][0].id]))

        response_page_2 = self.client.get(reverse('lista_medicoes_construtora'), {'obra': self.obra.id, 'ordem': 'bruto', 'page': 2})
        self.assertEqual(len(response_page_2.context['medicoes']), 5)

    def test_lista_medicoes_construtora_nao_cresce_queries_por_medicao(self):
        orcamento, item = self._orcamento()
        for index in range(35):
            medicao = MedicaoConstrutora.objects.create(
                orcamento=orcamento,
                numero=index + 1,
                periodo_inicio=date(2026, 6, 1),
                periodo_fim=date(2026, 6, 30),
                data_medicao=date(2026, 6, 30),
            )
            ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('1'))

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse('lista_medicoes_construtora'))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(captured), 22)

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

        excel = self.client.get(reverse('medicao_construtora_excel', args=[segunda.id]))
        wb = load_workbook(BytesIO(excel.content))
        rows = list(wb.active.iter_rows(values_only=True))
        self.assertTrue(any(row and row[0] == 'Itens contratuais' for row in rows))
        headers = next(row for row in rows if row and row[0] == 'Item')
        self.assertIn('Unit. material', headers)
        self.assertIn('Unit. mao obra', headers)
        self.assertIn('Material', headers)
        self.assertIn('Mao de obra', headers)
        self.assertIn('Equip.', headers)

    def test_resumo_otimizado_preserva_calculos_financeiros_construtora(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
            retencao_tecnica_percentual=Decimal('2.0000'),
            issqn_percentual=Decimal('5.0000'),
            inss_percentual=Decimal('11.0000'),
            desconto_adicional=Decimal('40.00'),
            desconto_adicional_reduz_base_nf=True,
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('10'))
        faturamento = FaturamentoDireto.objects.create(
            obra=self.obra,
            numero_nf='FD-REG',
            empresa_comprou='Cliente',
            valor_nota=Decimal('30.00'),
            descricao='Faturamento direto regressao',
            vencimento_boleto='30 dias',
        )
        FaturamentoDiretoMedicao.objects.create(medicao=medicao, faturamento_direto=faturamento, percentual_descontado=Decimal('50.0000'))

        medicao_fallback = MedicaoConstrutora.objects.get(id=medicao.id)
        esperado = {
            'subtotal': medicao_fallback.subtotal_periodo,
            'faturamento_direto': medicao_fallback.total_faturamento_direto,
            'desconto': medicao_fallback.desconto_adicional_calculado,
            'retencao': medicao_fallback.retencao_tecnica_calculada,
            'inss': medicao_fallback.inss_calculado,
            'issqn': medicao_fallback.issqn_calculado,
            'base_nf': medicao_fallback.base_impostos,
            'material': medicao_fallback.valor_material_nf,
            'mao_obra': medicao_fallback.valor_mao_obra_nf,
            'equipamentos': medicao_fallback.valor_equipamentos_nf,
            'total_liquido': medicao_fallback.total_liquido,
        }

        linhas, _ = itens_construtora_com_grupos(medicao)
        resumo = calcular_resumo_construtora(
            medicao,
            itens=linhas,
            faturamentos=list(medicao.faturamentos_diretos.select_related('faturamento_direto')),
        )

        self.assertEqual(resumo.subtotal_periodo, esperado['subtotal'])
        self.assertEqual(resumo.total_faturamento_direto, esperado['faturamento_direto'])
        self.assertEqual(resumo.desconto_adicional_calculado, esperado['desconto'])
        self.assertEqual(resumo.retencao_tecnica_calculada, esperado['retencao'])
        self.assertEqual(resumo.inss_calculado, esperado['inss'])
        self.assertEqual(resumo.issqn_calculado, esperado['issqn'])
        self.assertEqual(resumo.base_impostos, esperado['base_nf'])
        self.assertEqual(resumo.valor_material_nf, esperado['material'])
        self.assertEqual(resumo.valor_mao_obra_nf, esperado['mao_obra'])
        self.assertEqual(resumo.valor_equipamentos_nf, esperado['equipamentos'])
        self.assertEqual(resumo.total_liquido, esperado['total_liquido'])

    def test_acumulado_otimizado_preserva_edicao_de_medicao_antiga(self):
        _, itens, primeira, segunda, terceira = self._medicao_construtora_com_itens(quantidade=3)
        linhas, _ = itens_construtora_com_grupos(segunda)
        itens_medidos = [linha for linha in linhas if isinstance(linha, ItemMedicaoConstrutora)]

        self.assertEqual(itens_medidos[0].quantidade_acumulada_anterior, Decimal('10.0000'))
        self.assertEqual(itens_medidos[0].quantidade_acumulada_atual, Decimal('25.0000'))
        self.assertEqual(terceira.itens.get(item_orcamento=itens[0]).quantidade_acumulada_anterior, Decimal('25.0000'))
        self.assertEqual(primeira.itens.get(item_orcamento=itens[0]).quantidade_acumulada_anterior, Decimal('0'))

    def test_views_pesadas_de_medicao_nao_executam_query_por_item(self):
        _, _, _, segunda, _ = self._medicao_construtora_com_itens(quantidade=30)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('editar_medicao_construtora', args=[segunda.id]))
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(ctx.captured_queries), 90)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('medicao_construtora_pdf', args=[segunda.id]))
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(ctx.captured_queries), 40)

    def test_relatorio_medicoes_nao_recalcula_totais_por_linha(self):
        orcamento, item = self._orcamento()
        for numero in range(1, 21):
            medicao = MedicaoConstrutora.objects.create(
                orcamento=orcamento,
                numero=numero,
                periodo_inicio=date(2026, 1, 1),
                periodo_fim=date(2026, 1, 31),
                data_medicao=date(2026, 1, 31),
            )
            ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('1'))

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('relatorio_medicoes'))

        self.assertEqual(response.status_code, 200)
        self.assertLess(len(ctx.captured_queries), 60)

    def test_pdf_empreiteiro_cumulativo_usa_acumulados_em_lote(self):
        _, _, _, segunda = self._medicao_empreiteiro_cumulativa_com_itens(quantidade=30)
        itens = itens_empreiteiro_com_acumulados(segunda)

        self.assertEqual(itens[0].quantidade_acumulada_anterior, Decimal('10.0000'))
        self.assertEqual(itens[0].quantidade_acumulada_atual, Decimal('25.0000'))

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('medicao_empreiteiro_pdf', args=[segunda.id]))

        self.assertEqual(response.status_code, 200)
        self.assertLess(len(ctx.captured_queries), 35)

    def test_edicao_medicao_construtora_rollback_quando_etapa_relacionada_falha(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        item_medicao = ItemMedicaoConstrutora.objects.create(
            medicao=medicao,
            item_orcamento=item,
            quantidade_periodo=Decimal('5'),
        )

        payload = {
            'numero': '1',
            'periodo_inicio': '2026-01-01',
            'periodo_fim': '2026-01-31',
            'data_medicao': '2026-01-31',
            'retencao_tecnica': '0',
            'retencao_tecnica_percentual': '0',
            'issqn': '0',
            'issqn_percentual': '0',
            'inss': '0',
            'inss_percentual': '0',
            'desconto_adicional': '0',
            'desconto_adicional_percentual': '0',
            'observacoes': 'alterado',
            'itens-TOTAL_FORMS': '1',
            'itens-INITIAL_FORMS': '1',
            'itens-MIN_NUM_FORMS': '0',
            'itens-MAX_NUM_FORMS': '1000',
            'itens-0-id': str(item_medicao.id),
            'itens-0-quantidade_periodo': '30',
        }
        with mock.patch('medicoes.views._sync_faturamentos_diretos', side_effect=RuntimeError('falha controlada')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('editar_medicao_construtora', args=[medicao.id]), payload)

        item_medicao.refresh_from_db()
        medicao.refresh_from_db()
        self.assertEqual(item_medicao.quantidade_periodo, Decimal('5.0000'))
        self.assertEqual(medicao.observacoes, '')

    def test_medicao_construtora_salva_mesmo_com_grupo_antigo_na_medicao(self):
        orcamento, item = self._orcamento()
        grupo = ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            tipo=ItemOrcamentoMedicao.TIPO_GRUPO,
            item='1',
            descricao='SERVICOS PRELIMINARES',
        )
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=grupo)
        item_medicao = ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item)

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
                'issqn_percentual': '0',
                'inss': '0',
                'inss_percentual': '0',
                'desconto_adicional': '0',
                'desconto_adicional_percentual': '0',
                'observacoes': '',
                'itens-TOTAL_FORMS': '1',
                'itens-INITIAL_FORMS': '1',
                'itens-MIN_NUM_FORMS': '0',
                'itens-MAX_NUM_FORMS': '1000',
                'itens-0-id': str(item_medicao.id),
                'itens-0-quantidade_periodo': '15',
            },
        )

        self.assertRedirects(response, reverse('editar_medicao_construtora', args=[medicao.id]))
        item_medicao.refresh_from_db()
        self.assertEqual(item_medicao.quantidade_periodo, Decimal('15'))
        self.assertFalse(medicao.itens.filter(item_orcamento=grupo).exists())

    def test_editar_grupo_construtora_preserva_itens_nao_renderizados(self):
        orcamento = OrcamentoMedicao.objects.create(
            obra=self.obra,
            nome='Orcamento com grupos',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )
        grupo_a = ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            tipo=ItemOrcamentoMedicao.TIPO_GRUPO,
            item='1',
            descricao='Grupo A',
            ordem=1,
        )
        item_a = ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            item='1.1',
            descricao='Servico A',
            unidade='m2',
            quantidade=Decimal('100.0000'),
            preco_unitario_mao_obra=Decimal('10.0000'),
            ordem=2,
        )
        ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            tipo=ItemOrcamentoMedicao.TIPO_GRUPO,
            item='2',
            descricao='Grupo B',
            ordem=3,
        )
        item_b = ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            item='2.1',
            descricao='Servico B',
            unidade='m2',
            quantidade=Decimal('100.0000'),
            preco_unitario_mao_obra=Decimal('10.0000'),
            ordem=4,
        )
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        medicao_a = ItemMedicaoConstrutora.objects.create(
            medicao=medicao,
            item_orcamento=item_a,
            quantidade_periodo=Decimal('5.0000'),
        )
        medicao_b = ItemMedicaoConstrutora.objects.create(
            medicao=medicao,
            item_orcamento=item_b,
            quantidade_periodo=Decimal('7.0000'),
        )

        url = f"{reverse('editar_medicao_construtora', args=[medicao.id])}?grupo={grupo_a.id}"
        response = self.client.get(url)
        self.assertEqual(response.context['escopo_itens']['total_renderizado'], 1)
        self.assertContains(response, 'Servico A')
        self.assertNotContains(response, 'Servico B')

        response = self.client.post(
            url,
            {
                'numero': '1',
                'periodo_inicio': '2026-01-01',
                'periodo_fim': '2026-01-31',
                'data_medicao': '2026-01-31',
                'retencao_tecnica': '0',
                'retencao_tecnica_percentual': '0',
                'issqn': '0',
                'issqn_percentual': '0',
                'inss': '0',
                'inss_percentual': '0',
                'desconto_adicional': '0',
                'desconto_adicional_percentual': '0',
                'observacoes': '',
                'itens-TOTAL_FORMS': '1',
                'itens-INITIAL_FORMS': '1',
                'itens-MIN_NUM_FORMS': '0',
                'itens-MAX_NUM_FORMS': '1000',
                'itens-0-id': str(medicao_a.id),
                'itens-0-quantidade_periodo': '12',
            },
        )

        self.assertRedirects(response, f"{reverse('editar_medicao_construtora', args=[medicao.id])}?grupo={grupo_a.id}&tab=itens")
        medicao_a.refresh_from_db()
        medicao_b.refresh_from_db()
        self.assertEqual(medicao_a.quantidade_periodo, Decimal('12.0000'))
        self.assertEqual(medicao_b.quantidade_periodo, Decimal('7.0000'))

    def test_tela_construtora_exibe_percentual_do_item_visivel(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        ItemMedicaoConstrutora.objects.create(
            medicao=medicao,
            item_orcamento=item,
            quantidade_periodo=Decimal('25.0000'),
        )

        response = self.client.get(reverse('editar_medicao_construtora', args=[medicao.id]))

        self.assertContains(response, '25,00%')

    def test_medicao_empreiteiro_grande_renderiza_apenas_pagina_atual(self):
        _, _, _, segunda = self._medicao_empreiteiro_cumulativa_com_itens(quantidade=300)

        response = self.client.get(f"{reverse('editar_medicao_empreiteiro', args=[segunda.id])}?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['escopo_itens']['total_itens'], 300)
        self.assertEqual(response.context['escopo_itens']['total_renderizado'], 50)
        self.assertContains(response, 'Pagina 2 de 6')
        self.assertContains(response, 'itens-TOTAL_FORMS" value="50"')

    def test_grupo_grande_construtora_renderiza_apenas_pagina_atual(self):
        orcamento = OrcamentoMedicao.objects.create(
            obra=self.obra,
            nome='Orcamento grupo grande',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )
        grupo = ItemOrcamentoMedicao.objects.create(
            orcamento=orcamento,
            tipo=ItemOrcamentoMedicao.TIPO_GRUPO,
            item='1',
            descricao='Grupo grande',
            ordem=1,
        )
        itens = [
            ItemOrcamentoMedicao.objects.create(
                orcamento=orcamento,
                item=f'1.{index}',
                descricao=f'Servico grupo grande {index}',
                unidade='m2',
                quantidade=Decimal('100.0000'),
                preco_unitario_mao_obra=Decimal('10.0000'),
                ordem=index + 1,
            )
            for index in range(1, 121)
        ]
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        for item in itens:
            ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item)

        response = self.client.get(f"{reverse('editar_medicao_construtora', args=[medicao.id])}?grupo={grupo.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['escopo_itens']['total_renderizado'], 50)
        self.assertContains(response, 'Pagina 1 de 3')
        self.assertContains(response, 'itens-TOTAL_FORMS" value="50"')

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
                f'faturamento_direto_{faturamento.id}_percentual': '50',
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
        self.assertEqual(medicao.total_faturamento_direto, Decimal('50.00'))
        self.assertEqual(medicao.issqn, Decimal('14.50'))
        self.assertEqual(medicao.inss, Decimal('10.00'))
        self.assertEqual(medicao.total_liquido, Decimal('265.50'))
        self.assertEqual(faturamento.medicao_desconto, 'Medicao 1 (50.00%)')

    def test_pdf_medicao_construtora_pagina_faturamentos_diretos_extensos(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('20'))
        for index in range(12):
            faturamento = FaturamentoDireto.objects.create(
                obra=self.obra,
                numero_nf=f'FD-{index + 1}',
                empresa_comprou='Cliente',
                valor_nota=Decimal('100.00'),
                descricao=f'Material comprado direto {index + 1}',
                vencimento_boleto='30 dias',
            )
            FaturamentoDiretoMedicao.objects.create(medicao=medicao, faturamento_direto=faturamento)

        response = self.client.get(reverse('medicao_construtora_pdf', args=[medicao.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_pdf_table_wrap_nao_adiciona_reticencias_artificiais(self):
        doc = PdfDocument(empresa=self.empresa, title='Teste')
        drawn_texts = []
        original_text = doc.draw.text

        def capture_text(position, text, *args, **kwargs):
            drawn_texts.append(str(text))
            return original_text(position, text, *args, **kwargs)

        texto_longo = (
            'DESCRICAO_INICIO_123 Execucao de assentamento de piso em basalto serrado 40x40 cm '
            'incluindo preparacao da base posicionamento nivelamento rejuntamento limpeza final '
            'e demais servicos necessarios a perfeita execucao do item DESCRICAO_FINAL_987'
        )
        with mock.patch.object(doc.draw, 'text', side_effect=capture_text):
            doc.add_table(
                [
                    PdfTableColumn('item', 'Item', width=90),
                    PdfTableColumn('descricao', 'Descricao', width=560),
                ],
                [{'item': '1', 'descricao': texto_longo}],
                row_height='auto',
                overflow='wrap',
            )

        self.assertFalse(any(text.endswith('...') for text in drawn_texts if 'DESCRICAO' in text or 'Execucao' in text))
        self.assertTrue(any('DESCRICAO_INICIO_123' in text for text in drawn_texts))
        self.assertTrue(any('DESCRICAO_FINAL_987' in text for text in drawn_texts))

    def test_pdfs_medicoes_geram_com_descricoes_extensas_sem_alterar_dados(self):
        textos = {
            '100': 'DESCRICAO_100 ' + ('Servico medido longo ' * 4),
            '200': 'DESCRICAO_200 ' + ('Execucao completa com preparo nivelamento conferencia e limpeza final ' * 3),
            '255': ('DESCRICAO_INICIO_123 ' + ('assentamento basalto serrado com rejuntamento nivelamento e limpeza final ' * 4))[:255],
        }
        orcamento = OrcamentoMedicao.objects.create(
            obra=self.obra,
            nome='Orcamento descricoes extensas',
            tipo=OrcamentoMedicao.TIPO_CONSTRUTORA,
        )
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
        )
        for ordem, descricao in enumerate(textos.values(), start=1):
            item = ItemOrcamentoMedicao.objects.create(
                orcamento=orcamento,
                item=str(ordem),
                descricao=descricao,
                unidade='m2',
                quantidade=Decimal('10.0000'),
                preco_unitario_material=Decimal('100.0000'),
            )
            ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('1.0000'))

        pdf = self.client.get(reverse('medicao_construtora_pdf', args=[medicao.id]))
        excel = self.client.get(reverse('medicao_construtora_excel', args=[medicao.id]))

        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        wb = load_workbook(BytesIO(excel.content))
        valores_excel = [cell for row in wb.active.iter_rows(values_only=True) for cell in row if isinstance(cell, str)]
        self.assertTrue(any(textos['100'] in value for value in valores_excel))
        self.assertTrue(any(textos['200'] in value for value in valores_excel))
        self.assertTrue(any(textos['255'] in value for value in valores_excel))

    def test_pdf_empreiteiro_observacao_longa_usa_bloco_de_texto(self):
        medicao = MedicaoEmpreiteiro.objects.create(
            empresa=self.empresa,
            obra=self.obra,
            tipo=MedicaoEmpreiteiro.TIPO_SIMPLES,
            empreiteiro='Empreiteiro',
            numero=77,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
            observacoes=(
                'Acerto referente aos servicos executados no periodo, incluindo atividades complementares '
                'realizadas conforme solicitacao da fiscalizacao e ajustes necessarios para conclusao dos servicos previstos.'
            ),
        )
        ItemMedicaoEmpreiteiro.objects.create(
            medicao=medicao,
            descricao='Servico simples com descricao longa para validar quebra integral da tabela',
            unidade='vb',
            quantidade_periodo=Decimal('1'),
            valor_unitario=Decimal('100.00'),
        )

        original_add_text_block = PdfDocument.add_text_block

        def spy_add_text_block(instance, title, text, *args, **kwargs):
            return original_add_text_block(instance, title, text, *args, **kwargs)

        with mock.patch.object(PdfDocument, 'add_text_block', autospec=True, side_effect=spy_add_text_block) as mocked_text_block:
            response = self.client.get(reverse('medicao_empreiteiro_pdf', args=[medicao.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertTrue(mocked_text_block.called)

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

    def test_desconto_adicional_pode_reduzir_base_da_nf(self):
        orcamento, item = self._orcamento()
        medicao = MedicaoConstrutora.objects.create(
            orcamento=orcamento,
            numero=1,
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 1, 31),
            data_medicao=date(2026, 1, 31),
            issqn_percentual=Decimal('5.00'),
            inss_percentual=Decimal('11.00'),
            desconto_adicional=Decimal('40.00'),
        )
        ItemMedicaoConstrutora.objects.create(medicao=medicao, item_orcamento=item, quantidade_periodo=Decimal('10'))

        self.assertEqual(medicao.subtotal_periodo, Decimal('170.00'))
        self.assertEqual(medicao.base_impostos, Decimal('170.00'))
        self.assertEqual(medicao.base_inss, Decimal('50.00'))
        self.assertEqual(medicao.total_material_periodo, Decimal('100.00'))
        self.assertEqual(medicao.total_mao_obra_periodo, Decimal('50.00'))
        self.assertEqual(medicao.total_equipamentos_periodo, Decimal('20.00'))
        self.assertEqual(medicao.issqn_calculado, Decimal('8.50'))
        self.assertEqual(medicao.inss_calculado, Decimal('5.50'))

        medicao.desconto_adicional_reduz_base_nf = True
        medicao.save(update_fields=['desconto_adicional_reduz_base_nf', 'updated_at'])

        self.assertEqual(medicao.base_impostos, Decimal('130.00'))
        self.assertEqual(medicao.base_inss, Decimal('38.24'))
        self.assertEqual(medicao.valor_material_nf, Decimal('76.47'))
        self.assertEqual(medicao.valor_mao_obra_nf, Decimal('38.24'))
        self.assertEqual(medicao.valor_equipamentos_nf, Decimal('15.29'))
        self.assertEqual(medicao.issqn_calculado, Decimal('6.50'))
        self.assertEqual(medicao.inss_calculado, Decimal('4.21'))

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
            empresa=self.empresa,
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
        wb = load_workbook(BytesIO(excel.content))
        ws = wb.active
        self.assertTrue(
            any('Contratado:' in str(cell.value) for row in ws.iter_rows(max_row=10) for cell in row if cell.value)
        )

    def test_medicao_simples_usa_cadastro_de_empreiteiro(self):
        empreiteiro = Empreiteiro.objects.create(
            empresa=self.empresa,
            nome='Empreiteiro cadastrado',
            cpf_cnpj='11.111.111/0001-11',
            pix='pix@empreiteiro.com',
        )

        response = self.client.post(
            reverse('nova_medicao_empreiteiro_simples'),
            {
                'obra': self.obra.id,
                'empreiteiro_cadastro': empreiteiro.id,
                'empreiteiro': '',
                'cpf_cnpj': '',
                'pix': '',
                'numero': '1',
                'periodo_inicio': '2026-03-01',
                'periodo_fim': '2026-03-31',
                'data_medicao': '2026-03-31',
                'observacoes': '',
                'itens-TOTAL_FORMS': '1',
                'itens-INITIAL_FORMS': '0',
                'itens-MIN_NUM_FORMS': '0',
                'itens-MAX_NUM_FORMS': '1000',
                'itens-0-item_orcamento': '',
                'itens-0-item': '1',
                'itens-0-descricao': 'Servico',
                'itens-0-unidade': 'un',
                'itens-0-quantidade_periodo': '1',
                'itens-0-valor_unitario': '100.00',
            },
        )

        medicao = MedicaoEmpreiteiro.objects.get()
        self.assertRedirects(response, reverse('editar_medicao_empreiteiro', args=[medicao.id]))
        self.assertEqual(medicao.empreiteiro_cadastro, empreiteiro)
        self.assertEqual(medicao.empreiteiro, 'Empreiteiro cadastrado')
        self.assertEqual(medicao.cpf_cnpj, '11.111.111/0001-11')
        self.assertEqual(medicao.pix, 'pix@empreiteiro.com')

    def test_medicao_sem_empreiteiro_cadastrado_nao_salva(self):
        orcamento, item = self._orcamento()
        orcamento.tipo = OrcamentoMedicao.TIPO_EMPREITEIRO
        orcamento.save(update_fields=['tipo'])

        response = self.client.post(
            reverse('nova_medicao_empreiteiro_cumulativa', args=[orcamento.id]),
            {
                'obra': self.obra.id,
                'empreiteiro_cadastro': '',
                'empreiteiro': 'Novo Empreiteiro',
                'cpf_cnpj': '22.222.222/0001-22',
                'pix': 'pix@novo.com',
                'numero': '1',
                'periodo_inicio': '2026-04-01',
                'periodo_fim': '2026-04-30',
                'data_medicao': '2026-04-30',
                'observacoes': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MedicaoEmpreiteiro.objects.filter(orcamento=orcamento).exists())
        self.assertFalse(Empreiteiro.objects.filter(nome='Novo Empreiteiro').exists())
        self.assertContains(response, 'Selecione um contratado cadastrado')

    def test_medicao_cumulativa_reaproveita_empreiteiro_cadastrado(self):
        empreiteiro = Empreiteiro.objects.create(
            empresa=self.empresa,
            nome='Novo Empreiteiro',
            cpf_cnpj='22.222.222/0001-22',
            pix='pix@novo.com',
        )
        orcamento, item = self._orcamento()
        orcamento.tipo = OrcamentoMedicao.TIPO_EMPREITEIRO
        orcamento.save(update_fields=['tipo'])

        primeira = MedicaoEmpreiteiro.objects.create(
            empresa=self.empresa,
            tipo=MedicaoEmpreiteiro.TIPO_CUMULATIVA,
            orcamento=orcamento,
            obra=self.obra,
            empreiteiro_cadastro=empreiteiro,
            empreiteiro=empreiteiro.nome,
            cpf_cnpj=empreiteiro.cpf_cnpj,
            pix=empreiteiro.pix,
            numero=1,
            periodo_inicio=date(2026, 4, 1),
            periodo_fim=date(2026, 4, 30),
            data_medicao=date(2026, 4, 30),
        )
        ItemMedicaoEmpreiteiro.objects.create(
            medicao=primeira,
            item_orcamento=item,
            quantidade_periodo=Decimal('1'),
        )

        response = self.client.get(reverse('nova_medicao_empreiteiro_cumulativa', args=[orcamento.id]))

        self.assertContains(response, 'Novo Empreiteiro')
        self.assertContains(response, 'pix@novo.com')

    def test_exclui_medicao_empreiteiro_simples(self):
        medicao = MedicaoEmpreiteiro.objects.create(
            empresa=self.empresa,
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
