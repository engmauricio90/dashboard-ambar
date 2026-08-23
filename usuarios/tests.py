from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from urllib.parse import urlparse

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

    def test_grupo_administrador_global_nao_administra_painel_legado(self):
        administrador = Group.objects.get_or_create(name='Administrador')[0]
        self.user.groups.add(administrador)

        response = self.client.get(reverse('lista_usuarios'))

        self.assertRedirects(response, reverse('minha_area'))

    def test_administrador_da_empresa_nao_acessa_painel_global_legado(self):
        UsuarioEmpresa.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa,
            defaults={'administrador_empresa': True},
        )

        response = self.client.get(reverse('lista_usuarios'))

        self.assertRedirects(response, reverse('minha_area'))

    def test_superuser_cria_usuario_com_grupo_e_obra_no_painel_tecnico(self):
        financeiro = Group.objects.get_or_create(name='Financeiro')[0]
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=['is_staff', 'is_superuser'])

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

    def test_staff_acessa_painel_global_legado_como_ferramenta_tecnica(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])

        response = self.client.get(reverse('lista_usuarios'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Usuarios')

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


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', PLATFORM_BASE_URL='https://app.exemplo.com')
class PasswordResetTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.get(slug='ambar')
        self.user = User.objects.create_user(
            username='reset-user',
            email='reset@example.com',
            password='senha-antiga-123',
        )
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.empresa)

    def _link_reset(self):
        for trecho in mail.outbox[-1].body.split():
            if '/senha/redefinir/' in trecho:
                return trecho
        self.fail('Link de reset nao encontrado.')

    def test_pagina_reset_acessivel_sem_login(self):
        response = self.client.get(reverse('password_reset'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Redefinir senha')

    def test_reset_email_existente_envia_link_absoluto_https(self):
        response = self.client.post(reverse('password_reset'), {'email': 'reset@example.com'})

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        link = self._link_reset()
        self.assertTrue(link.startswith('https://app.exemplo.com/senha/redefinir/'))
        self.assertIn('reset@example.com', mail.outbox[0].to)

    def test_reset_email_inexistente_tem_mesma_resposta_sem_envio(self):
        response = self.client.post(reverse('password_reset'), {'email': 'inexistente@example.com'})

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_email_duplicado_nao_escolhe_usuario_arbitrario(self):
        User.objects.create_user(username='reset-duplicado', email='reset@example.com', password='outra-senha-123')

        response = self.client.post(reverse('password_reset'), {'email': 'reset@example.com'})

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_link_valido_redefine_senha_e_token_nao_reutiliza(self):
        self.client.post(reverse('password_reset'), {'email': 'reset@example.com'})
        confirm_path = urlparse(self._link_reset()).path
        response = self.client.get(confirm_path)
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            response.url,
            {
                'new_password1': 'senha-nova-forte-123',
                'new_password2': 'senha-nova-forte-123',
            },
        )

        self.assertRedirects(response, reverse('password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('senha-nova-forte-123'))
        self.assertTrue(self.client.login(username='reset-user', password='senha-nova-forte-123'))
        response = self.client.get(confirm_path)
        self.assertContains(response, 'Link invalido')


class RateLimitAutenticacaoTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(LOGIN_RATE_LIMIT=2, LOGIN_RATE_LIMIT_WINDOW=300)
    def test_login_bloqueia_excesso_de_tentativas(self):
        for _indice in range(2):
            response = self.client.post(reverse('login'), {'username': 'alvo', 'password': 'errada'})
            self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse('login'), {'username': 'alvo', 'password': 'errada'})

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Muitas tentativas de login', status_code=429)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        PASSWORD_RESET_RATE_LIMIT=1,
        PASSWORD_RESET_RATE_LIMIT_WINDOW=3600,
    )
    def test_reset_senha_bloqueia_excesso_de_solicitacoes(self):
        response = self.client.post(reverse('password_reset'), {'email': 'alvo@example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))

        response = self.client.post(reverse('password_reset'), {'email': 'alvo@example.com'})

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Muitas solicitacoes', status_code=429)
