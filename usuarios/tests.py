from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from obras.models import Obra

from .models import PerfilUsuario


User = get_user_model()


class UsuariosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='usuario', password='senha', first_name='Usuario')
        self.client.force_login(self.user)
        self.obra = Obra.objects.create(nome_obra='Obra Usuario', cliente='Cliente')

    def test_minha_area_cria_e_exibe_perfil(self):
        response = self.client.get(reverse('minha_area'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(PerfilUsuario.objects.filter(user=self.user).exists())
        self.assertContains(response, 'Minha area')
        self.assertContains(response, 'usuario')

    def test_usuario_comum_nao_acessa_administracao(self):
        response = self.client.get(reverse('lista_usuarios'))

        self.assertRedirects(response, reverse('minha_area'))

    def test_diretoria_cria_usuario_com_grupo_e_obra(self):
        diretoria = Group.objects.get_or_create(name='Diretoria')[0]
        financeiro = Group.objects.get_or_create(name='Financeiro')[0]
        self.user.groups.add(diretoria)

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
