from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
import tempfile

from controles.models import CronogramaObra, OrcamentoRadarObra, OrdemCompraGeral
from diarios.models import DiarioObra, FotoDiario
from financeiro.models import CentroCusto, ContaPagar, ContaReceber, Fornecedor, PrevisaoFinanceira
from medicoes.models import Empreiteiro
from obras.models import Obra
from propostas.models import Proposta
from .middleware import EmpresaAtivaMiddleware
from .models import Empresa, UsuarioEmpresa
from .services import (
    definir_empresa_na_sessao,
    empresa_ativa_do_request,
    obter_ou_criar_empresa_padrao,
    usuario_tem_acesso_empresa,
    vincular_usuarios_existentes_a_empresa_padrao,
)


User = get_user_model()


class EmpresaTests(TestCase):
    def test_cria_empresa_ativa_por_padrao(self):
        empresa = Empresa.objects.create(nome='Cassoni Engenharia', slug='cassoni')

        self.assertEqual(empresa.nome, 'Cassoni Engenharia')
        self.assertTrue(empresa.ativa)

    def test_slug_de_empresa_e_unico(self):
        Empresa.objects.get_or_create(slug='ambar', defaults={'nome': 'Ambar'})

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Empresa.objects.create(nome='Outra Ambar', slug='ambar')


class UsuarioEmpresaTests(TestCase):
    def setUp(self):
        self.ambar, _created = Empresa.objects.get_or_create(slug='ambar', defaults={'nome': 'Ambar Engenharia'})
        self.cassoni = Empresa.objects.create(nome='Cassoni Engenharia', slug='cassoni')
        self.mauricio = User.objects.create_user(username='mauricio', password='senha')
        self.joao = User.objects.create_user(username='joao', password='senha')

    def test_vincula_usuario_a_empresa(self):
        vinculo = UsuarioEmpresa.objects.create(usuario=self.mauricio, empresa=self.ambar)

        self.assertTrue(vinculo.ativo)
        self.assertFalse(vinculo.administrador_empresa)

    def test_nao_permite_vinculo_duplicado(self):
        UsuarioEmpresa.objects.create(usuario=self.mauricio, empresa=self.ambar)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UsuarioEmpresa.objects.create(usuario=self.mauricio, empresa=self.ambar)

    def test_usuario_pode_pertencer_a_duas_empresas(self):
        UsuarioEmpresa.objects.create(usuario=self.mauricio, empresa=self.ambar)
        UsuarioEmpresa.objects.create(usuario=self.mauricio, empresa=self.cassoni)

        self.assertEqual(UsuarioEmpresa.objects.filter(usuario=self.mauricio).count(), 2)

    def test_duas_pessoas_podem_pertencer_a_mesma_empresa(self):
        UsuarioEmpresa.objects.create(usuario=self.mauricio, empresa=self.cassoni)
        UsuarioEmpresa.objects.create(usuario=self.joao, empresa=self.cassoni)

        self.assertEqual(UsuarioEmpresa.objects.filter(empresa=self.cassoni).count(), 2)


class EmpresaAtivaRequestTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.ambar = obter_ou_criar_empresa_padrao()
        self.teste = Empresa.objects.create(nome='Empresa Teste', slug='empresa-teste')
        self.user = User.objects.create_user(username='usuario-empresa', password='senha')

    def _request(self):
        request = self.factory.get('/')
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = self.user
        return request

    def test_usuario_com_uma_empresa_ativa_seleciona_automaticamente(self):
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.ambar)
        request = self._request()

        EmpresaAtivaMiddleware(lambda req: req)(request)

        self.assertEqual(request.empresa, self.ambar)
        self.assertEqual(request.session['empresa_id'], self.ambar.id)

    def test_usuario_com_duas_empresas_respeita_sessao_valida(self):
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.ambar)
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.teste)
        request = self._request()
        request.session['empresa_id'] = self.teste.id

        EmpresaAtivaMiddleware(lambda req: req)(request)

        self.assertEqual(request.empresa, self.teste)

    def test_sessao_adulterada_nao_ativa_empresa_sem_permissao(self):
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.ambar)
        request = self._request()
        request.session['empresa_id'] = self.teste.id

        EmpresaAtivaMiddleware(lambda req: req)(request)

        self.assertEqual(request.empresa, self.ambar)
        self.assertEqual(request.session['empresa_id'], self.ambar.id)
        self.assertFalse(usuario_tem_acesso_empresa(self.user, self.teste))

    def test_usuario_com_duas_empresas_sem_sessao_nao_escolhe_primeira(self):
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.ambar)
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.teste)
        request = self._request()

        self.assertIsNone(empresa_ativa_do_request(request))

    def test_vinculo_inativo_nao_concede_acesso(self):
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.ambar, ativo=False)
        request = self._request()

        EmpresaAtivaMiddleware(lambda req: req)(request)

        self.assertIsNone(request.empresa)

    def test_empresa_inativa_nao_pode_ser_ativada(self):
        self.ambar.ativa = False
        self.ambar.save(update_fields=['ativa'])
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.ambar)
        request = self._request()

        EmpresaAtivaMiddleware(lambda req: req)(request)

        self.assertIsNone(request.empresa)

    def test_definir_empresa_na_sessao_valida_acesso(self):
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.ambar)
        request = self._request()

        self.assertEqual(definir_empresa_na_sessao(request, self.ambar), self.ambar)
        self.assertIsNone(definir_empresa_na_sessao(request, self.teste))


class EmpresaPadraoTests(TestCase):
    def test_obter_ou_criar_empresa_padrao_e_idempotente(self):
        primeira = obter_ou_criar_empresa_padrao()
        segunda = obter_ou_criar_empresa_padrao()

        self.assertEqual(primeira.id, segunda.id)
        self.assertEqual(Empresa.objects.filter(slug='ambar').count(), 1)

    def test_vincula_usuarios_existentes_sem_duplicidade(self):
        comum = User.objects.create_user(username='usuario')
        admin = User.objects.create_superuser(username='admin', password='senha')

        vincular_usuarios_existentes_a_empresa_padrao()
        vincular_usuarios_existentes_a_empresa_padrao()

        ambar = Empresa.objects.get(slug='ambar')
        self.assertEqual(UsuarioEmpresa.objects.filter(empresa=ambar).count(), 2)
        self.assertTrue(UsuarioEmpresa.objects.get(usuario=admin, empresa=ambar).administrador_empresa)
        self.assertFalse(UsuarioEmpresa.objects.get(usuario=comum, empresa=ambar).administrador_empresa)


class PropriedadeDadosFase2Tests(TestCase):
    def setUp(self):
        self.ambar = obter_ou_criar_empresa_padrao()
        self.cassoni = Empresa.objects.create(nome='Cassoni Engenharia', slug='cassoni')

    def test_nova_obra_exige_empresa_explicita(self):
        with self.assertRaises(ValidationError):
            Obra.objects.create(nome_obra='Obra Fase 2')

        obra = Obra.objects.create(nome_obra='Obra Fase 2', empresa=self.ambar)
        self.assertEqual(obra.empresa, self.ambar)

    def test_cadastros_operacionais_convertidos_exigem_empresa_explicita(self):
        with self.assertRaises(ValidationError):
            Empreiteiro.objects.create(nome='Empreiteiro Fase 2')

        empreiteiro = Empreiteiro.objects.create(empresa=self.ambar, nome='Empreiteiro Fase 2')

        self.assertEqual(empreiteiro.empresa, self.ambar)

    def test_cadastros_financeiros_exigem_empresa_explicita(self):
        with self.assertRaises(ValidationError):
            Fornecedor.objects.create(nome='Fornecedor Fase 2', cpf_cnpj='00')
        with self.assertRaises(ValidationError):
            CentroCusto.objects.create(nome='Centro Fase 2')

    def test_cadastros_permitidos_em_empresas_diferentes(self):
        Fornecedor.objects.create(empresa=self.ambar, nome='Fornecedor Compartilhado', cpf_cnpj='11')
        Fornecedor.objects.create(empresa=self.cassoni, nome='Fornecedor Compartilhado', cpf_cnpj='11')
        CentroCusto.objects.create(empresa=self.ambar, nome='Administrativo')
        CentroCusto.objects.create(empresa=self.cassoni, nome='Administrativo')
        Empreiteiro.objects.create(empresa=self.ambar, nome='Equipe Compartilhada')
        Empreiteiro.objects.create(empresa=self.cassoni, nome='Equipe Compartilhada')

        self.assertEqual(Fornecedor.objects.filter(nome='Fornecedor Compartilhado').count(), 2)
        self.assertEqual(CentroCusto.objects.filter(nome='Administrativo').count(), 2)
        self.assertEqual(Empreiteiro.objects.filter(nome='Equipe Compartilhada').count(), 2)

    def test_financeiro_sem_obra_usa_empresa_explicita(self):
        centro = CentroCusto.objects.create(empresa=self.ambar, nome='Escritorio Fase 2')
        conta_pagar = ContaPagar.objects.create(
            empresa=self.ambar,
            fornecedor='Fornecedor sem obra',
            centro_custo=centro,
            descricao='Conta administrativa',
            data_emissao=timezone.localdate(),
            data_vencimento=timezone.localdate(),
            valor='100.00',
        )
        conta_receber = ContaReceber.objects.create(
            empresa=self.ambar,
            cliente='Cliente sem obra',
            descricao='Receita administrativa',
            data_emissao=timezone.localdate(),
            data_vencimento=timezone.localdate(),
            valor_bruto='200.00',
        )
        previsao = PrevisaoFinanceira.objects.create(
            empresa=self.ambar,
            tipo=PrevisaoFinanceira.TIPO_PAGAR,
            descricao='Previsao administrativa',
            data_prevista=timezone.localdate(),
            valor='300.00',
        )

        self.assertEqual(conta_pagar.empresa, self.ambar)
        self.assertEqual(conta_receber.empresa, self.ambar)
        self.assertEqual(previsao.empresa, self.ambar)

    def test_registros_com_obra_derivam_empresa_da_obra(self):
        obra = Obra.objects.create(nome_obra='Obra Cassoni', empresa=self.cassoni)
        conta_pagar = ContaPagar.objects.create(
            fornecedor='Fornecedor obra',
            obra=obra,
            descricao='Despesa obra',
            data_emissao=timezone.localdate(),
            data_vencimento=timezone.localdate(),
            valor='100.00',
        )
        conta_receber = ContaReceber.objects.create(
            cliente='Cliente obra',
            obra=obra,
            numero_nf='1',
            descricao='Receita obra',
            data_emissao=timezone.localdate(),
            data_vencimento=timezone.localdate(),
            valor_bruto='200.00',
        )
        ordem = OrdemCompraGeral.objects.create(fornecedor='Fornecedor OC', obra=obra)
        previsao = PrevisaoFinanceira.objects.create(
            tipo=PrevisaoFinanceira.TIPO_RECEBER,
            obra=obra,
            descricao='Previsao obra',
            data_prevista=timezone.localdate(),
            valor='300.00',
        )
        cronograma = CronogramaObra.objects.create(
            nome='Cronograma obra',
            obra=obra,
            data_inicio=timezone.localdate(),
            data_fim=timezone.localdate(),
        )

        self.assertEqual(conta_pagar.empresa, self.cassoni)
        self.assertEqual(conta_receber.empresa, self.cassoni)
        self.assertEqual(ordem.empresa, self.cassoni)
        self.assertEqual(previsao.empresa, self.cassoni)
        self.assertEqual(cronograma.empresa, self.cassoni)

    def test_radar_cronograma_e_proposta_exigem_empresa_explicita(self):
        with self.assertRaises(ValidationError):
            OrcamentoRadarObra.objects.create(
                numero='RAD-F2',
                cliente='Cliente Radar',
                descricao='Oportunidade',
                data_orcamento=timezone.localdate(),
            )
        with self.assertRaises(ValidationError):
            CronogramaObra.objects.create(
                nome='Cronograma sem obra',
                data_inicio=timezone.localdate(),
                data_fim=timezone.localdate(),
            )
        with self.assertRaises(ValidationError):
            Proposta.objects.create(
                cliente='Cliente Proposta',
                tipo_execucao='Servico',
                servico_incluso='Servico incluso',
            )

        radar = OrcamentoRadarObra.objects.create(
            empresa=self.ambar,
            numero='RAD-F2',
            cliente='Cliente Radar',
            descricao='Oportunidade',
            data_orcamento=timezone.localdate(),
        )
        cronograma = CronogramaObra.objects.create(
            empresa=self.ambar,
            nome='Cronograma sem obra',
            data_inicio=timezone.localdate(),
            data_fim=timezone.localdate(),
        )
        proposta = Proposta.objects.create(
            empresa=self.ambar,
            cliente='Cliente Proposta',
            tipo_execucao='Servico',
            servico_incluso='Servico incluso',
        )
        proposta.sincronizar_radar()

        self.assertEqual(radar.empresa, self.ambar)
        self.assertEqual(cronograma.empresa, self.ambar)
        self.assertEqual(proposta.empresa, self.ambar)
        self.assertEqual(proposta.radar.empresa, self.ambar)

    def test_usuario_de_outra_empresa_nao_acessa_operacional_por_id(self):
        usuario = User.objects.create_user(username='cassoni-user', password='senha')
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.cassoni)
        self.client.force_login(usuario)
        radar = OrcamentoRadarObra.objects.create(
            empresa=self.ambar,
            numero='RAD-AMBAR',
            cliente='Cliente Ambar',
            descricao='Oportunidade Ambar',
            data_orcamento=timezone.localdate(),
        )

        response = self.client.get(reverse('editar_radar_obra', args=[radar.id]))

        self.assertEqual(response.status_code, 404)

    def test_atualizacao_em_lote_nao_altera_radar_de_outra_empresa(self):
        usuario = User.objects.create_user(username='cassoni-lote', password='senha')
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.cassoni)
        radar_ambar = OrcamentoRadarObra.objects.create(
            empresa=self.ambar,
            numero='RAD-AMBAR-LOTE',
            cliente='Cliente Ambar',
            descricao='Oportunidade Ambar',
            data_orcamento=timezone.localdate(),
            situacao='aguardando_resposta',
        )
        radar_cassoni = OrcamentoRadarObra.objects.create(
            empresa=self.cassoni,
            numero='RAD-CASSONI-LOTE',
            cliente='Cliente Cassoni',
            descricao='Oportunidade Cassoni',
            data_orcamento=timezone.localdate(),
            situacao='aguardando_resposta',
        )
        self.client.force_login(usuario)

        self.client.post(
            reverse('atualizar_radar_obras_em_lote'),
            {
                'orcamento_id': [str(radar_ambar.id), str(radar_cassoni.id)],
                f'situacao_{radar_ambar.id}': 'fechada',
                f'temperatura_{radar_ambar.id}': '5',
                f'situacao_{radar_cassoni.id}': 'fechada',
                f'temperatura_{radar_cassoni.id}': '5',
            },
        )

        radar_ambar.refresh_from_db()
        radar_cassoni.refresh_from_db()
        self.assertEqual(radar_ambar.situacao, 'aguardando_resposta')
        self.assertEqual(radar_cassoni.situacao, 'fechada')

    def test_numeracoes_operacionais_podem_repetir_entre_empresas(self):
        obra_ambar = Obra.objects.create(empresa=self.ambar, nome_obra='Obra Numeracao Ambar')
        obra_cassoni = Obra.objects.create(empresa=self.cassoni, nome_obra='Obra Numeracao Cassoni')

        OrdemCompraGeral.objects.create(empresa=self.ambar, obra=obra_ambar, numero='001/2026', fornecedor='Fornecedor A')
        OrdemCompraGeral.objects.create(empresa=self.cassoni, obra=obra_cassoni, numero='001/2026', fornecedor='Fornecedor B')
        OrcamentoRadarObra.objects.create(
            empresa=self.ambar,
            numero='RAD-001',
            cliente='Cliente A',
            descricao='Radar A',
            data_orcamento=timezone.localdate(),
        )
        OrcamentoRadarObra.objects.create(
            empresa=self.cassoni,
            numero='RAD-001',
            cliente='Cliente B',
            descricao='Radar B',
            data_orcamento=timezone.localdate(),
        )
        proposta_ambar = Proposta.objects.create(
            empresa=self.ambar,
            cliente='Cliente A',
            tipo_execucao='Servico',
            servico_incluso='Servico incluso',
            data_proposta=timezone.localdate(),
        )
        proposta_cassoni = Proposta.objects.create(
            empresa=self.cassoni,
            cliente='Cliente B',
            tipo_execucao='Servico',
            servico_incluso='Servico incluso',
            data_proposta=timezone.localdate(),
        )

        self.assertEqual(OrdemCompraGeral.objects.filter(numero='001/2026').count(), 2)
        self.assertEqual(OrcamentoRadarObra.objects.filter(numero='RAD-001').count(), 2)
        self.assertEqual(proposta_ambar.numero_sequencial, proposta_cassoni.numero_sequencial)


class MidiaMultiempresaTests(TestCase):
    def setUp(self):
        self.ambar = obter_ou_criar_empresa_padrao()
        self.cassoni = Empresa.objects.create(nome='Cassoni Engenharia', slug='cassoni')
        self.usuario_ambar = User.objects.create_user(username='usuario-ambar', password='senha')
        self.usuario_cassoni = User.objects.create_user(username='usuario-cassoni', password='senha')
        UsuarioEmpresa.objects.create(usuario=self.usuario_ambar, empresa=self.ambar)
        UsuarioEmpresa.objects.create(usuario=self.usuario_cassoni, empresa=self.cassoni)
        self.obra_ambar = Obra.objects.create(empresa=self.ambar, nome_obra='Obra com foto Ambar')
        self.diario_ambar = DiarioObra.objects.create(
            obra=self.obra_ambar,
            data=timezone.localdate(),
            responsavel_preenchimento='Engenheiro',
            condicao_climatica=DiarioObra.CLIMA_ENSOLARADO,
            situacao_obra=DiarioObra.SITUACAO_ANDAMENTO,
            descricao_servicos='Registro de teste.',
        )

    def test_midia_de_diario_nao_vaza_para_outra_empresa(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            foto = FotoDiario.objects.create(
                diario=self.diario_ambar,
                imagem=SimpleUploadedFile('foto.jpg', b'conteudo-foto', content_type='image/jpeg'),
            )
            url = reverse('protected_media', kwargs={'path': foto.imagem.name})

            self.client.force_login(self.usuario_cassoni)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

            self.client.force_login(self.usuario_ambar)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            response.close()


class IsolamentoListagensMultiempresaTests(TestCase):
    def setUp(self):
        self.ambar = obter_ou_criar_empresa_padrao()
        self.cassoni = Empresa.objects.create(nome='Cassoni Engenharia', slug='cassoni')
        self.usuario = User.objects.create_user(username='usuario-cassoni-listas', password='senha')
        for grupo in ['Financeiro', 'Engenharia']:
            self.usuario.groups.add(Group.objects.get_or_create(name=grupo)[0])
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.cassoni)
        self.client.force_login(self.usuario)

    def test_empresa_sem_dados_abre_listagens_principais_sem_fallback_ambar(self):
        for url_name in [
            'lista_obras',
            'financeiro_home',
            'lista_contas_pagar',
            'lista_contas_receber',
            'lista_propostas',
            'lista_diarios',
            'lista_radar_obras',
        ]:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)

    def test_listagens_nao_exibem_sentinetas_de_outra_empresa(self):
        Obra.objects.create(empresa=self.ambar, nome_obra='SENTINELA-AMBAR-OBRA')
        Fornecedor.objects.create(empresa=self.ambar, nome='SENTINELA-AMBAR-FORNECEDOR', cpf_cnpj='11')
        ContaPagar.objects.create(
            empresa=self.ambar,
            fornecedor='SENTINELA-AMBAR-FORNECEDOR',
            descricao='SENTINELA-AMBAR-CONTA',
            data_emissao=timezone.localdate(),
            data_vencimento=timezone.localdate(),
            valor='123.45',
        )
        Proposta.objects.create(
            empresa=self.ambar,
            cliente='SENTINELA-AMBAR-PROPOSTA',
            tipo_execucao='Servico',
            servico_incluso='Servico incluso',
        )
        OrcamentoRadarObra.objects.create(
            empresa=self.ambar,
            numero='SENTINELA-AMBAR-RADAR',
            cliente='SENTINELA-AMBAR-RADAR',
            descricao='Radar de outra empresa',
            data_orcamento=timezone.localdate(),
        )

        for url_name in ['lista_obras', 'lista_contas_pagar', 'lista_fornecedores', 'lista_propostas', 'lista_radar_obras']:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'SENTINELA-AMBAR')


class Fase4TenantVisualTests(TestCase):
    def setUp(self):
        self.ambar = obter_ou_criar_empresa_padrao()
        self.cassoni = Empresa.objects.create(nome='Cassoni Engenharia', slug='cassoni')

    def _usuario(self, username, empresas):
        usuario = User.objects.create_user(username=username, password='senha-forte-123')
        for empresa, ativo in empresas:
            UsuarioEmpresa.objects.create(usuario=usuario, empresa=empresa, ativo=ativo)
        return usuario

    def test_command_criar_empresa_e_idempotente(self):
        call_command('criar_empresa', nome='Cassoni Engenharia', slug='cassoni')
        call_command('criar_empresa', nome='Cassoni Engenharia', slug='cassoni')

        self.assertEqual(Empresa.objects.filter(slug='cassoni').count(), 1)
        self.assertEqual(Empresa.objects.get(slug='cassoni').nome, 'Cassoni Engenharia')

    def test_command_vincular_usuario_empresa_e_idempotente(self):
        usuario = User.objects.create_user(username='mauricio-fase4', password='senha')

        call_command('vincular_usuario_empresa', usuario='mauricio-fase4', empresa='cassoni', administrador=True)
        call_command('vincular_usuario_empresa', usuario='mauricio-fase4', empresa='cassoni', administrador=True)

        vinculos = UsuarioEmpresa.objects.filter(usuario=usuario, empresa=self.cassoni)
        self.assertEqual(vinculos.count(), 1)
        self.assertTrue(vinculos.get().administrador_empresa)

    def test_command_vincular_rejeita_usuario_ou_empresa_inexistente(self):
        User.objects.create_user(username='usuario', password='senha')
        with self.assertRaises(CommandError):
            call_command('vincular_usuario_empresa', usuario='nao-existe', empresa='cassoni')
        with self.assertRaises(CommandError):
            call_command('vincular_usuario_empresa', usuario='usuario', empresa='nao-existe')

    def test_usuario_somente_ambar_entra_sem_seletor(self):
        usuario = self._usuario('somente-ambar', [(self.ambar, True)])
        self.client.force_login(usuario)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['empresa_id'], self.ambar.id)
        self.assertContains(response, self.ambar.nome)
        self.assertNotContains(response, 'Escolher empresa')
        self.assertNotContains(response, 'Cassoni Engenharia')

    def test_usuario_somente_cassoni_entra_sem_seletor_e_sem_dados_ambar(self):
        Obra.objects.create(empresa=self.ambar, nome_obra='SENTINELA-AMBAR-OBRA')
        usuario = self._usuario('somente-cassoni', [(self.cassoni, True)])
        self.client.force_login(usuario)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['empresa_id'], self.cassoni.id)
        self.assertContains(response, 'Cassoni Engenharia')
        self.assertNotContains(response, 'Escolher empresa')
        self.assertNotContains(response, 'SENTINELA-AMBAR-OBRA')

    def test_usuario_multiempresa_sem_sessao_escolhe_empresa(self):
        usuario = self._usuario('mauricio-fase4-ui', [(self.ambar, True), (self.cassoni, True)])
        self.client.force_login(usuario)

        response = self.client.get(reverse('home'))

        self.assertRedirects(response, reverse('selecionar_empresa'))
        response = self.client.get(reverse('selecionar_empresa'))
        self.assertContains(response, self.ambar.nome)
        self.assertContains(response, 'Cassoni Engenharia')

    def test_usuario_multiempresa_troca_por_post_e_dados_ficam_isolados(self):
        usuario = self._usuario('multi-troca', [(self.ambar, True), (self.cassoni, True)])
        Obra.objects.create(empresa=self.ambar, nome_obra='SENTINELA-AMBAR-OBRA')
        Obra.objects.create(empresa=self.cassoni, nome_obra='SENTINELA-CASSONI-OBRA')
        self.client.force_login(usuario)
        session = self.client.session
        session['empresa_id'] = self.ambar.id
        session.save()

        response = self.client.get(reverse('home'))
        self.assertContains(response, self.ambar.nome)
        self.assertContains(response, 'SENTINELA-AMBAR-OBRA')
        self.assertNotContains(response, 'SENTINELA-CASSONI-OBRA')

        response = self.client.post(reverse('trocar_empresa', args=[self.cassoni.id]))
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(self.client.session['empresa_id'], self.cassoni.id)
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Cassoni Engenharia')
        self.assertContains(response, 'SENTINELA-CASSONI-OBRA')
        self.assertNotContains(response, 'SENTINELA-AMBAR-OBRA')

        self.client.post(reverse('trocar_empresa', args=[self.ambar.id]))
        self.assertEqual(self.client.session['empresa_id'], self.ambar.id)

    def test_post_empresa_nao_autorizada_nao_altera_sessao(self):
        usuario = self._usuario('sem-cassoni', [(self.ambar, True)])
        self.client.force_login(usuario)
        self.client.get(reverse('home'))

        response = self.client.post(reverse('trocar_empresa', args=[self.cassoni.id]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.session['empresa_id'], self.ambar.id)

    def test_empresa_inativa_e_vinculo_inativo_nao_aparecem_nem_selecionam(self):
        empresa_inativa = Empresa.objects.create(nome='Empresa Inativa', slug='empresa-inativa', ativa=False)
        empresa_valida = Empresa.objects.create(nome='Empresa Valida', slug='empresa-valida', ativa=True)
        usuario = self._usuario(
            'multi-inativos',
            [(self.ambar, True), (empresa_valida, True), (self.cassoni, False), (empresa_inativa, True)],
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse('selecionar_empresa'))
        self.assertContains(response, self.ambar.nome)
        self.assertContains(response, 'Empresa Valida')
        self.assertNotContains(response, 'Cassoni Engenharia')
        self.assertNotContains(response, 'Empresa Inativa')
        self.assertEqual(self.client.post(reverse('trocar_empresa', args=[self.cassoni.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('trocar_empresa', args=[empresa_inativa.id])).status_code, 404)

    def test_troca_de_empresa_redireciona_para_dashboard(self):
        usuario = self._usuario('multi-contexto', [(self.ambar, True), (self.cassoni, True)])
        obra = Obra.objects.create(empresa=self.ambar, nome_obra='Obra Contexto')
        self.client.force_login(usuario)
        session = self.client.session
        session['empresa_id'] = self.ambar.id
        session.save()

        self.client.get(reverse('detalhe_obra', args=[obra.id]))
        response = self.client.post(reverse('trocar_empresa', args=[self.cassoni.id]))

        self.assertRedirects(response, reverse('home'))

    def test_troca_de_empresa_exige_csrf(self):
        usuario = self._usuario('multi-csrf', [(self.ambar, True), (self.cassoni, True)])
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(usuario)

        response = csrf_client.post(reverse('trocar_empresa', args=[self.cassoni.id]))

        self.assertEqual(response.status_code, 403)

    def test_logo_da_empresa_aparece_na_navbar_quando_existir(self):
        self.cassoni.logo = 'empresas/cassoni/branding/logo.png'
        self.cassoni.save(update_fields=['logo'])
        usuario = self._usuario('cassoni-logo', [(self.cassoni, True)])
        self.client.force_login(usuario)

        response = self.client.get(reverse('home'))

        self.assertContains(response, 'empresa-logo')
        self.assertContains(response, 'empresas/cassoni/branding/logo.png')


class Fase5IdentidadeVisualTests(TestCase):
    def setUp(self):
        self.ambar = obter_ou_criar_empresa_padrao()
        self.cassoni = Empresa.objects.create(nome='Cassoni Engenharia', slug='cassoni')
        self.admin = User.objects.create_user(username='admin-identidade', password='senha')
        self.comum = User.objects.create_user(username='comum-identidade', password='senha')
        UsuarioEmpresa.objects.create(usuario=self.admin, empresa=self.ambar, administrador_empresa=True)
        UsuarioEmpresa.objects.create(usuario=self.admin, empresa=self.cassoni, administrador_empresa=True)
        UsuarioEmpresa.objects.create(usuario=self.comum, empresa=self.ambar, administrador_empresa=False)

    def _selecionar(self, empresa):
        session = self.client.session
        session['empresa_id'] = empresa.id
        session.save()

    def test_admin_da_empresa_edita_identidade_da_empresa_ativa(self):
        self.client.force_login(self.admin)
        self._selecionar(self.cassoni)

        response = self.client.post(
            reverse('identidade_visual_empresa'),
            {
                'razao_social': 'Cassoni Engenharia Ltda',
                'nome_fantasia': 'Cassoni Engenharia',
                'cnpj': '00.000.000/0001-00',
                'endereco': 'Rua Cassoni',
                'cidade': 'Novo Hamburgo',
                'estado': 'RS',
                'cep': '',
                'telefone': '',
                'email': '',
                'texto_rodape': 'RODAPE-CASSONI',
                'cor_primaria': '#123456',
                'cor_secundaria': '#abcdef',
                'responsavel_tecnico': 'Eng. Cassoni',
                'crea_responsavel': 'CREA TESTE',
            },
        )

        self.assertRedirects(response, reverse('identidade_visual_empresa'))
        self.cassoni.refresh_from_db()
        self.ambar.refresh_from_db()
        self.assertEqual(self.cassoni.texto_rodape, 'RODAPE-CASSONI')
        self.assertNotEqual(self.ambar.texto_rodape, 'RODAPE-CASSONI')

    def test_usuario_comum_nao_edita_identidade(self):
        self.client.force_login(self.comum)
        self._selecionar(self.ambar)

        response = self.client.get(reverse('identidade_visual_empresa'))

        self.assertEqual(response.status_code, 403)

    def test_midia_de_branding_nao_vaza_para_outra_empresa(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.cassoni.cabecalho_documentos = SimpleUploadedFile(
                'cabecalho.png',
                b'cabecalho-cassoni',
                content_type='image/png',
            )
            self.cassoni.save(update_fields=['cabecalho_documentos'])
            url = reverse('protected_media', kwargs={'path': self.cassoni.cabecalho_documentos.name})

            self.client.force_login(self.comum)
            self._selecionar(self.ambar)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

            self.client.force_login(self.admin)
            self._selecionar(self.cassoni)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            response.close()


class Fase6PilotoCassoniUsuariosTests(TestCase):
    def setUp(self):
        self.ambar = obter_ou_criar_empresa_padrao()
        self.cassoni = Empresa.objects.create(nome='Cassoni Engenharia', slug='cassoni')
        self.grupo_financeiro = Group.objects.get_or_create(name='Financeiro')[0]
        self.grupo_diretoria = Group.objects.get_or_create(name='Diretoria')[0]
        self.grupo_consulta = Group.objects.get_or_create(name='Consulta')[0]
        self.admin_cassoni = User.objects.create_user(username='admin-cassoni', password='senha')
        self.comum_cassoni = User.objects.create_user(username='comum-cassoni', password='senha')
        self.usuario_ambar = User.objects.create_user(username='usuario-ambar-fase6', password='senha')
        self.vinculo_admin = UsuarioEmpresa.objects.create(
            usuario=self.admin_cassoni,
            empresa=self.cassoni,
            grupo=self.grupo_diretoria,
            administrador_empresa=True,
        )
        self.vinculo_comum = UsuarioEmpresa.objects.create(
            usuario=self.comum_cassoni,
            empresa=self.cassoni,
            grupo=self.grupo_consulta,
            administrador_empresa=False,
        )
        self.vinculo_ambar = UsuarioEmpresa.objects.create(
            usuario=self.usuario_ambar,
            empresa=self.ambar,
            grupo=self.grupo_diretoria,
            administrador_empresa=True,
        )
        self.obra_cassoni = Obra.objects.create(empresa=self.cassoni, nome_obra='Obra Cassoni Fase 6')
        self.obra_ambar = Obra.objects.create(empresa=self.ambar, nome_obra='Obra Ambar Fase 6')

    def _selecionar(self, empresa):
        session = self.client.session
        session['empresa_id'] = empresa.id
        session.save()

    def test_usuario_somente_cassoni_entra_na_cassoni_sem_dropdown(self):
        self.client.force_login(self.comum_cassoni)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['empresa_id'], self.cassoni.id)
        self.assertContains(response, 'Cassoni Engenharia')
        self.assertNotContains(response, 'Escolher empresa')
        self.assertNotContains(response, 'Obra Ambar Fase 6')

    def test_usuario_cassoni_nao_consegue_trocar_para_ambar(self):
        self.client.force_login(self.comum_cassoni)
        self.client.get(reverse('home'))

        response = self.client.post(reverse('trocar_empresa', args=[self.ambar.id]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.session['empresa_id'], self.cassoni.id)

    def test_admin_cassoni_lista_apenas_vinculos_da_cassoni(self):
        self.client.force_login(self.admin_cassoni)
        self._selecionar(self.cassoni)

        response = self.client.get(reverse('usuarios_empresa'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin-cassoni')
        self.assertContains(response, 'comum-cassoni')
        self.assertNotContains(response, 'usuario-ambar-fase6')

    def test_usuario_comum_nao_acessa_usuarios_da_empresa(self):
        self.client.force_login(self.comum_cassoni)
        self._selecionar(self.cassoni)

        response = self.client.get(reverse('usuarios_empresa'))

        self.assertEqual(response.status_code, 403)

    def test_admin_cria_usuario_vinculado_somente_a_empresa_ativa(self):
        self.client.force_login(self.admin_cassoni)
        self._selecionar(self.cassoni)

        response = self.client.post(
            reverse('novo_usuario_empresa'),
            {
                'username': 'piloto-cassoni',
                'first_name': 'Piloto',
                'last_name': 'Cassoni',
                'email': 'piloto@example.com',
                'password': 'senha-temporaria-segura',
                'grupo': str(self.grupo_financeiro.id),
                'administrador_empresa': 'on',
                'obras_permitidas': [str(self.obra_cassoni.id)],
            },
        )

        self.assertRedirects(response, reverse('usuarios_empresa'))
        usuario = User.objects.get(username='piloto-cassoni')
        self.assertTrue(usuario.check_password('senha-temporaria-segura'))
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertFalse(usuario.groups.exists())
        vinculo = UsuarioEmpresa.objects.get(usuario=usuario)
        self.assertEqual(vinculo.empresa, self.cassoni)
        self.assertEqual(vinculo.grupo, self.grupo_financeiro)
        self.assertTrue(vinculo.administrador_empresa)
        self.assertTrue(vinculo.obras_permitidas.filter(pk=self.obra_cassoni.pk).exists())
        self.assertFalse(UsuarioEmpresa.objects.filter(usuario=usuario, empresa=self.ambar).exists())

    def test_post_adulterado_nao_aceita_obra_de_outra_empresa(self):
        self.client.force_login(self.admin_cassoni)
        self._selecionar(self.cassoni)

        response = self.client.post(
            reverse('novo_usuario_empresa'),
            {
                'username': 'tamper-obra',
                'password': 'senha-temporaria-segura',
                'grupo': str(self.grupo_financeiro.id),
                'obras_permitidas': [str(self.obra_ambar.id)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='tamper-obra').exists())

    def test_post_adulterado_nao_edita_vinculo_de_outro_tenant(self):
        self.client.force_login(self.admin_cassoni)
        self._selecionar(self.cassoni)

        response = self.client.post(
            reverse('editar_usuario_empresa', args=[self.vinculo_ambar.id]),
            {
                'first_name': 'Alterado',
                'grupo': str(self.grupo_financeiro.id),
                'administrador_empresa': 'on',
                'ativo': 'on',
            },
        )

        self.assertEqual(response.status_code, 404)
        self.usuario_ambar.refresh_from_db()
        self.assertNotEqual(self.usuario_ambar.first_name, 'Alterado')

    def test_nao_remove_ultimo_administrador_ativo(self):
        self.vinculo_comum.delete()
        self.client.force_login(self.admin_cassoni)
        self._selecionar(self.cassoni)

        response = self.client.post(
            reverse('editar_usuario_empresa', args=[self.vinculo_admin.id]),
            {
                'first_name': '',
                'last_name': '',
                'email': '',
                'grupo': str(self.grupo_diretoria.id),
                'ativo': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.vinculo_admin.refresh_from_db()
        self.assertTrue(self.vinculo_admin.administrador_empresa)

    def test_nao_desativa_ultimo_administrador_ativo(self):
        self.vinculo_comum.delete()
        self.client.force_login(self.admin_cassoni)
        self._selecionar(self.cassoni)

        response = self.client.post(reverse('alternar_status_usuario_empresa', args=[self.vinculo_admin.id]))

        self.assertRedirects(response, reverse('usuarios_empresa'))
        self.vinculo_admin.refresh_from_db()
        self.assertTrue(self.vinculo_admin.ativo)

    def test_grupo_do_vinculo_ativo_libera_financeiro_sem_user_groups(self):
        usuario = User.objects.create_user(username='financeiro-cassoni-vinculo', password='senha')
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.cassoni, grupo=self.grupo_financeiro)
        self.client.force_login(usuario)

        response = self.client.get(reverse('financeiro_home'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(usuario.groups.exists())
