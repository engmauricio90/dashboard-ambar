from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Empresa, UsuarioEmpresa
from .services import obter_ou_criar_empresa_padrao, vincular_usuarios_existentes_a_empresa_padrao


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
