from datetime import timedelta
from io import BytesIO, StringIO
from hashlib import sha256
import importlib.util
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.parse
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw

from empresas.models import Empresa, UsuarioEmpresa

from .models import SocialBaseImage, SocialContent, SocialContentEvent, SocialProfile
from .ai import GeneratedContent
from .automation import executar_tick_social
from .generation import GenerationResult, _image_contexts, gerar_lote_conteudos
from .image_selection import selecionar_imagem_base
from .instagram import (
    InstagramAPIError,
    MEDIA_SIGNING_SALT,
    PUBLICADO_INSTAGRAM,
    auditar_imagem_final,
    criar_container_imagem,
    gerar_assinatura_midia_meta,
    gerar_token_midia_temporaria,
    publicar_conteudo_instagram,
    resumir_image_url,
    url_midia_meta_compat,
    url_midia_temporaria,
    validar_assinatura_midia_meta,
    validar_token_midia_temporaria,
)
from .rendering import SocialRenderError, renderizar_conteudo_social
from .rendering import _draw_text_box, _layout_text, _region, _text_boxes
from .scheduler import estoque_pronto, preencher_agenda


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
                {
                    'nome': 'Cachorro serio',
                    'tags': 'cachorro, serio',
                    'text_position': SocialBaseImage.TextPosition.AUTO,
                    'ativa': 'on',
                    'arquivo': imagem_teste(),
                },
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


class SocialAutomationCronTriggerScriptTests(TestCase):
    def _script(self):
        path = Path('scripts/acionar_automacao_social.py').resolve()
        spec = importlib.util.spec_from_file_location('cron_trigger_script', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_script_nao_importa_django_nem_app(self):
        source = Path('scripts/acionar_automacao_social.py').read_text(encoding='utf-8')
        self.assertNotIn('django', source)
        self.assertNotIn('social_automation', source)

    def test_env_ausente_falha_sem_secret(self):
        script = self._script()
        stderr = StringIO()

        code = script.trigger(env={}, stdout=StringIO(), stderr=stderr)

        self.assertEqual(code, 1)
        self.assertIn('PLATFORM_BASE_URL', stderr.getvalue())

    def test_secret_ausente_falha(self):
        script = self._script()
        stderr = StringIO()

        code = script.trigger(env={'PLATFORM_BASE_URL': 'https://dashboard-ambar.onrender.com'}, stdout=StringIO(), stderr=stderr)

        self.assertEqual(code, 1)
        self.assertIn('SOCIAL_AUTOMATION_CRON_SECRET', stderr.getvalue())

    def test_post_correto_retorna_zero_sem_expor_secret(self):
        script = self._script()
        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"status": "ok"}'

        def fake_opener(request, timeout):
            captured['url'] = request.full_url
            captured['method'] = request.get_method()
            captured['auth'] = request.headers.get('Authorization')
            captured['content_type'] = request.headers.get('Content-type')
            captured['body'] = request.data
            captured['timeout'] = timeout
            return FakeResponse()

        stdout = StringIO()
        stderr = StringIO()
        env = {'PLATFORM_BASE_URL': 'https://dashboard-ambar.onrender.com', 'SOCIAL_AUTOMATION_CRON_SECRET': 'segredo-cron'}

        code = script.trigger(env=env, opener=fake_opener, stdout=stdout, stderr=stderr)

        self.assertEqual(code, 0)
        self.assertEqual(captured['url'], 'https://dashboard-ambar.onrender.com/internal/social-automation/tick/')
        self.assertEqual(captured['method'], 'POST')
        self.assertEqual(captured['auth'], 'Bearer segredo-cron')
        self.assertEqual(captured['content_type'], 'application/json')
        self.assertEqual(captured['body'], b'{}')
        self.assertEqual(captured['timeout'], 120)
        self.assertNotIn('segredo-cron', stdout.getvalue())
        self.assertNotIn('segredo-cron', stderr.getvalue())

    def test_http_403_e_500_retornam_um_e_sanitizam_secret(self):
        script = self._script()
        env = {'PLATFORM_BASE_URL': 'https://dashboard-ambar.onrender.com', 'SOCIAL_AUTOMATION_CRON_SECRET': 'segredo-cron'}
        for status in [403, 500]:
            with self.subTest(status=status):
                def fake_opener(request, timeout):
                    body = BytesIO(f'erro segredo-cron {status}'.encode('utf-8'))
                    raise urllib.error.HTTPError(request.full_url, status, 'Erro', {}, body)

                stderr = StringIO()
                code = script.trigger(env=env, opener=fake_opener, stdout=StringIO(), stderr=stderr)

                self.assertEqual(code, 1)
                self.assertIn(f'HTTP {status}', stderr.getvalue())
                self.assertNotIn('segredo-cron', stderr.getvalue())

    def test_timeout_retorna_um_sem_secret(self):
        script = self._script()

        def fake_opener(request, timeout):
            raise TimeoutError('tempo esgotado')

        stderr = StringIO()
        code = script.trigger(
            env={'PLATFORM_BASE_URL': 'https://dashboard-ambar.onrender.com', 'SOCIAL_AUTOMATION_CRON_SECRET': 'segredo-cron'},
            opener=fake_opener,
            stdout=StringIO(),
            stderr=stderr,
        )

        self.assertEqual(code, 1)
        self.assertIn('TimeoutError', stderr.getvalue())
        self.assertNotIn('segredo-cron', stderr.getvalue())


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


class SocialAutomationRenderingPositionTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-render-social', password='senha', is_staff=True)
        self.client.force_login(self.staff)
        self.profile = SocialProfile.objects.create(nome='Perfil Visual', username='@visual', horarios_publicacao=['12:00'])

    def _image(self, position, nome='base-position'):
        return SocialBaseImage.objects.create(
            profile=self.profile,
            nome=nome,
            tags='laila, fundo limpo',
            text_position=position,
            arquivo=imagem_social(f'{nome}-{position}.jpg', tamanho=(1400, 1100), cor='darkseagreen'),
        )

    def _content(self, image, frase='Segunda-feira tambem tem seu charme duvidoso'):
        return SocialContent.objects.create(profile=self.profile, base_image=image, frase=frase)

    def test_renderiza_posicoes_preferenciais_e_auto(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            for position in [
                SocialBaseImage.TextPosition.LEFT,
                SocialBaseImage.TextPosition.RIGHT,
                SocialBaseImage.TextPosition.TOP,
                SocialBaseImage.TextPosition.BOTTOM,
                SocialBaseImage.TextPosition.AUTO,
            ]:
                content = self._content(self._image(position, nome=f'base-{position}'))
                renderizar_conteudo_social(content)
                content.refresh_from_db()
                with Image.open(content.final_image.path) as final:
                    self.assertEqual(final.size, (1080, 1080))
                    self.assertEqual(final.format, 'JPEG')

    def test_frase_longa_reduz_fonte_sem_cortar(self):
        frase = (
            'Execucao de rotina com descricao propositalmente extensa para validar quebra de linha, '
            'reducao de fonte e preservacao da regiao segura do texto.'
        )
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content(self._image(SocialBaseImage.TextPosition.LEFT), frase=frase)
            renderizar_conteudo_social(content)
            content.refresh_from_db()
            self.assertTrue(content.final_image.name.endswith('.jpg'))

    def test_layout_prefere_menos_linhas_para_frases_tipicas(self):
        canvas = Image.new('RGBA', (1080, 1080))
        draw = ImageDraw.Draw(canvas)
        frases = [
            'Meu salario e timido: aparece e some.',
            'Se segunda fosse comida, eu devolvia.',
            'Hoje eu acordei produtiva por engano.',
        ]
        for position in [
            SocialBaseImage.TextPosition.LEFT,
            SocialBaseImage.TextPosition.RIGHT,
            SocialBaseImage.TextPosition.TOP,
            SocialBaseImage.TextPosition.BOTTOM,
            SocialBaseImage.TextPosition.AUTO,
        ]:
            region, _align = _region(position)
            for frase in frases:
                _font, lines, _line_height, _text_height = _layout_text(draw, frase, region[2], region[3])
                self.assertLessEqual(len(lines), 4, f'{position}: {lines}')

    def test_regioes_usam_mais_largura_sem_ocupar_canvas_inteiro(self):
        left, _ = _region(SocialBaseImage.TextPosition.LEFT)
        right, _ = _region(SocialBaseImage.TextPosition.RIGHT)
        bottom, _ = _region(SocialBaseImage.TextPosition.BOTTOM)

        self.assertGreaterEqual(left[2], 520)
        self.assertGreaterEqual(right[2], 520)
        self.assertGreaterEqual(bottom[2], 900)
        self.assertLess(left[2], 1080)
        self.assertLess(right[2], 1080)

    def test_texto_impossivel_falha_sem_truncar(self):
        frase = 'X' * 900
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content(self._image(SocialBaseImage.TextPosition.RIGHT), frase=frase)
            with self.assertRaises(SocialRenderError):
                renderizar_conteudo_social(content)

    def test_original_permanece_intacto(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self._image(SocialBaseImage.TextPosition.BOTTOM)
            with image.arquivo.open('rb') as arquivo:
                original = arquivo.read()
            renderizar_conteudo_social(self._content(image))
            with image.arquivo.open('rb') as arquivo:
                self.assertEqual(arquivo.read(), original)

    def test_rerender_usa_posicao_atual_da_imagem(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self._image(SocialBaseImage.TextPosition.LEFT)
            content = self._content(image)
            renderizar_conteudo_social(content)
            content.refresh_from_db()
            primeiro = content.final_image.name

            image.text_position = SocialBaseImage.TextPosition.RIGHT
            image.save(update_fields=['text_position', 'updated_at'])
            response = self.client.post(reverse('social_automation:content_render', args=[content.id]))

            self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
            content.refresh_from_db()
            self.assertNotEqual(primeiro, content.final_image.name)

    def test_caixa_primaria_configurada_define_regiao_e_alinhamento(self):
        image = self._image(SocialBaseImage.TextPosition.AUTO_SMART)
        image.primary_text_box_x = 8
        image.primary_text_box_y = 52
        image.primary_text_box_width = 40
        image.primary_text_box_height = 28
        image.text_align_horizontal = SocialBaseImage.TextAlignHorizontal.LEFT
        image.text_align_vertical = SocialBaseImage.TextAlignVertical.BOTTOM
        image.save()

        boxes = _text_boxes(image)

        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]['name'], 'primary')
        self.assertEqual(boxes[0]['region'], (86, 562, 432, 302))
        self.assertEqual(boxes[0]['align_horizontal'], 'left')
        self.assertEqual(boxes[0]['align_vertical'], 'bottom')

    def test_caixa_secundaria_e_usada_quando_primaria_nao_comporta_texto(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self._image(SocialBaseImage.TextPosition.AUTO_SMART)
            image.primary_text_box_x = 5
            image.primary_text_box_y = 5
            image.primary_text_box_width = 4
            image.primary_text_box_height = 4
            image.secondary_text_box_x = 50
            image.secondary_text_box_y = 58
            image.secondary_text_box_width = 42
            image.secondary_text_box_height = 30
            image.secondary_text_align_horizontal = SocialBaseImage.TextAlignHorizontal.RIGHT
            image.save()

            content = self._content(image, frase='Frase curta para testar fallback visual')
            renderizar_conteudo_social(content)
            content.refresh_from_db()

            self.assertTrue(content.final_image.name.endswith('.jpg'))

    def test_sem_caixa_configurada_mantem_fallback_por_text_position(self):
        image = self._image(SocialBaseImage.TextPosition.LEFT)

        boxes = _text_boxes(image)
        legacy, align = _region(SocialBaseImage.TextPosition.LEFT)

        self.assertEqual(boxes[0]['name'], 'legacy')
        self.assertEqual(boxes[0]['region'], legacy)
        self.assertEqual(boxes[0]['align_horizontal'], align)

    def test_texto_desenhado_nao_ultrapassa_caixa_configurada(self):
        overlay = Image.new('RGBA', (1080, 1080), (0, 0, 0, 0))
        box = {
            'name': 'primary',
            'region': (100, 200, 360, 220),
            'align_horizontal': 'center',
            'align_vertical': 'middle',
            'gradient_position': 'left',
        }

        _draw_text_box(overlay, 'Texto curto dentro da caixa permitida', box)

        alpha = overlay.getchannel('A')
        outside = Image.new('L', (1080, 1080), 255)
        ImageDraw.Draw(outside).rectangle((100, 200, 460, 420), fill=0)
        outside_alpha = Image.composite(alpha, Image.new('L', (1080, 1080), 0), outside)
        self.assertIsNone(outside_alpha.getbbox())

    def test_form_salva_posicao_e_choice_invalido_falha(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse('social_automation:image_create', args=[self.profile.id]),
                {
                    'nome': 'Laila esquerda',
                    'tags': 'laila',
                    'text_position': SocialBaseImage.TextPosition.LEFT,
                    'ativa': 'on',
                    'arquivo': imagem_social('laila-esquerda.jpg'),
                },
            )
            self.assertRedirects(response, reverse('social_automation:image_list', args=[self.profile.id]))
            image = SocialBaseImage.objects.get(nome='Laila esquerda')
            self.assertEqual(image.text_position, SocialBaseImage.TextPosition.LEFT)

            response = self.client.post(
                reverse('social_automation:image_update', args=[image.id]),
                {'nome': 'Laila esquerda', 'tags': 'laila', 'text_position': 'centro', 'ativa': 'on'},
            )
            self.assertEqual(response.status_code, 200)
            image.refresh_from_db()
            self.assertEqual(image.text_position, SocialBaseImage.TextPosition.LEFT)

    def test_form_salva_preset_e_caixa_manual(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse('social_automation:image_create', args=[self.profile.id]),
                {
                    'nome': 'Laila meio esquerda',
                    'tags': 'laila',
                    'text_position': SocialBaseImage.TextPosition.AUTO_SMART,
                    'text_box_preset': SocialBaseImage.TextBoxPreset.MIDDLE_LEFT,
                    'primary_text_box_x': '9',
                    'primary_text_box_y': '38',
                    'primary_text_box_width': '41',
                    'primary_text_box_height': '30',
                    'text_align_horizontal': SocialBaseImage.TextAlignHorizontal.LEFT,
                    'text_align_vertical': SocialBaseImage.TextAlignVertical.MIDDLE,
                    'secondary_text_align_horizontal': SocialBaseImage.TextAlignHorizontal.CENTER,
                    'secondary_text_align_vertical': SocialBaseImage.TextAlignVertical.MIDDLE,
                    'ativa': 'on',
                    'arquivo': imagem_social('laila-meio-esquerda.jpg'),
                },
            )

            self.assertRedirects(response, reverse('social_automation:image_list', args=[self.profile.id]))
            image = SocialBaseImage.objects.get(nome='Laila meio esquerda')
            self.assertEqual(image.text_position, SocialBaseImage.TextPosition.AUTO_SMART)
            self.assertEqual(float(image.primary_text_box_x), 9)
            self.assertEqual(image.text_align_horizontal, SocialBaseImage.TextAlignHorizontal.LEFT)

    def test_contexto_de_ia_considera_area_disponivel_da_imagem(self):
        image = self._image(SocialBaseImage.TextPosition.AUTO_SMART)
        image.primary_text_box_x = 7
        image.primary_text_box_y = 60
        image.primary_text_box_width = 30
        image.primary_text_box_height = 20
        image.save()

        contexts = _image_contexts(self.profile)

        self.assertEqual(contexts[0]['nome'], image.nome)
        self.assertIn('area_disponivel_percentual', contexts[0])
        self.assertIn('curta', contexts[0]['tamanho_recomendado_frase'])


class SocialAutomationFullAutomationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-auto-social', password='senha', is_staff=True)
        self.client.force_login(self.staff)
        self.profile = SocialProfile.objects.create(
            nome='Laila',
            username='@lailapistola',
            modo_operacao=SocialProfile.ModoOperacao.AUTOMATICO,
            posts_por_dia=20,
            horarios_publicacao=['07:00', '07:50', '08:40'],
            timezone='America/Sao_Paulo',
        )

    def _ready_content(self, status=SocialContent.Status.APROVADO, scheduled_at=None, frase='conteudo pronto'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        media_override = override_settings(MEDIA_ROOT=tmp.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        image = SocialBaseImage.objects.create(profile=self.profile, nome=f'Base {frase}', tags='laila', arquivo=imagem_social())
        content = SocialContent.objects.create(
            profile=self.profile,
            base_image=image,
            frase=frase,
            legenda='Legenda valida',
            hashtags='#laila',
            status=status,
            scheduled_at=scheduled_at,
        )
        renderizar_conteudo_social(content)
        content.refresh_from_db()
        return content

    @override_settings(INSTAGRAM_EXPECTED_USERNAME='lailapistola')
    def test_scheduler_cria_slots_futuros_sem_agendar_rascunho_antigo(self):
        now = timezone.datetime(2026, 1, 1, 8, 0, tzinfo=timezone.get_current_timezone())
        aprovado = self._ready_content(frase='aprovado')
        rascunho = self._ready_content(status=SocialContent.Status.RASCUNHO, frase='rascunho antigo')

        result = preencher_agenda(self.profile, now=now, days=2)

        aprovado.refresh_from_db()
        rascunho.refresh_from_db()
        self.assertEqual(result.scheduled, 1)
        self.assertEqual(aprovado.status, SocialContent.Status.AGENDADO)
        self.assertGreater(aprovado.scheduled_at, now)
        self.assertEqual(rascunho.status, SocialContent.Status.RASCUNHO)

    @override_settings(
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        SOCIAL_AUTOMATION_QUEUE_MIN=40,
        SOCIAL_AUTOMATION_QUEUE_TARGET=60,
        SOCIAL_AUTOMATION_GENERATION_BATCH=5,
        OPENAI_API_KEY='test-key',
    )
    def test_tick_gera_lote_quando_estoque_baixo_e_autoaprova_somente_gerados(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            SocialBaseImage.objects.create(profile=self.profile, nome='Base', tags='laila', arquivo=imagem_social())
            antigo = SocialContent.objects.create(profile=self.profile, frase='rascunho antigo', legenda='legenda', status=SocialContent.Status.RASCUNHO)
            generated = [GeneratedContent(frase=f'Frase evergreen {i}', legenda='Legenda valida', hashtags=['laila'], tags_imagem=['laila']) for i in range(5)]
            with mock.patch('social_automation.generation.gerar_conteudos_ia', return_value=generated), mock.patch('social_automation.generation.moderar_conteudo', return_value=False):
                summary = executar_tick_social(use_lock=False, now=timezone.now())

            antigo.refresh_from_db()
            self.assertEqual(antigo.status, SocialContent.Status.RASCUNHO)
            self.assertEqual(summary['profiles'][0]['generated'], 5)
            self.assertEqual(summary['profiles'][0]['approved'], 5)
            self.assertEqual(self.profile.contents.filter(status__in=[SocialContent.Status.APROVADO, SocialContent.Status.AGENDADO]).count(), 5)

    @override_settings(
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        SOCIAL_AUTOMATION_QUEUE_MIN=40,
        SOCIAL_AUTOMATION_QUEUE_TARGET=60,
        SOCIAL_AUTOMATION_GENERATION_BATCH=5,
    )
    def test_politica_estoque_tende_ao_target_sem_ultrapassar_intencionalmente(self):
        cenarios = [
            (60, 0),
            (59, 1),
            (55, 5),
            (44, 5),
            (39, 5),
        ]
        for inventory, expected_batch in cenarios:
            with self.subTest(inventory=inventory):
                SocialContent.objects.all().delete()
                for index in range(inventory):
                    SocialContent.objects.create(
                        profile=self.profile,
                        frase=f'Estoque {inventory}-{index}',
                        legenda='Legenda',
                        status=SocialContent.Status.APROVADO,
                        final_image='social/fake.jpg',
                    )

                calls = []

                def fake_generation(profile, quantidade, tema, usuario):
                    calls.append(quantidade)
                    return GenerationResult(solicitados=quantidade, criados=quantidade)

                with mock.patch('social_automation.automation.gerar_lote_conteudos', side_effect=fake_generation):
                    summary = executar_tick_social(use_lock=False, now=timezone.now())

                if expected_batch:
                    self.assertEqual(calls, [expected_batch])
                    self.assertEqual(summary['profiles'][0]['generated'], expected_batch)
                else:
                    self.assertEqual(calls, [])
                    self.assertEqual(summary['profiles'][0]['generated'], 0)

    @override_settings(INSTAGRAM_EXPECTED_USERNAME='lailapistola', SOCIAL_AUTOMATION_MIN_POST_GAP_MINUTES=30, SOCIAL_AUTOMATION_HARD_24H_CAP=30)
    def test_tick_publica_no_maximo_um_e_respeita_gap(self):
        now = timezone.now()
        due_one = self._ready_content(status=SocialContent.Status.AGENDADO, scheduled_at=now - timedelta(minutes=10), frase='due one')
        due_two = self._ready_content(status=SocialContent.Status.AGENDADO, scheduled_at=now - timedelta(minutes=5), frase='due two')
        with mock.patch('social_automation.automation.publicar_conteudo_instagram') as publish:
            def fake_publish(content, usuario=None):
                content.status = SocialContent.Status.PUBLICADO
                content.published_at = now
                content.external_post_id = f'media-{content.id}'
                content.save(update_fields=['status', 'published_at', 'external_post_id', 'updated_at'])
                return content

            publish.side_effect = fake_publish
            summary = executar_tick_social(use_lock=False, now=now)

        due_one.refresh_from_db()
        due_two.refresh_from_db()
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(summary['profiles'][0]['published'], 1)
        self.assertEqual(due_one.status, SocialContent.Status.PUBLICADO)
        self.assertNotEqual(due_two.status, SocialContent.Status.PUBLICADO)

    @override_settings(SOCIAL_AUTOMATION_CRON_SECRET='segredo-cron')
    def test_endpoint_cron_exige_secret_post_e_lock(self):
        get_response = self.client.get(reverse('social_automation_tick'))
        self.assertEqual(get_response.status_code, 405)

        forbidden = self.client.post(reverse('social_automation_tick'), HTTP_AUTHORIZATION='Bearer errado')
        self.assertEqual(forbidden.status_code, 403)

        with mock.patch('social_automation.views.executar_tick_social', return_value={'status': 'ok', 'profiles': []}) as tick:
            response = self.client.post(reverse('social_automation_tick'), HTTP_AUTHORIZATION='Bearer segredo-cron')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        tick.assert_called_once()

    @override_settings(SOCIAL_AUTOMATION_CRON_SECRET='')
    def test_endpoint_cron_indisponivel_sem_secret(self):
        response = self.client.post(reverse('social_automation_tick'), HTTP_AUTHORIZATION='Bearer qualquer')
        self.assertEqual(response.status_code, 503)

    def test_lock_impede_tick_concorrente(self):
        from django.core.cache import cache

        cache.add('social_automation_tick_lock', 'ocupado', 60)
        result = executar_tick_social()
        cache.delete('social_automation_tick_lock')
        self.assertEqual(result['status'], 'already_running')

    def test_botao_staff_executa_mesmo_tick(self):
        with mock.patch('social_automation.views.executar_tick_social', return_value={'status': 'ok', 'profiles': [{'published': 0, 'scheduled': 1, 'generated': 0}]}):
            response = self.client.post(reverse('social_automation:automation_run_now', args=[self.profile.id]))
        self.assertRedirects(response, reverse('social_automation:profile_detail', args=[self.profile.id]))

    def test_configurar_automacao_social_preset_20_dia(self):
        output = StringIO()
        call_command('configurar_automacao_social', 'lailapistola', '--preset', '20-dia', '--dry-run', stdout=output)
        self.assertIn('posts_por_dia=20', output.getvalue())

        call_command('configurar_automacao_social', 'lailapistola', '--preset', '20-dia', '--apply', stdout=StringIO())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.modo_operacao, SocialProfile.ModoOperacao.AUTOMATICO)
        self.assertEqual(self.profile.posts_por_dia, 20)
        self.assertEqual(len(self.profile.horarios_publicacao), 20)


class SocialAutomationInstagramIntegrationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-instagram-social', password='senha', is_staff=True)
        self.client.force_login(self.staff)
        self.profile = SocialProfile.objects.create(nome='Laila Pistola', username='@lailapistola', horarios_publicacao=['12:00'])

    def _content_ready(self, status=SocialContent.Status.APROVADO, username='@lailapistola'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        media_override = override_settings(MEDIA_ROOT=tmp.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.profile.username = username
        self.profile.save(update_fields=['username', 'updated_at'])
        image = SocialBaseImage.objects.create(
            profile=self.profile,
            nome='Base Instagram',
            tags='laila',
            arquivo=imagem_social('instagram-base.jpg'),
        )
        content = SocialContent.objects.create(
            profile=self.profile,
            base_image=image,
            frase='Segunda-feira chegou com personalidade',
            legenda='Legenda curta',
            hashtags='#laila #humor',
            status=status,
        )
        renderizar_conteudo_social(content)
        content.refresh_from_db()
        return content

    @override_settings(INSTAGRAM_MEDIA_URL_TTL_SECONDS=3600)
    def test_signed_url_valida_serve_imagem_e_rejeita_token_invalido(self):
        content = self._content_ready()
        token = gerar_token_midia_temporaria(content)
        response = self.client.get(reverse('social_public_final_image', args=[token]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertEqual(response['Cache-Control'], 'private, max-age=0, no-store')
        self.assertIn('inline', response.get('Content-Disposition', ''))
        self.assertIn('.jpg', response.get('Content-Disposition', ''))
        body = b''.join(response.streaming_content)
        self.assertTrue(body.startswith(b'\xff\xd8\xff'))
        image = Image.open(BytesIO(body))
        self.assertEqual(image.format, 'JPEG')
        self.assertEqual(image.size, (1080, 1080))
        response.close()

        response = self.client.get(reverse('social_public_final_image', args=['token-invalido']))
        self.assertEqual(response.status_code, 404)

    def test_signed_url_anomina_nao_redireciona_para_login(self):
        content = self._content_ready()
        token = gerar_token_midia_temporaria(content)
        self.client.logout()
        response = self.client.get(reverse('social_public_final_image', args=[token]), follow=False)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(response.status_code, {301, 302})
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        b''.join(response.streaming_content)
        response.close()

    @override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com', INSTAGRAM_MEDIA_URL_TTL_SECONDS=3600)
    def test_signed_url_meta_user_agent_e_head(self):
        content = self._content_ready()
        token = gerar_token_midia_temporaria(content)
        path = reverse('social_public_final_image', args=[token])

        meta_response = self.client.get(
            path,
            HTTP_USER_AGENT='facebookexternalhit/1.1',
            follow=False,
        )
        self.assertEqual(meta_response.status_code, 200)
        self.assertEqual(meta_response['Content-Type'], 'image/jpeg')
        body = b''.join(meta_response.streaming_content)
        self.assertTrue(body.startswith(b'\xff\xd8\xff'))
        meta_response.close()

        head_response = self.client.head(path, follow=False)
        self.assertEqual(head_response.status_code, 200)
        self.assertEqual(head_response['Content-Type'], 'image/jpeg')
        head_response.close()

        signed_url = url_midia_temporaria(content)
        self.assertEqual(urllib.parse.urlparse(signed_url).netloc, 'dashboard-ambar.onrender.com')

    @override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_url_jpg_alternativa_preserva_assinatura(self):
        content = self._content_ready()
        url = url_midia_temporaria(content, com_extensao_jpg=True, legacy=True)
        resumo = resumir_image_url(url)

        self.assertTrue(url.startswith('https://dashboard-ambar.onrender.com/'))
        self.assertTrue(resumo['has_jpg'])
        self.assertEqual(resumo['path_structure'], '/social-media/public-jpg/[signed-token]/imagem.jpg')

    @override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com', INSTAGRAM_MEDIA_URL_TTL_SECONDS=3600)
    def test_meta_compat_url_curta_assinada_e_menor_que_legada(self):
        content = self._content_ready()
        signature = gerar_assinatura_midia_meta(content)
        validado = validar_assinatura_midia_meta(content.id, signature)
        meta_url = url_midia_meta_compat(content)
        legacy_url = url_midia_temporaria(content, com_extensao_jpg=True, legacy=True)
        resumo = resumir_image_url(meta_url)

        self.assertEqual(validado, content)
        self.assertIn(f'/social-media/ig/{content.id}/', meta_url)
        self.assertTrue(meta_url.endswith('.jpg'))
        self.assertLess(len(meta_url), len(legacy_url))
        self.assertEqual(resumo['path_structure'], f'/social-media/ig/{content.id}/[signed-token].jpg')

    @override_settings(INSTAGRAM_MEDIA_URL_TTL_SECONDS=-1)
    def test_meta_compat_ttl_expira(self):
        content = self._content_ready()
        signature = gerar_assinatura_midia_meta(content)
        with self.assertRaises(ValidationError):
            validar_assinatura_midia_meta(content.id, signature)

    def test_meta_compat_content_id_adulterado_e_recusado(self):
        content = self._content_ready()
        signature = gerar_assinatura_midia_meta(content)
        with self.assertRaises(ValidationError):
            validar_assinatura_midia_meta(content.id + 1, signature)

    @override_settings(INSTAGRAM_MEDIA_URL_TTL_SECONDS=3600)
    def test_meta_compat_serve_httpresponse_nao_streaming_com_bytes_identicos(self):
        content = self._content_ready()
        signature = gerar_assinatura_midia_meta(content)
        path = reverse('social_public_final_image_meta_compat', args=[content.id, signature])
        self.client.logout()

        with self.assertLogs('social_automation.views', level='INFO') as logs:
            response = self.client.get(path, HTTP_USER_AGENT='facebookexternalhit/1.1', follow=False)
        with content.final_image.storage.open(content.final_image.name, 'rb') as arquivo:
            storage_bytes = arquivo.read()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.streaming)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertEqual(response['Content-Length'], str(len(storage_bytes)))
        self.assertEqual(response.get('Content-Disposition', ''), '')
        self.assertNotIn('Content-Encoding', response)
        self.assertEqual(response.content, storage_bytes)
        self.assertEqual(sha256(response.content).hexdigest(), sha256(storage_bytes).hexdigest())
        self.assertTrue(response.content.startswith(b'\xff\xd8\xff'))
        self.assertNotIn(response.status_code, {301, 302})
        self.assertIn(f'signed_media_fetch content_id={content.id}', '\n'.join(logs.output))
        self.assertNotIn(signature, '\n'.join(logs.output))

        head_response = self.client.head(path, follow=False)
        self.assertEqual(head_response.status_code, 200)
        self.assertFalse(head_response.streaming)
        self.assertEqual(head_response['Content-Type'], 'image/jpeg')
        self.assertEqual(head_response['Content-Length'], str(len(storage_bytes)))
        self.assertEqual(head_response.content, b'')

    def test_auditoria_confirma_jpeg_real(self):
        content = self._content_ready()
        auditoria = auditar_imagem_final(content)

        self.assertEqual(auditoria['format'], 'JPEG')
        self.assertEqual(auditoria['extension'], '.jpg')
        self.assertEqual(auditoria['mode'], 'RGB')
        self.assertEqual((auditoria['width'], auditoria['height']), (1080, 1080))
        self.assertTrue(auditoria['jpeg_signature'])
        self.assertGreater(auditoria['bytes'], 0)

    @override_settings(INSTAGRAM_MEDIA_URL_TTL_SECONDS=-1)
    def test_signed_url_expirada_nao_acessa(self):
        content = self._content_ready()
        token = gerar_token_midia_temporaria(content)
        with self.assertRaises(ValidationError):
            validar_token_midia_temporaria(token)

    def test_assinatura_vincula_content_e_arquivo_atual(self):
        content = self._content_ready()
        token = gerar_token_midia_temporaria(content)
        content.final_image.name = 'social/outro/posts/outro.jpg'
        content.save(update_fields=['final_image', 'updated_at'])

        with self.assertRaises(ValidationError):
            validar_token_midia_temporaria(token)

    @override_settings(
        INSTAGRAM_ACCESS_TOKEN='token-teste',
        INSTAGRAM_USER_ID='178000000000',
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    )
    def test_publicacao_mockada_marca_publicado(self):
        content = self._content_ready()
        with mock.patch('social_automation.instagram.obter_conta_instagram', return_value={'username': 'lailapistola'}), mock.patch(
            'social_automation.instagram.criar_container_imagem',
            return_value='container-1',
        ), mock.patch('social_automation.instagram.aguardar_container_pronto', return_value={'status_code': 'FINISHED'}), mock.patch(
            'social_automation.instagram.publicar_container',
            return_value='media-1',
        ), mock.patch('social_automation.instagram.obter_midia_publicada', return_value={'id': 'media-1', 'permalink': 'https://instagram.com/p/teste/'}):
            publicar_conteudo_instagram(content, self.staff)

        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.PUBLICADO)
        self.assertEqual(content.external_post_id, 'media-1')
        self.assertEqual(content.external_permalink, 'https://instagram.com/p/teste/')
        self.assertIsNotNone(content.published_at)
        self.assertTrue(content.events.filter(acao=PUBLICADO_INSTAGRAM).exists())

    @override_settings(
        INSTAGRAM_ACCESS_TOKEN='token-teste',
        INSTAGRAM_USER_ID='178000000000',
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
        INSTAGRAM_MEDIA_URL_TTL_SECONDS=3600,
    )
    def test_publicacao_real_usa_url_meta_compat(self):
        content = self._content_ready()
        captured = {}

        def fake_container(image_url, caption):
            captured['image_url'] = image_url
            captured['caption'] = caption
            return 'container-1'

        with mock.patch('social_automation.instagram.obter_conta_instagram', return_value={'username': 'lailapistola'}), mock.patch(
            'social_automation.instagram.criar_container_imagem',
            side_effect=fake_container,
        ), mock.patch('social_automation.instagram.aguardar_container_pronto', return_value={'status_code': 'FINISHED'}), mock.patch(
            'social_automation.instagram.publicar_container',
            return_value='media-1',
        ), mock.patch('social_automation.instagram.obter_midia_publicada', return_value={'id': 'media-1'}):
            with self.assertLogs('social_automation.instagram', level='INFO') as logs:
                publicar_conteudo_instagram(content, self.staff)

        self.assertIn(f'/social-media/ig/{content.id}/', captured['image_url'])
        self.assertTrue(captured['image_url'].endswith('.jpg'))
        self.assertNotIn('/social-media/public', captured['image_url'])
        self.assertIn(f'publication_start content_id={content.id}', '\n'.join(logs.output))

    @override_settings(INSTAGRAM_ACCESS_TOKEN='token-teste', INSTAGRAM_USER_ID='178000000000')
    def test_criacao_container_envia_image_url_sem_media_type_video(self):
        captured = {}

        def fake_request(method, path, params=None):
            captured['method'] = method
            captured['path'] = path
            captured['params'] = params
            return {'id': 'container-1'}

        with mock.patch('social_automation.instagram._request', side_effect=fake_request):
            with self.assertLogs('social_automation.instagram', level='INFO') as logs:
                container_id = criar_container_imagem('https://dashboard-ambar.onrender.com/social-media/public/token/', 'Legenda')

        self.assertEqual(container_id, 'container-1')
        self.assertEqual(captured['method'], 'POST')
        self.assertIn('/media', captured['path'])
        self.assertEqual(captured['params']['image_url'], 'https://dashboard-ambar.onrender.com/social-media/public/token/')
        self.assertEqual(captured['params']['caption'], 'Legenda')
        self.assertNotIn('media_type', captured['params'])
        self.assertNotIn('caption', captured['params']['image_url'])
        self.assertNotIn('%253A', captured['params']['image_url'])
        texto_logs = '\n'.join(logs.output)
        self.assertIn('media_container_request_start', texto_logs)
        self.assertIn('media_container_request_end', texto_logs)
        self.assertNotIn('token-teste', texto_logs)

    def test_render_yaml_configura_gunicorn_gthread_para_self_fetch(self):
        render_yaml = Path('render.yaml').read_text(encoding='utf-8')
        self.assertIn('gunicorn config.wsgi:application', render_yaml)
        self.assertIn('--worker-class gthread', render_yaml)
        self.assertIn('--workers 1', render_yaml)
        self.assertIn('--threads 4', render_yaml)
        self.assertIn('--timeout 60', render_yaml)

    def test_erro_meta_completo_e_sanitizado(self):
        payload = {
            'error': {
                'message': 'Only photo or video can be accepted as media type. https://dashboard-ambar.onrender.com/social-media/public/token-secreto/',
                'type': 'OAuthException',
                'code': 9004,
                'error_subcode': 2207052,
                'is_transient': False,
                'error_user_title': 'Media invalida',
                'error_user_msg': 'Falhou em https://dashboard-ambar.onrender.com/social-media/public/token-secreto/',
                'fbtrace_id': 'ABC123',
            }
        }

        class FakeHTTPError(Exception):
            pass

        error = urllib.error.HTTPError(
            url='https://graph.instagram.com/v23.0/178/media',
            code=400,
            msg='Bad Request',
            hdrs={},
            fp=BytesIO(__import__('json').dumps(payload).encode('utf-8')),
        )
        with override_settings(INSTAGRAM_ACCESS_TOKEN='segredo'), mock.patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(InstagramAPIError) as ctx:
                criar_container_imagem('https://dashboard-ambar.onrender.com/social-media/public/token-secreto/', '')

        exc = ctx.exception
        self.assertEqual(exc.code, 9004)
        self.assertEqual(exc.subcode, 2207052)
        self.assertEqual(exc.error_type, 'OAuthException')
        self.assertFalse(exc.is_transient)
        self.assertEqual(exc.fbtrace_id, 'ABC123')
        self.assertNotIn('token-secreto', str(exc))
        self.assertNotIn('token-secreto', exc.user_msg)

    @override_settings(INSTAGRAM_ACCESS_TOKEN='token-teste', INSTAGRAM_USER_ID='178000000000', PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_diagnostico_container_nao_chama_media_publish(self):
        content = self._content_ready()
        output = StringIO()
        with mock.patch('social_automation.instagram._request', return_value={'id': 'container-1'}) as request_mock, mock.patch(
            'social_automation.instagram.publicar_container'
        ) as publish_mock:
            call_command('diagnosticar_container_instagram', str(content.id), stdout=output)

        texto = output.getvalue()
        self.assertIn('media_publish: NAO executado', texto)
        self.assertIn('ROTA_ANTIGA', texto)
        self.assertIn('META_COMPAT_SEM_CAPTION', texto)
        self.assertIn('META_COMPAT_COM_CAPTION', texto)
        self.assertIn('image_url_sha256=', texto)
        self.assertEqual(request_mock.call_count, 3)
        publish_mock.assert_not_called()

    @override_settings(
        INSTAGRAM_ACCESS_TOKEN='token-teste',
        INSTAGRAM_USER_ID='178000000000',
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    )
    def test_falha_container_vai_para_erro(self):
        content = self._content_ready()
        with mock.patch('social_automation.instagram.obter_conta_instagram', return_value={'username': 'lailapistola'}), mock.patch(
            'social_automation.instagram.criar_container_imagem',
            side_effect=InstagramAPIError('Container recusado', status=400, code=10),
        ):
            with self.assertRaises(InstagramAPIError):
                publicar_conteudo_instagram(content, self.staff)

        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.ERRO)
        self.assertIn('Container recusado', content.erro)

    @override_settings(
        INSTAGRAM_ACCESS_TOKEN='token-teste',
        INSTAGRAM_USER_ID='178000000000',
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    )
    def test_falha_media_publish_vai_para_erro(self):
        content = self._content_ready()
        with mock.patch('social_automation.instagram.obter_conta_instagram', return_value={'username': 'lailapistola'}), mock.patch(
            'social_automation.instagram.criar_container_imagem',
            return_value='container-1',
        ), mock.patch('social_automation.instagram.aguardar_container_pronto', return_value={'status_code': 'FINISHED'}), mock.patch(
            'social_automation.instagram.publicar_container',
            side_effect=InstagramAPIError('Publish recusado', status=400, code=20),
        ):
            with self.assertRaises(InstagramAPIError):
                publicar_conteudo_instagram(content, self.staff)

        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.ERRO)
        self.assertFalse(content.external_post_id)

    @override_settings(INSTAGRAM_ACCESS_TOKEN='', INSTAGRAM_USER_ID='', PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_configuracao_ausente_nao_gera_500(self):
        content = self._content_ready()
        response = self.client.post(reverse('social_automation:content_publish_instagram', args=[content.id]))

        self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.ERRO)
        self.assertIn('INSTAGRAM_ACCESS_TOKEN', content.erro)

    @override_settings(
        INSTAGRAM_ACCESS_TOKEN='token-teste',
        INSTAGRAM_USER_ID='178000000000',
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    )
    def test_status_nao_aprovado_nao_publica(self):
        for status in [SocialContent.Status.RASCUNHO, SocialContent.Status.REJEITADO, SocialContent.Status.PUBLICADO]:
            content = self._content_ready(status=status)
            with self.assertRaisesMessage(Exception, 'Somente conteudos aprovados'):
                publicar_conteudo_instagram(content, self.staff)


class SocialAutomationMediaRootTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-media-root-social', password='senha', is_staff=True)
        self.client.force_login(self.staff)
        self.profile = SocialProfile.objects.create(nome='Perfil Media', username='@lailapistola', horarios_publicacao=['12:00'])

    def _content_ready(self, status=SocialContent.Status.APROVADO, username='@lailapistola'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        media_override = override_settings(MEDIA_ROOT=tmp.name)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.profile.username = username
        self.profile.save(update_fields=['username', 'updated_at'])
        image = SocialBaseImage.objects.create(
            profile=self.profile,
            nome='Base Instagram',
            tags='laila',
            arquivo=imagem_social('instagram-base.jpg'),
        )
        content = SocialContent.objects.create(
            profile=self.profile,
            base_image=image,
            frase='Segunda-feira chegou com personalidade',
            legenda='Legenda curta',
            hashtags='#laila #humor',
            status=status,
        )
        renderizar_conteudo_social(content)
        content.refresh_from_db()
        return content

    def test_media_root_local_e_override_por_env(self):
        from config.settings import base

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(base.media_root_path(), base.BASE_DIR / 'media')

        with mock.patch.dict(os.environ, {'MEDIA_ROOT': '/var/data/media'}, clear=True):
            self.assertEqual(base.media_root_path(), Path('/var/data/media'))

        with mock.patch.dict(os.environ, {'DJANGO_MEDIA_ROOT': '/legacy/media'}, clear=True):
            self.assertEqual(base.media_root_path(), Path('/legacy/media'))

        with mock.patch.dict(os.environ, {'MEDIA_ROOT': '/var/data/media', 'DJANGO_MEDIA_ROOT': '/legacy/media'}, clear=True):
            self.assertEqual(base.media_root_path(), Path('/var/data/media'))

    def test_uploads_sociais_usam_media_root_configurado_e_signed_url_funciona(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root, INSTAGRAM_MEDIA_URL_TTL_SECONDS=3600):
            response = self.client.post(
                reverse('social_automation:image_create', args=[self.profile.id]),
                {
                    'nome': 'Base persistente',
                    'tags': 'laila',
                    'text_position': SocialBaseImage.TextPosition.AUTO,
                    'ativa': 'on',
                    'arquivo': imagem_social('base-persistente.jpg'),
                },
            )
            self.assertRedirects(response, reverse('social_automation:image_list', args=[self.profile.id]))
            image = SocialBaseImage.objects.get(nome='Base persistente')
            self.assertTrue(Path(image.arquivo.path).is_relative_to(Path(media_root)))

            content = SocialContent.objects.create(
                profile=self.profile,
                base_image=image,
                frase='Card final salvo no storage configurado',
                status=SocialContent.Status.APROVADO,
            )
            renderizar_conteudo_social(content)
            content.refresh_from_db()
            self.assertTrue(Path(content.final_image.path).is_relative_to(Path(media_root)))

            token = gerar_token_midia_temporaria(content)
            public_response = self.client.get(reverse('social_public_final_image', args=[token]))
            self.assertEqual(public_response.status_code, 200)
            self.assertEqual(public_response['Content-Type'], 'image/jpeg')
            b''.join(public_response.streaming_content)
            public_response.close()

    @override_settings(
        INSTAGRAM_ACCESS_TOKEN='token-teste',
        INSTAGRAM_USER_ID='178000000000',
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    )
    def test_username_de_outro_perfil_bloqueia_publicacao(self):
        content = self._content_ready(username='@outroperfil')
        with self.assertRaisesMessage(Exception, 'outro perfil social'):
            publicar_conteudo_instagram(content, self.staff)

    @override_settings(
        INSTAGRAM_ACCESS_TOKEN='token-teste',
        INSTAGRAM_USER_ID='178000000000',
        INSTAGRAM_EXPECTED_USERNAME='lailapistola',
        PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    )
    def test_duplo_clique_nao_publica_duas_vezes(self):
        content = self._content_ready()
        with mock.patch('social_automation.instagram.obter_conta_instagram', return_value={'username': 'lailapistola'}), mock.patch(
            'social_automation.instagram.criar_container_imagem',
            return_value='container-1',
        ), mock.patch('social_automation.instagram.aguardar_container_pronto', return_value={'status_code': 'FINISHED'}), mock.patch(
            'social_automation.instagram.publicar_container',
            return_value='media-1',
        ), mock.patch('social_automation.instagram.obter_midia_publicada', return_value={'id': 'media-1'}):
            publicar_conteudo_instagram(content, self.staff)

            with self.assertRaisesMessage(Exception, 'Somente conteudos aprovados'):
                publicar_conteudo_instagram(content, self.staff)
