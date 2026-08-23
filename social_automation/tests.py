from datetime import timedelta
from io import BytesIO, StringIO
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from empresas.models import Empresa, UsuarioEmpresa

from .models import SocialBaseImage, SocialContent, SocialContentEvent, SocialProfile
from .ai import GeneratedContent
from .generation import gerar_lote_conteudos
from .image_selection import selecionar_imagem_base
from .rendering import renderizar_conteudo_social


User = get_user_model()


def imagem_teste(nome='base.jpg'):
    buffer = StringIO()
    image = Image.new('RGB', (10, 10), color='white')
    bytes_buffer = __import__('io').BytesIO()
    image.save(bytes_buffer, format='JPEG')
    return SimpleUploadedFile(nome, bytes_buffer.getvalue(), content_type='image/jpeg')


def imagem_social(nome='social.jpg', tamanho=(1200, 900), cor='steelblue'):
    image = Image.new('RGB', tamanho, color=cor)
    bytes_buffer = BytesIO()
    image.save(bytes_buffer, format='JPEG')
    return SimpleUploadedFile(nome, bytes_buffer.getvalue(), content_type='image/jpeg')


class SocialAutomationPermissionTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-social', password='senha', is_staff=True)
        self.superuser = User.objects.create_superuser(username='super-social', password='senha', email='super@example.com')
        self.tenant_admin = User.objects.create_user(username='tenant-admin-social', password='senha')
        self.comum = User.objects.create_user(username='comum-social', password='senha')
        empresa = Empresa.objects.get(slug='ambar')
        UsuarioEmpresa.objects.create(usuario=self.tenant_admin, empresa=empresa, administrador_empresa=True)
        UsuarioEmpresa.objects.create(usuario=self.comum, empresa=empresa)

    def test_staff_e_superuser_acessam_home_social(self):
        for user in [self.staff, self.superuser]:
            self.client.force_login(user)
            response = self.client.get(reverse('social_automation:home'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Automacao Social')

    def test_tenant_admin_e_usuario_comum_recebem_403(self):
        for user in [self.tenant_admin, self.comum]:
            self.client.force_login(user)
            response = self.client.get(reverse('social_automation:home'))
            self.assertEqual(response.status_code, 403)

    def test_menu_aparece_somente_para_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('clientes_plataforma'))
        self.assertContains(response, 'Automacao Social')

        self.client.force_login(self.tenant_admin)
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'Automacao Social')


class SocialAutomationProfileTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-profile-social', password='senha', is_staff=True)
        self.client.force_login(self.staff)

    def test_cria_edita_e_desativa_perfil_com_horarios_validos(self):
        response = self.client.post(
            reverse('social_automation:profile_create'),
            {
                'nome': 'Humor Cachorro',
                'username': '@humor.cachorro',
                'plataforma': SocialProfile.Plataforma.INSTAGRAM,
                'ativo': 'on',
                'timezone': 'America/Sao_Paulo',
                'modo_operacao': SocialProfile.ModoOperacao.SEMIAUTOMATICO,
                'posts_por_dia': '2',
                'horarios_texto': '12:00\n19:30',
                'estilo': 'Humor leve',
                'instrucoes_ia': 'Frases curtas',
                'limite_respostas': '0',
            },
        )

        profile = SocialProfile.objects.get(username='@humor.cachorro')
        self.assertRedirects(response, reverse('social_automation:profile_detail', args=[profile.id]))
        self.assertEqual(profile.horarios_publicacao, ['12:00', '19:30'])

        response = self.client.post(reverse('social_automation:profile_toggle', args=[profile.id]))
        self.assertRedirects(response, reverse('social_automation:profile_list'))
        profile.refresh_from_db()
        self.assertFalse(profile.ativo)

    def test_horario_invalido_e_bloqueado(self):
        response = self.client.post(
            reverse('social_automation:profile_create'),
            {
                'nome': 'Perfil Invalido',
                'username': '@invalido',
                'plataforma': SocialProfile.Plataforma.INSTAGRAM,
                'timezone': 'America/Sao_Paulo',
                'modo_operacao': SocialProfile.ModoOperacao.MANUAL,
                'posts_por_dia': '1',
                'horarios_texto': '99:99',
                'limite_respostas': '0',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SocialProfile.objects.filter(username='@invalido').exists())


class SocialAutomationWorkflowTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-workflow-social', password='senha', is_staff=True)
        self.client.force_login(self.staff)
        self.profile = SocialProfile.objects.create(nome='Humor Trabalho', username='@trabalho', horarios_publicacao=['12:00'])

    def test_upload_imagem_base_e_toggle(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse('social_automation:image_create', args=[self.profile.id]),
                {'nome': 'Cachorro serio', 'tags': 'cachorro, serio', 'ativa': 'on', 'arquivo': imagem_teste()},
            )

            image = SocialBaseImage.objects.get(profile=self.profile)
            self.assertRedirects(response, reverse('social_automation:image_list', args=[self.profile.id]))
            self.assertTrue(image.arquivo.name.startswith(f'social/{self.profile.id}/base/'))

            response = self.client.post(reverse('social_automation:image_toggle', args=[image.id]))
            self.assertRedirects(response, reverse('social_automation:image_list', args=[self.profile.id]))
            image.refresh_from_db()
            self.assertFalse(image.ativa)

    def test_cria_edita_aprova_rejeita_restaura_agenda_e_desagenda(self):
        content = SocialContent.objects.create(profile=self.profile, frase='Frase inicial')

        response = self.client.post(reverse('social_automation:content_approve', args=[content.id]))
        self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.APROVADO)
        self.assertTrue(content.events.filter(acao=SocialContentEvent.Acao.APROVADO).exists())

        data_futura = timezone.localdate() + timedelta(days=1)
        response = self.client.post(reverse('social_automation:content_schedule', args=[content.id]), {'data': data_futura.isoformat(), 'hora': '19:30'})
        self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.AGENDADO)
        self.assertIsNotNone(content.scheduled_at)

        response = self.client.post(reverse('social_automation:content_unschedule', args=[content.id]))
        self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.APROVADO)
        self.assertIsNone(content.scheduled_at)

        response = self.client.post(reverse('social_automation:content_reject', args=[content.id]))
        self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.REJEITADO)

        response = self.client.post(reverse('social_automation:content_restore', args=[content.id]))
        self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.RASCUNHO)

    def test_transicoes_invalidas_sao_bloqueadas(self):
        rejeitado = SocialContent.objects.create(profile=self.profile, frase='Ruim', status=SocialContent.Status.REJEITADO)
        response = self.client.post(reverse('social_automation:content_schedule', args=[rejeitado.id]), {'data': (timezone.localdate() + timedelta(days=1)).isoformat(), 'hora': '12:00'})
        self.assertRedirects(response, reverse('social_automation:content_detail', args=[rejeitado.id]))
        rejeitado.refresh_from_db()
        self.assertEqual(rejeitado.status, SocialContent.Status.REJEITADO)

        rascunho = SocialContent.objects.create(profile=self.profile, frase='Ainda rascunho')
        response = self.client.post(reverse('social_automation:content_schedule', args=[rascunho.id]), {'data': (timezone.localdate() + timedelta(days=1)).isoformat(), 'hora': '12:00'})
        self.assertRedirects(response, reverse('social_automation:content_detail', args=[rascunho.id]))
        rascunho.refresh_from_db()
        self.assertEqual(rascunho.status, SocialContent.Status.RASCUNHO)

    def test_fila_filtra_busca_pagina_e_aprova_lote(self):
        for indice in range(30):
            SocialContent.objects.create(profile=self.profile, frase=f'Frase lote {indice}', legenda='legenda busca')
        SocialContent.objects.create(profile=self.profile, frase='Agendado especial', status=SocialContent.Status.AGENDADO)

        response = self.client.get(reverse('social_automation:content_list'), {'busca': 'lote', 'status': SocialContent.Status.RASCUNHO})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 25)

        ids = list(SocialContent.objects.filter(status=SocialContent.Status.RASCUNHO).values_list('id', flat=True)[:3])
        response = self.client.post(reverse('social_automation:content_bulk_approve'), {'content_ids': [str(id_) for id_ in ids]})
        self.assertRedirects(response, reverse('social_automation:content_list'))
        self.assertEqual(SocialContent.objects.filter(id__in=ids, status=SocialContent.Status.APROVADO).count(), 3)

    def test_models_nao_possuem_campo_empresa(self):
        for model in [SocialProfile, SocialBaseImage, SocialContent, SocialContentEvent]:
            self.assertNotIn('empresa', [field.name for field in model._meta.fields])


class SocialAutomationCommandTests(TestCase):
    def test_dry_run_lista_somente_agendados_vencidos_de_perfil_ativo(self):
        profile = SocialProfile.objects.create(nome='Ativo', username='@ativo', horarios_publicacao=['12:00'])
        inactive = SocialProfile.objects.create(nome='Inativo', username='@inativo', ativo=False, horarios_publicacao=['12:00'])
        due = SocialContent.objects.create(
            profile=profile,
            frase='Vencido',
            status=SocialContent.Status.AGENDADO,
            scheduled_at=timezone.now() - timedelta(minutes=5),
        )
        SocialContent.objects.create(profile=profile, frase='Futuro', status=SocialContent.Status.AGENDADO, scheduled_at=timezone.now() + timedelta(days=1))
        SocialContent.objects.create(profile=profile, frase='Rascunho', status=SocialContent.Status.RASCUNHO)
        SocialContent.objects.create(profile=inactive, frase='Inativo', status=SocialContent.Status.AGENDADO, scheduled_at=timezone.now() - timedelta(minutes=5))

        output = StringIO()
        call_command('processar_fila_social', '--dry-run', stdout=output)

        texto = output.getvalue()
        self.assertIn(f'#{due.id}', texto)
        self.assertIn('Vencido', texto)
        self.assertNotIn('Futuro', texto)
        self.assertNotIn('Rascunho', texto)
        self.assertNotIn('Inativo', texto)


class SocialAutomationGenerationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-ai-social', password='senha', is_staff=True)
        self.client.force_login(self.staff)
        self.profile = SocialProfile.objects.create(
            nome='Perfil IA',
            username='@perfil.ia',
            horarios_publicacao=['12:00'],
            estilo='Construcao civil com linguagem clara',
            instrucoes_ia='Evite repeticao e gere frases curtas.',
        )

    def _base_image(self, profile=None, nome='Base', tags='obra, equipe', usada=0, ativa=True, cor='steelblue'):
        return SocialBaseImage.objects.create(
            profile=profile or self.profile,
            nome=nome,
            tags=tags,
            ativa=ativa,
            vezes_usada=usada,
            arquivo=imagem_social(f'{nome}.jpg', cor=cor),
        )

    def _generated(self, indice, frase=None, tags=None):
        return GeneratedContent(
            frase=frase or f'Frase unica de obra numero {indice}',
            legenda=f'Legenda de teste {indice}',
            hashtags=['obra', 'engenharia'],
            tags_imagem=tags or ['obra'],
        )

    @override_settings(OPENAI_API_KEY='', OPENAI_SOCIAL_MAX_BATCH=30)
    def test_sem_chave_openai_nao_gera_500(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._base_image()
            response = self.client.post(reverse('social_automation:profile_generate', args=[self.profile.id]), {'quantidade': '5'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Configure OPENAI_API_KEY')
        self.assertEqual(SocialContent.objects.count(), 0)

    @override_settings(OPENAI_API_KEY='test-key', OPENAI_SOCIAL_MAX_BATCH=30)
    def test_gera_lote_dez_rascunhos_com_card_final(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._base_image()
            gerados = [self._generated(i) for i in range(10)]
            with mock.patch('social_automation.generation.gerar_conteudos_ia', return_value=gerados), mock.patch(
                'social_automation.generation.moderar_conteudo',
                return_value=False,
            ):
                resultado = gerar_lote_conteudos(self.profile, 10, 'tema', self.staff)

            self.assertEqual(resultado.criados, 10)
            self.assertEqual(SocialContent.objects.filter(status=SocialContent.Status.RASCUNHO).count(), 10)
            self.assertEqual(SocialContent.objects.exclude(final_image='').count(), 10)
            self.assertTrue(SocialContentEvent.objects.filter(acao='gerado_ia').exists())

    @override_settings(OPENAI_API_KEY='test-key')
    def test_bloqueia_duplicidade_existente_e_no_mesmo_lote(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._base_image()
            SocialContent.objects.create(profile=self.profile, frase='Frase repetida existente')
            gerados = [
                self._generated(1, frase='Frase repetida existente'),
                self._generated(2, frase='Frase nova aprovada'),
                self._generated(3, frase='Frase nova aprovada'),
            ]
            with mock.patch('social_automation.generation.gerar_conteudos_ia', return_value=gerados), mock.patch(
                'social_automation.generation.moderar_conteudo',
                return_value=False,
            ):
                resultado = gerar_lote_conteudos(self.profile, 3, '', self.staff)

            self.assertEqual(resultado.criados, 1)
            self.assertEqual(resultado.duplicados, 2)

    @override_settings(OPENAI_API_KEY='test-key')
    def test_moderacao_bloqueia_sem_salvar_conteudo(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._base_image()
            gerados = [self._generated(1), self._generated(2)]
            with mock.patch('social_automation.generation.gerar_conteudos_ia', return_value=gerados), mock.patch(
                'social_automation.generation.moderar_conteudo',
                side_effect=[False, True],
            ):
                resultado = gerar_lote_conteudos(self.profile, 2, '', self.staff)

            self.assertEqual(resultado.criados, 1)
            self.assertEqual(resultado.bloqueados, 1)
            self.assertEqual(SocialContent.objects.count(), 1)

    @override_settings(OPENAI_API_KEY='test-key')
    def test_historico_considera_somente_o_perfil_atual(self):
        outro = SocialProfile.objects.create(nome='Outro', username='@outro', horarios_publicacao=['12:00'])
        SocialContent.objects.create(profile=self.profile, frase='Historico atual')
        SocialContent.objects.create(profile=outro, frase='Historico de outro perfil')
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._base_image()
            with mock.patch('social_automation.generation.gerar_conteudos_ia', return_value=[]) as gerar_mock:
                gerar_lote_conteudos(self.profile, 1, '', self.staff)

        historico = gerar_mock.call_args.args[3]
        self.assertIn('Historico atual', historico)
        self.assertNotIn('Historico de outro perfil', historico)

    def test_selecao_imagem_prioriza_ativa_menos_usada_e_tags(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self._base_image(nome='Inativa', tags='obra', usada=0, ativa=False)
            muito_usada = self._base_image(nome='Muito usada', tags='obra', usada=10)
            menos_usada = self._base_image(nome='Menos usada', tags='obra', usada=1)
            escolhida = selecionar_imagem_base(self.profile, ['obra'])

        self.assertEqual(escolhida.id, menos_usada.id)
        self.assertNotEqual(escolhida.id, muito_usada.id)

    @override_settings(OPENAI_API_KEY='test-key')
    def test_sem_imagem_bloqueia_antes_de_chamar_api(self):
        with mock.patch('social_automation.generation.gerar_conteudos_ia') as gerar_mock:
            with self.assertRaisesMessage(Exception, 'imagem-base ativa'):
                gerar_lote_conteudos(self.profile, 1, '', self.staff)
        gerar_mock.assert_not_called()

    def test_renderizacao_gera_jpg_1080_sem_alterar_original(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self._base_image()
            with image.arquivo.open('rb') as arquivo:
                original = arquivo.read()
            content = SocialContent.objects.create(
                profile=self.profile,
                base_image=image,
                frase='Execucao de servico com descricao extensa para validar quebra automatica e legibilidade do card.',
            )
            renderizar_conteudo_social(content)
            content.refresh_from_db()
            with Image.open(content.final_image.path) as final:
                self.assertEqual(final.size, (1080, 1080))
                self.assertEqual(final.mode, 'RGB')
            with image.arquivo.open('rb') as arquivo:
                self.assertEqual(arquivo.read(), original)

    def test_editar_frase_rerenderiza_e_editar_legenda_nao(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self._base_image()
            content = SocialContent.objects.create(profile=self.profile, base_image=image, frase='Frase inicial para card')
            renderizar_conteudo_social(content)
            content.refresh_from_db()
            primeiro_card = content.final_image.name

            response = self.client.post(
                reverse('social_automation:content_update', args=[content.id]),
                {
                    'profile': self.profile.id,
                    'base_image': image.id,
                    'frase': 'Frase alterada para card',
                    'legenda': '',
                    'hashtags': '',
                },
            )
            self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
            content.refresh_from_db()
            segundo_card = content.final_image.name
            self.assertNotEqual(primeiro_card, segundo_card)

            response = self.client.post(
                reverse('social_automation:content_update', args=[content.id]),
                {
                    'profile': self.profile.id,
                    'base_image': image.id,
                    'frase': 'Frase alterada para card',
                    'legenda': 'Somente legenda mudou',
                    'hashtags': '',
                },
            )
            self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
            content.refresh_from_db()
            self.assertEqual(content.final_image.name, segundo_card)

    def test_tela_de_geracao_continua_restrita_a_staff(self):
        comum = User.objects.create_user(username='usuario-social-nao-staff', password='senha')
        self.client.force_login(comum)
        response = self.client.get(reverse('social_automation:profile_generate', args=[self.profile.id]))
        self.assertEqual(response.status_code, 403)
