from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from empresas.models import Empresa, UsuarioEmpresa
from obras.models import Obra

from .models import PerfilUsuario


User = get_user_model()


class UsuariosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='usuario', password='senha', first_name='Usuario')
        self.empresa = Empresa.objects.get(slug='ambar')
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.empresa)
        self.client.force_login(self.user)
        self.obra = Obra.objects.create(empresa=self.empresa, nome_obra='Obra Usuario', cliente='Cliente')

    def test_minha_area_cria_e_exibe_perfil(self):
        response = self.client.get(reverse('minha_area'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(PerfilUsuario.objects.filter(user=self.user).exists())
        self.assertContains(response, 'Minha area')
        self.assertContains(response, 'usuario')

    def test_usuario_comum_nao_acessa_administracao(self):
        response = self.client.get(reverse('lista_usuarios'))

        self.assertRedirects(response, reverse('minha_area'))

    def test_usuario_comum_nao_altera_usuarios_por_acesso_direto(self):
        outro = User.objects.create_user(username='outro', password='senha')

        response_novo = self.client.post(reverse('novo_usuario'), {'username': 'bloqueado'})
        response_editar = self.client.post(reverse('editar_usuario', args=[outro.id]), {'username': 'alterado'})
        response_status = self.client.post(reverse('alternar_status_usuario', args=[outro.id]))

        self.assertRedirects(response_novo, reverse('minha_area'))
        self.assertRedirects(response_editar, reverse('minha_area'))
        self.assertRedirects(response_status, reverse('minha_area'))
        outro.refresh_from_db()
        self.assertEqual(outro.username, 'outro')
        self.assertTrue(outro.is_active)

    def test_diretoria_sem_grupo_administrador_nao_administra_usuarios(self):
        self.user.groups.add(Group.objects.get_or_create(name='Diretoria')[0])

        response = self.client.get(reverse('lista_usuarios'))

        self.assertRedirects(response, reverse('minha_area'))

    def test_administrador_cria_usuario_com_grupo_e_obra(self):
        administrador = Group.objects.get_or_create(name='Administrador')[0]
        financeiro = Group.objects.get_or_create(name='Financeiro')[0]
        UsuarioEmpresa.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa,
            defaults={'administrador_empresa': True},
        )
        self.user.groups.add(administrador)

        response = self.client.post(
            reverse('novo_usuario'),
            {
                'username': 'financeiro',
                'first_name': 'Ana',
                'last_name': 'Financeiro',
                'email': 'ana@example.com',
                'is_active': 'on',
                'password': 'senha-provisoria',
                'grupos': [str(financeiro.id)],
                'telefone': '51999999999',
                'cargo': 'Analista financeiro',
                'setor': 'financeiro',
                'obras': [str(self.obra.id)],
                'dashboard_inicial': 'Financeiro',
                'itens_por_pagina': '30',
                'observacoes': '',
            },
        )

        self.assertRedirects(response, reverse('lista_usuarios'))
        novo = User.objects.get(username='financeiro')
        self.assertTrue(novo.check_password('senha-provisoria'))
        self.assertTrue(novo.groups.filter(name='Financeiro').exists())
        self.assertEqual(novo.perfil.cargo, 'Analista financeiro')
        self.assertTrue(novo.perfil.obras.filter(id=self.obra.id).exists())
        self.assertTrue(UsuarioEmpresa.objects.filter(usuario=novo, empresa=self.empresa, ativo=True).exists())

    def test_usuario_edita_proprio_perfil(self):
        response = self.client.post(
            reverse('editar_meu_perfil'),
            {
                'telefone': '5100000000',
                'cargo': 'Engenheiro',
                'setor': 'engenharia',
                'dashboard_inicial': 'Obras',
                'itens_por_pagina': '40',
            },
        )

        self.assertRedirects(response, reverse('minha_area'))
        perfil = PerfilUsuario.objects.get(user=self.user)
        self.assertEqual(perfil.telefone, '5100000000')
        self.assertEqual(perfil.setor, 'engenharia')

    def test_usuario_altera_propria_senha(self):
        response = self.client.post(
            reverse('alterar_minha_senha'),
            {
                'old_password': 'senha',
                'new_password1': 'nova-senha-forte-123',
                'new_password2': 'nova-senha-forte-123',
            },
        )

        self.assertRedirects(response, reverse('minha_area'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('nova-senha-forte-123'))
        response_area = self.client.get(reverse('minha_area'))
        self.assertEqual(response_area.status_code, 200)
