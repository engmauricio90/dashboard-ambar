from decimal import Decimal
import os
from tempfile import NamedTemporaryFile

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from obras.models import Obra

from .models import (
    ApontamentoMaquinaLocacao,
    BombonaCombustivel,
    EquipamentoLocadoCatalogo,
    ContratoConcretagem,
    FornecedorMaquinaLocacao,
    FaturamentoConcretagem,
    HistoricoLocacaoMaquina,
    HistoricoOrdemCombustivel,
    LocacaoEquipamento,
    LocadoraEquipamento,
    MaquinaLocacaoCatalogo,
    NotaFiscalCombustivel,
    NotaFiscalLocacaoMaquina,
    OrcamentoRadarObra,
    OrdemCompraCombustivel,
    OrdemServicoLocacaoMaquina,
    RegistroAbastecimento,
    SolicitanteConcretagem,
    VeiculoMaquina,
)


class ControleAbastecimentoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='operador', password='senha-forte-123')
        self.client.force_login(self.user)

    def test_home_controles_carrega(self):
        response = self.client.get(reverse('controles_home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Controles Operacionais')
        self.assertContains(response, 'Controle de abastecimento')

    def test_cria_veiculo_maquina(self):
        response = self.client.post(
            reverse('novo_veiculo'),
            {
                'placa': 'abc1234',
                'descricao': 'Caminhonete obra',
                'tipo': 'carro',
                'status': 'ativo',
                'observacoes': '',
            },
        )

        self.assertRedirects(response, reverse('lista_veiculos'))
        veiculo = VeiculoMaquina.objects.get()
        self.assertEqual(veiculo.placa, 'ABC1234')

    def test_cria_registro_abastecimento(self):
        veiculo = VeiculoMaquina.objects.create(
            placa='MAQ01',
            descricao='Retroescavadeira',
            tipo='maquina',
        )

        response = self.client.post(
            reverse('novo_abastecimento'),
            {
                'data_abastecimento': '2026-04-23',
                'veiculo': veiculo.id,
                'posto': 'Posto Central',
                'responsavel': 'Joao',
                'litros': '50.00',
                'valor_litro': '6.50',
                'valor_total': '325.00',
                'observacoes': 'Abastecimento completo',
            },
        )

        self.assertRedirects(response, reverse('lista_abastecimentos'))
        registro = RegistroAbastecimento.objects.get()
        self.assertEqual(registro.valor_total, Decimal('325.00'))

    def test_abastecimentos_exigem_login(self):
        self.client.logout()

        response = self.client.get(reverse('lista_abastecimentos'))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('lista_abastecimentos')}")

    def test_cria_ordem_combustivel_para_veiculo_e_nf(self):
        veiculo = VeiculoMaquina.objects.create(
            placa='oc1234',
            descricao='Caminhao tanque',
            tipo='caminhao',
        )

        response = self.client.post(
            reverse('nova_ordem_combustivel'),
            {
                'numero': '',
                'data_ordem': '2026-04-29',
                'fornecedor': 'Posto Central',
                'solicitante': 'Operacao',
                'tipo_combustivel': 'diesel',
                'tipo_destino': 'veiculo',
                'veiculo': veiculo.id,
                'bombona': '',
                'quantidade_litros': '100.00',
                'valor_litro_previsto': '6.50',
                'valor_total_previsto': '',
                'status': 'solicitada',
                'observacoes': 'Compra inicial',
            },
        )

        ordem = OrdemCompraCombustivel.objects.get()
        self.assertRedirects(response, reverse('detalhe_ordem_combustivel', args=[ordem.id]))
        self.assertEqual(ordem.veiculo, veiculo)
        self.assertIsNone(ordem.bombona)
        self.assertEqual(ordem.valor_total_previsto, Decimal('650.0000'))
        self.assertTrue(ordem.numero.startswith('OC-COMB-2026-'))
        self.assertEqual(HistoricoOrdemCombustivel.objects.count(), 1)

        response = self.client.post(
            reverse('nova_nf_combustivel', args=[ordem.id]),
            {
                'numero': 'NF-001',
                'data_emissao': '2026-04-29',
                'litros': '80.00',
                'valor_litro': '6.60',
                'valor_total': '',
                'status': 'emitida',
                'observacoes': '',
            },
        )

        self.assertRedirects(response, reverse('detalhe_ordem_combustivel', args=[ordem.id]))
        nota = NotaFiscalCombustivel.objects.get()
        self.assertEqual(nota.valor_total, Decimal('528.0000'))
        self.assertEqual(ordem.total_litros_faturados, Decimal('80.00'))
        self.assertEqual(ordem.saldo_litros, Decimal('20.00'))
        self.assertEqual(HistoricoOrdemCombustivel.objects.count(), 2)

    def test_cria_ordem_combustivel_para_bombona(self):
        bombona = BombonaCombustivel.objects.create(
            identificacao='bmb-01',
            capacidade_litros=Decimal('200.00'),
            localizacao='Almoxarifado',
        )

        response = self.client.post(
            reverse('nova_ordem_combustivel'),
            {
                'numero': 'OC-BOMBONA-01',
                'data_ordem': '2026-04-29',
                'fornecedor': 'Distribuidora Diesel',
                'solicitante': 'Almoxarifado',
                'tipo_combustivel': 'diesel',
                'tipo_destino': 'bombona',
                'veiculo': '',
                'bombona': bombona.id,
                'quantidade_litros': '150.00',
                'valor_litro_previsto': '6.25',
                'valor_total_previsto': '937.50',
                'status': 'aprovada',
                'observacoes': '',
            },
        )

        ordem = OrdemCompraCombustivel.objects.get()
        self.assertRedirects(response, reverse('detalhe_ordem_combustivel', args=[ordem.id]))
        self.assertEqual(ordem.bombona, bombona)
        self.assertIsNone(ordem.veiculo)
        self.assertEqual(str(ordem.destino_display), 'BMB-01')

    def test_cria_ordem_locacao_maquina_com_apontamento_e_nf(self):
        obra = Obra.objects.create(nome_obra='Obra Maquinas')
        fornecedor = FornecedorMaquinaLocacao.objects.create(nome='Maquinas Pesadas Ltda')
        maquina = MaquinaLocacaoCatalogo.objects.create(nome='Retroescavadeira', categoria='Linha amarela')

        response = self.client.post(
            reverse('nova_ordem_locacao_maquina'),
            {
                'numero': '',
                'data_solicitacao': '2026-04-29',
                'obra': obra.id,
                'fornecedor': fornecedor.id,
                'maquina': maquina.id,
                'solicitante': 'Equipe obra',
                'responsavel': 'Mauricio',
                'status': 'solicitada',
                'tipo_cobranca': 'por_hora',
                'data_prevista_inicio': '2026-04-30',
                'data_prevista_fim': '',
                'data_mobilizacao': '',
                'data_inicio_operacao': '',
                'data_solicitacao_desmobilizacao': '',
                'data_desmobilizacao': '',
                'valor_hora': '250.00',
                'valor_diaria': '',
                'valor_mensal': '',
                'franquia_horas': '',
                'valor_mobilizacao': '500.00',
                'valor_desmobilizacao': '400.00',
                'valor_previsto_manual': '',
                'operador_incluso': 'on',
                'combustivel_incluso': '',
                'observacoes': 'Servico de escavacao',
            },
        )

        ordem = OrdemServicoLocacaoMaquina.objects.get()
        self.assertRedirects(response, reverse('detalhe_ordem_locacao_maquina', args=[ordem.id]))
        self.assertTrue(ordem.numero.startswith('OS-MAQ-2026-'))
        self.assertEqual(HistoricoLocacaoMaquina.objects.count(), 1)

        response = self.client.post(
            reverse('novo_apontamento_maquina', args=[ordem.id]),
            {
                'data': '2026-04-30',
                'horimetro_inicial': '100.00',
                'horimetro_final': '108.50',
                'horas_trabalhadas': '',
                'horas_paradas': '1.00',
                'motivo_parada': 'Chuva',
                'operador': 'Joao',
                'responsavel_apontamento': 'Mestre obra',
                'observacoes': '',
            },
        )

        self.assertRedirects(response, reverse('detalhe_ordem_locacao_maquina', args=[ordem.id]))
        apontamento = ApontamentoMaquinaLocacao.objects.get()
        self.assertEqual(apontamento.horas_trabalhadas, Decimal('8.50'))
        self.assertEqual(ordem.total_horas_apontadas, Decimal('8.50'))
        self.assertEqual(ordem.valor_previsto_total, Decimal('3025.0000'))

        response = self.client.post(
            reverse('nova_nf_locacao_maquina', args=[ordem.id]),
            {
                'numero': 'NF-MAQ-001',
                'data_emissao': '2026-05-02',
                'periodo_inicio': '2026-04-30',
                'periodo_fim': '2026-04-30',
                'horas_faturadas': '8.50',
                'valor_maquina': '2125.00',
                'valor_mobilizacao': '500.00',
                'valor_desmobilizacao': '400.00',
                'valor_total': '',
                'status': 'emitida',
                'observacoes': '',
            },
        )

        self.assertRedirects(response, reverse('detalhe_ordem_locacao_maquina', args=[ordem.id]))
        nota = NotaFiscalLocacaoMaquina.objects.get()
        self.assertEqual(nota.valor_total, Decimal('3025.0000'))
        self.assertEqual(ordem.total_horas_faturadas, Decimal('8.50'))
        self.assertEqual(ordem.saldo_horas, Decimal('0.00'))
        self.assertEqual(HistoricoLocacaoMaquina.objects.count(), 3)

    def test_cadastros_locacao_maquina_carregam(self):
        response = self.client.post(
            reverse('nova_maquina_locacao'),
            {
                'nome': 'Escavadeira hidraulica',
                'categoria': 'Linha amarela',
                'status': 'ativa',
                'observacoes': '',
            },
        )

        self.assertRedirects(response, reverse('lista_catalogo_maquinas_locacao'))
        self.assertEqual(MaquinaLocacaoCatalogo.objects.get().nome, 'Escavadeira hidraulica')

        response = self.client.post(
            reverse('novo_fornecedor_maquina'),
            {
                'nome': 'Fornecedor Linha Amarela',
                'contato': 'Carlos',
                'telefone': '11999990000',
                'email': 'contato@example.com',
                'observacoes': '',
            },
        )

        self.assertRedirects(response, reverse('lista_fornecedores_maquinas'))
        self.assertEqual(FornecedorMaquinaLocacao.objects.get().nome, 'Fornecedor Linha Amarela')

    def test_cria_locacao_equipamento(self):
        equipamento = EquipamentoLocadoCatalogo.objects.create(nome='Plataforma elevatoria')
        locadora = LocadoraEquipamento.objects.create(nome='Locadora Sul')
        obra = Obra.objects.create(nome_obra='Obra Teste')

        response = self.client.post(
            reverse('nova_locacao_equipamento'),
            {
                'data_locacao': '2026-04-23',
                'equipamento': equipamento.id,
                'locadora': locadora.id,
                'obra': obra.id,
                'solicitante': 'Maria',
                'status': 'locado',
                'numero_contrato': '97016-01',
                'quantidade': '2',
                'data_solicitacao_retirada': '',
                'data_retirada': '',
                'prazo': '30 dias',
                'valor_referencia': '1500.00',
                'observacoes': 'Locacao inicial',
            },
        )

        self.assertRedirects(response, reverse('lista_equipamentos_locados'))
        locacao = LocacaoEquipamento.objects.get()
        self.assertEqual(locacao.status, 'locado')
        self.assertEqual(locacao.numero_contrato, '97016-01')
        self.assertEqual(locacao.quantidade, 2)
        self.assertTrue(locacao.em_aberto)

    def test_lista_locacoes_destaca_resumo_por_obra(self):
        equipamento = EquipamentoLocadoCatalogo.objects.create(nome='Gerador')
        locadora = LocadoraEquipamento.objects.create(nome='Locadora Sul')
        obra = Obra.objects.create(nome_obra='Condominio Rithmo', cliente='Cliente X')
        LocacaoEquipamento.objects.create(
            equipamento=equipamento,
            locadora=locadora,
            obra=obra,
            data_locacao='2026-04-01',
            status='aguardando_entrega',
        )

        response = self.client.get(reverse('lista_equipamentos_locados'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Resumo por obra')
        self.assertContains(response, 'Condominio Rithmo')
        self.assertContains(response, 'Ag. entrega')

    def test_lista_locacoes_aplica_filtros(self):
        equipamento = EquipamentoLocadoCatalogo.objects.create(nome='Gerador')
        locadora_a = LocadoraEquipamento.objects.create(nome='Sulmak')
        locadora_b = LocadoraEquipamento.objects.create(nome='RM')
        obra_a = Obra.objects.create(nome_obra='Condominio Rithmo')
        obra_b = Obra.objects.create(nome_obra='Ipanema')
        LocacaoEquipamento.objects.create(
            equipamento=equipamento,
            locadora=locadora_a,
            obra=obra_a,
            data_locacao='2026-04-01',
            observacoes='Equipamento principal',
        )
        LocacaoEquipamento.objects.create(
            equipamento=equipamento,
            locadora=locadora_b,
            obra=obra_b,
            data_locacao='2026-04-02',
            status='retirado',
            observacoes='Outro equipamento',
        )

        response = self.client.get(
            reverse('lista_equipamentos_locados'),
            {'obra': obra_a.id, 'locadora': locadora_a.id, 'status': 'locado', 'busca': 'principal'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Condominio Rithmo')
        self.assertEqual(list(response.context['locacoes']), [LocacaoEquipamento.objects.get(obra=obra_a)])

    def test_relatorio_locacoes_pdf_responde_pdf(self):
        equipamento = EquipamentoLocadoCatalogo.objects.create(nome='Betoneira')
        locadora = LocadoraEquipamento.objects.create(nome='Sulmak')
        obra = Obra.objects.create(nome_obra='Condominio Rithmo')
        LocacaoEquipamento.objects.create(
            equipamento=equipamento,
            locadora=locadora,
            obra=obra,
            data_locacao='2026-04-01',
            observacoes='Locacao para relatorio',
        )

        response = self.client.get(reverse('relatorio_locacoes_equipamentos_pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_solicita_retirada_e_baixa_locacao(self):
        equipamento = EquipamentoLocadoCatalogo.objects.create(nome='Andaime')
        locadora = LocadoraEquipamento.objects.create(nome='Locadora Centro')
        obra = Obra.objects.create(nome_obra='Obra Retirada')
        locacao = LocacaoEquipamento.objects.create(
            equipamento=equipamento,
            locadora=locadora,
            obra=obra,
            data_locacao='2026-04-01',
            solicitante='Carlos',
            valor_referencia=Decimal('500.00'),
        )

        response = self.client.post(
            reverse('solicitar_retirada_equipamento', args=[locacao.id]),
            {
                'data_solicitacao_retirada': '2026-04-20',
                'observacoes': 'Retirar da obra',
            },
        )

        self.assertRedirects(response, reverse('lista_equipamentos_locados'))
        locacao.refresh_from_db()
        self.assertEqual(locacao.status, 'retirada_solicitada')

        response = self.client.post(
            reverse('baixar_locacao_equipamento', args=[locacao.id]),
            {
                'data_retirada': '2026-04-23',
                'observacoes': 'Retirado pela locadora',
            },
        )

        self.assertRedirects(response, reverse('lista_equipamentos_locados'))
        locacao.refresh_from_db()
        self.assertEqual(locacao.status, 'retirado')
        self.assertFalse(locacao.em_aberto)

    def test_editar_locacao_mantem_datas_no_formulario(self):
        equipamento = EquipamentoLocadoCatalogo.objects.create(nome='Betoneira')
        locadora = LocadoraEquipamento.objects.create(nome='Locadora Centro')
        obra = Obra.objects.create(nome_obra='Obra Datas')
        locacao = LocacaoEquipamento.objects.create(
            equipamento=equipamento,
            locadora=locadora,
            obra=obra,
            data_locacao='2026-04-01',
            data_solicitacao_retirada='2026-04-10',
            data_retirada='2026-04-15',
        )

        response = self.client.get(reverse('editar_locacao_equipamento', args=[locacao.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="2026-04-01"', html=False)
        self.assertContains(response, 'value="2026-04-10"', html=False)
        self.assertContains(response, 'value="2026-04-15"', html=False)

    def test_cria_orcamento_no_radar(self):
        response = self.client.post(
            reverse('novo_radar_obra'),
            {
                'numero': 'ORC-001',
                'cliente': 'Cliente Radar',
                'descricao': 'Execucao de obra teste',
                'data_orcamento': '2026-04-23',
                'situacao': 'aguardando_resposta',
                'valor_estimado': '10000.00',
                'responsavel': 'Diretoria',
                'observacoes': 'Aguardando retorno',
            },
        )

        self.assertRedirects(response, reverse('lista_radar_obras'))
        orcamento = OrcamentoRadarObra.objects.get()
        self.assertEqual(orcamento.numero, 'ORC-001')
        self.assertEqual(orcamento.situacao, 'aguardando_resposta')

    def test_lista_radar_exibe_contadores(self):
        OrcamentoRadarObra.objects.create(
            numero='ORC-002',
            cliente='Cliente Fechado',
            descricao='Obra aprovada',
            data_orcamento='2026-04-23',
            situacao='fechada',
            valor_estimado=Decimal('20000.00'),
        )

        response = self.client.get(reverse('lista_radar_obras'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Radar de Obras')
        self.assertContains(response, 'Cliente Fechado')

    def test_cria_contrato_e_faturamento_concretagem(self):
        obra = Obra.objects.create(nome_obra='Obra Concreto')
        contrato = ContratoConcretagem.objects.create(
            obra=obra,
            fornecedor='Concreteira Teste',
            descricao='Contrato concreto usinado',
            data_inicio='2026-04-23',
            custo_m3_concreto=Decimal('500.00'),
            custo_bomba=Decimal('800.00'),
            adicional_noturno=Decimal('300.00'),
            adicional_sabado=Decimal('200.00'),
            adicional_m3_faltante=Decimal('50.00'),
            volume_minimo_m3=Decimal('8.00'),
        )
        solicitante = SolicitanteConcretagem.objects.create(nome='Equipe obra')

        response = self.client.post(
            reverse('novo_faturamento_concretagem', args=[contrato.id]),
            {
                'data_faturamento': '2026-04-24',
                'solicitante': solicitante.id,
                'status': 'conferida',
                'numero_documento': 'NF-CONC-001',
                'data_conferencia': '2026-04-25',
                'volume_m3': '10.00',
                'fck_traco': '30_mpa',
                'tipo_bomba': 'bomba_lanca',
                'usou_bomba': 'on',
                'adicional_noturno_aplicado': '',
                'adicional_sabado_aplicado': 'on',
                'volume_faltante_m3': '2.00',
                'valor_previsto_manual': '',
                'valor_cobrado': '6100.00',
                'observacoes': 'Primeiro faturamento',
            },
        )

        self.assertRedirects(response, reverse('detalhe_contrato_concretagem', args=[contrato.id]))
        faturamento = FaturamentoConcretagem.objects.get()
        self.assertEqual(faturamento.valor_previsto, Decimal('6100.0000'))
        self.assertEqual(faturamento.diferenca, Decimal('0.0000'))

    def test_lista_concretagens_carrega(self):
        obra = Obra.objects.create(nome_obra='Obra Lista Concreto')
        ContratoConcretagem.objects.create(
            obra=obra,
            fornecedor='Fornecedor Concreto',
            descricao='Contrato lista',
            data_inicio='2026-04-23',
        )

        response = self.client.get(reverse('lista_concretagens'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Controle de Concretagens')
        self.assertContains(response, 'Fornecedor Concreto')

    def test_importa_planilha_de_locacoes_por_obra(self):
        Obra.objects.create(nome_obra='Condominio Rithmo')

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = 'RITHMO (guris interno)'
        worksheet.append(['Endereco'])
        worksheet.append([])
        worksheet.append(
            ['DATA ALUGUEL', 'LOCADORA', 'QUEM LOCOU', 'SITUAÇÃO', 'EQUIPAMENTO', 'OS', 'CONTRATO', 'QNTD', 'DATA DEVOLUÇÃO', 'OBSERVAÇÃO', 'PRAZO', 'VALOR MENSAL']
        )
        worksheet.append([])
        worksheet.append(['2026-01-29', 'SULMAK', 'VINICIUS', 'NA OBRA', 'BETONEIRA 250L', '-', '2931-01', 1, '2026-02-04', 'teste', '1 SEMANA', '400'])
        worksheet.append(['2026-04-24', 'SULMAK', 'MAURICIO', 'AG ENTREGA', 'BOMBA MANGOTE 3"', None, None, 1, None, None, None, None])

        with NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            workbook.save(temp_path)
            call_command('importar_locacoes_equipamentos', temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        self.assertEqual(LocacaoEquipamento.objects.count(), 2)
        locacao = LocacaoEquipamento.objects.get(equipamento__nome='BETONEIRA 250L')
        self.assertEqual(locacao.obra.nome_obra, 'Condominio Rithmo')
        self.assertEqual(locacao.locadora.nome, 'SULMAK')
        self.assertEqual(locacao.valor_referencia, Decimal('400.00'))
        self.assertEqual(locacao.data_retirada.isoformat(), '2026-02-04')

        entrega = LocacaoEquipamento.objects.get(equipamento__nome='BOMBA MANGOTE 3"')
        self.assertEqual(entrega.status, 'aguardando_entrega')
