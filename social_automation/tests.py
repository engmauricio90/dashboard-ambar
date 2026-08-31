from datetime import timedelta
import base64
from io import BytesIO, StringIO
from hashlib import sha256
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.error
import urllib.parse
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw

from empresas.models import Empresa, UsuarioEmpresa

from .models import (
    SocialAIUsage,
    SocialBaseImage,
    SocialBaseImageProtectedRegion,
    SocialCarouselSlide,
    SocialCarouselTemplate,
    SocialCarouselTemplateVariant,
    SocialContent,
    SocialContentEvent,
    SocialInstagramConnection,
    SocialProfile,
    SocialVisualIdentity,
)
from .ai import GeneratedCarouselBlueprint, GeneratedCarouselSlide, GeneratedContent, OpenAIUnavailable
from .automation import executar_tick_social
from .container_versioning import (
    REEL_SHARE_TO_FEED,
    build_instagram_caption,
    calculate_instagram_carousel_slide_fingerprint,
    calculate_instagram_container_fingerprint,
    invalidate_instagram_container,
)
from .forms import SocialCarouselSlideFormSet
from .generation import GenerationResult, _image_contexts, gerar_lote_conteudos
from .image_selection import selecionar_imagem_base
from .image_generation import SocialImageGenerationDisabled, SocialImagePrompt, build_image_generation_prompt, generate_social_image, image_generation_available
from .image_analysis import ImageAnalysisResult, persist_image_analysis
from .media_resolver import STATUS_FULL_TEXT, STATUS_NEEDS_GENERATION, STATUS_SELECTED, resolve_slide_media
from .instagram import (
    InstagramAPIError,
    InstagramContainerPending,
    InstagramPublishError,
    MEDIA_SIGNING_SALT,
    PUBLICADO_INSTAGRAM,
    auditar_imagem_final,
    auditar_imagem_slide_carrossel,
    criar_container_reel,
    criar_container_imagem,
    gerar_assinatura_carousel_slide_meta,
    display_instagram_account_type,
    gerar_assinatura_midia_meta,
    gerar_token_midia_temporaria,
    is_publishable_instagram_account_type,
    montar_caption,
    normalize_instagram_account_type,
    publicar_conteudo_instagram,
    resumir_image_url,
    resumir_video_url,
    url_midia_meta_compat,
    url_video_meta_compat,
    url_carousel_slide_meta_compat,
    url_midia_temporaria,
    validar_assinatura_carousel_slide_meta,
    validar_assinatura_video_meta,
    validar_assinatura_midia_meta,
    validar_token_midia_temporaria,
)
from .rendering import CANVAS_SIZE, REEL_CANVAS_SIZE, SocialRenderError, renderizar_conteudo_social
from .rendering import _draw_text_box, _layout_text, _reel_text_boxes, _region, _text_boxes
from .scheduler import build_daily_media_plan, estoque_alvo_profile, estoque_minimo_profile, estoque_pronto, estoque_pronto_por_tipo, media_type_for_slot, plano_geracao_por_deficit, preencher_agenda
from .token_crypto import InstagramTokenEncryptionError, decrypt_instagram_token, encrypt_instagram_token
from .video_rendering import (
    SocialVideoRenderError,
    _ffmpeg_command,
    _validate_output_file,
    auditar_video_reel,
    renderizar_reel_social,
)
from .visual_composer import compose_carousel_slide, protected_regions_for_image, visual_identity_for_profile


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


def video_mp4_teste(nome='reel.mp4', tamanho=2048):
    payload = b'\x00\x00\x00\x18ftypmp42' + (b'\x00' * max(tamanho - 12, 0))
    return SimpleUploadedFile(nome, payload, content_type='video/mp4')


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

    def test_formulario_imagem_base_separa_layout_foto_e_reel(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse('social_automation:image_create', args=[self.profile.id]),
                {
                    'nome': 'Laila vertical',
                    'tags': 'laila',
                    'text_position': SocialBaseImage.TextPosition.RIGHT,
                    'text_box_preset': SocialBaseImage.TextBoxPreset.BOTTOM_RIGHT,
                    'primary_text_box_x': '50',
                    'primary_text_box_y': '60',
                    'primary_text_box_width': '43',
                    'primary_text_box_height': '32',
                    'reel_text_position': SocialBaseImage.TextPosition.AUTO_SMART,
                    'reel_text_box_preset': SocialBaseImage.ReelTextBoxPreset.BOTTOM_LEFT,
                    'reel_primary_text_box_x': '7',
                    'reel_primary_text_box_y': '66',
                    'reel_primary_text_box_width': '44',
                    'reel_primary_text_box_height': '20',
                    'ativa': 'on',
                    'arquivo': imagem_social('laila-vertical.jpg'),
                },
            )

            image = SocialBaseImage.objects.get(nome='Laila vertical')
            self.assertRedirects(response, reverse('social_automation:image_list', args=[self.profile.id]))
            self.assertTrue(image.primary_text_box_configured)
            self.assertTrue(image.reel_primary_text_box_configured)
            self.assertEqual(float(image.primary_text_box_y), 60)
            self.assertEqual(float(image.reel_primary_text_box_y), 66)

            edit = self.client.get(reverse('social_automation:image_update', args=[image.id]))
            self.assertContains(edit, 'Layout da foto')
            self.assertContains(edit, 'Layout do Reel')
            self.assertContains(edit, 'social-preview-photo')
            self.assertContains(edit, 'social-preview-reel')
            self.assertContains(edit, 'social-reel-safearea')

            listing = self.client.get(reverse('social_automation:image_list', args=[self.profile.id]))
            self.assertContains(listing, '<strong>Foto:</strong>', html=True)
            self.assertContains(listing, '<strong>Reel:</strong>', html=True)

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

    def test_reel_usa_caixa_vertical_independente_da_foto(self):
        image = self._image(SocialBaseImage.TextPosition.AUTO_SMART)
        image.primary_text_box_x = 50
        image.primary_text_box_y = 60
        image.primary_text_box_width = 40
        image.primary_text_box_height = 20
        image.reel_primary_text_box_x = 7
        image.reel_primary_text_box_y = 66
        image.reel_primary_text_box_width = 44
        image.reel_primary_text_box_height = 20
        image.reel_text_align_horizontal = SocialBaseImage.TextAlignHorizontal.LEFT
        image.save()

        photo_box = _text_boxes(image)[0]
        reel_box = _reel_text_boxes(image)[0]

        self.assertEqual(photo_box['source_canvas'], CANVAS_SIZE)
        self.assertEqual(reel_box['source_canvas'], REEL_CANVAS_SIZE)
        self.assertEqual(photo_box['region'], (540, 648, 432, 216))
        self.assertEqual(reel_box['region'], (76, 1267, 475, 384))
        self.assertEqual(reel_box['align_horizontal'], 'left')

    def test_reel_sem_layout_configurado_usa_fallback_da_foto(self):
        image = self._image(SocialBaseImage.TextPosition.LEFT)

        reel_box = _reel_text_boxes(image)[0]
        legacy, _align = _region(SocialBaseImage.TextPosition.LEFT)

        self.assertEqual(reel_box['name'], 'legacy')
        self.assertEqual(reel_box['region'], legacy)
        self.assertEqual(reel_box['source_canvas'], CANVAS_SIZE)

    def test_form_salva_preset_reel_sem_alterar_preset_foto(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse('social_automation:image_create', args=[self.profile.id]),
                {
                    'nome': 'Laila reel bottom',
                    'tags': 'laila',
                    'text_position': SocialBaseImage.TextPosition.LEFT,
                    'reel_text_position': SocialBaseImage.TextPosition.AUTO_SMART,
                    'reel_text_box_preset': SocialBaseImage.ReelTextBoxPreset.BOTTOM_CENTER,
                    'reel_text_align_horizontal': SocialBaseImage.TextAlignHorizontal.CENTER,
                    'reel_text_align_vertical': SocialBaseImage.TextAlignVertical.MIDDLE,
                    'reel_secondary_text_align_horizontal': SocialBaseImage.TextAlignHorizontal.CENTER,
                    'reel_secondary_text_align_vertical': SocialBaseImage.TextAlignVertical.MIDDLE,
                    'ativa': 'on',
                    'arquivo': imagem_social('laila-reel-bottom.jpg'),
                },
            )

            self.assertRedirects(response, reverse('social_automation:image_list', args=[self.profile.id]))
            image = SocialBaseImage.objects.get(nome='Laila reel bottom')
            self.assertFalse(image.primary_text_box_configured)
            self.assertTrue(image.reel_primary_text_box_configured)
            self.assertEqual(float(image.reel_primary_text_box_x), 15)
            self.assertEqual(float(image.reel_primary_text_box_width), 70)

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

    def test_contexto_de_ia_para_reel_usa_layout_vertical_e_ate_tres_linhas(self):
        image = self._image(SocialBaseImage.TextPosition.AUTO_SMART)
        image.reel_primary_text_box_x = 10
        image.reel_primary_text_box_y = 60
        image.reel_primary_text_box_width = 76
        image.reel_primary_text_box_height = 30
        image.save()

        contexts = _image_contexts(self.profile, SocialContent.MediaType.REEL)

        self.assertEqual(contexts[0]['tipo_midia'], SocialContent.MediaType.REEL)
        self.assertEqual(contexts[0]['area_disponivel_percentual'], 22.81)
        self.assertIn('ate 3 linhas', contexts[0]['tamanho_recomendado_frase'])


@override_settings(
    INSTAGRAM_ACCESS_TOKEN='token-teste',
    INSTAGRAM_USER_ID='178000000000',
    INSTAGRAM_EXPECTED_USERNAME='lailapistola',
    PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
)
class SocialAutomationReelTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-reel-social', password='senha', is_staff=True)
        self.client.force_login(self.staff)
        self.profile = SocialProfile.objects.create(
            nome='Laila',
            username='@lailapistola',
            posts_por_dia=20,
            reels_por_dia=5,
            horarios_publicacao=[f'{hour:02d}:00' for hour in range(20)],
        )

    def _image(self):
        return SocialBaseImage.objects.create(
            profile=self.profile,
            nome='Base Reel',
            tags='laila',
            text_position=SocialBaseImage.TextPosition.AUTO_SMART,
            primary_text_box_x=8,
            primary_text_box_y=58,
            primary_text_box_width=42,
            primary_text_box_height=24,
            arquivo=imagem_social('base-reel.jpg', tamanho=(1400, 1100), cor='plum'),
        )

    def _content(self, media_type=SocialContent.MediaType.REEL):
        return SocialContent.objects.create(
            profile=self.profile,
            base_image=self._image(),
            media_type=media_type,
            frase='Segunda-feira veio sem pedir licenca',
            legenda='Legenda',
            hashtags='#laila',
        )

    def _ready_content_for_schedule(self, media_type, index, scheduled_at=None, status=SocialContent.Status.APROVADO):
        content = SocialContent.objects.create(
            profile=self.profile,
            base_image=self._image(),
            media_type=media_type,
            frase=f'Conteudo {media_type} {index}',
            legenda='Legenda',
            hashtags='#laila',
            status=status,
            scheduled_at=scheduled_at,
        )
        if media_type == SocialContent.MediaType.REEL:
            content.final_video = video_mp4_teste(f'reel-{index}.mp4')
        else:
            content.final_image = imagem_social(f'foto-{index}.jpg')
        content.save(update_fields=['final_image', 'final_video'])
        return content

    def test_media_type_image_default_e_reels_por_dia_valido(self):
        content = SocialContent.objects.create(profile=self.profile, frase='Foto padrao')
        self.assertEqual(content.media_type, SocialContent.MediaType.IMAGE)
        self.assertEqual(self.profile.fotos_por_dia, 15)

        self.profile.reels_por_dia = 21
        with self.assertRaises(ValidationError):
            self.profile.full_clean()

    def test_scheduler_distribui_cinco_reels_em_vinte_slots(self):
        sequence = [media_type_for_slot(index, 20, 5) for index in range(20)]
        reel_indexes = [index for index, media_type in enumerate(sequence) if media_type == SocialContent.MediaType.REEL]

        self.assertEqual(len(reel_indexes), 5)
        self.assertEqual(reel_indexes, [3, 7, 11, 15, 19])

    def test_plano_diario_vinte_posts_seis_reels_distribuidos(self):
        sequence = build_daily_media_plan(20, 6)
        reel_indexes = [index for index, media_type in enumerate(sequence) if media_type == SocialContent.MediaType.REEL]

        self.assertEqual(len(sequence), 20)
        self.assertEqual(sequence.count(SocialContent.MediaType.IMAGE), 14)
        self.assertEqual(sequence.count(SocialContent.MediaType.REEL), 6)
        self.assertEqual(reel_indexes, [3, 6, 9, 13, 16, 19])
        for previous, current in zip(sequence, sequence[1:]):
            self.assertFalse(previous == current == SocialContent.MediaType.REEL)

    def test_plano_diario_casos_importantes(self):
        cases = [
            (20, 0, 20, 0),
            (20, 5, 15, 5),
            (20, 10, 10, 10),
            (10, 3, 7, 3),
            (5, 1, 4, 1),
            (20, 20, 0, 20),
        ]
        for posts, reels, expected_images, expected_reels in cases:
            with self.subTest(posts=posts, reels=reels):
                sequence = build_daily_media_plan(posts, reels)
                self.assertEqual(len(sequence), posts)
                self.assertEqual(sequence.count(SocialContent.MediaType.IMAGE), expected_images)
                self.assertEqual(sequence.count(SocialContent.MediaType.REEL), expected_reels)
                self.assertEqual(sequence, build_daily_media_plan(posts, reels))

    def test_scheduler_escolhe_tipo_do_slot_sem_fallback_silencioso(self):
        self.profile.reels_por_dia = 6
        self.profile.save(update_fields=['reels_por_dia'])
        now = timezone.datetime(2025, 12, 31, 23, 59, tzinfo=ZoneInfo('America/Sao_Paulo')).astimezone(timezone.get_current_timezone())
        for index in range(14):
            self._ready_content_for_schedule(SocialContent.MediaType.IMAGE, index)
        result = preencher_agenda(self.profile, now=now, days=2)

        agendados = list(self.profile.contents.filter(status=SocialContent.Status.AGENDADO).order_by('scheduled_at'))
        self.assertEqual(result.scheduled, 14)
        self.assertGreaterEqual(result.skipped, 6)
        self.assertTrue(all(content.media_type == SocialContent.MediaType.IMAGE for content in agendados))
        self.assertEqual(
            [content.scheduled_at.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%H:%M') for content in agendados],
            ['00:00', '01:00', '02:00', '04:00', '05:00', '07:00', '08:00', '10:00', '11:00', '12:00', '14:00', '15:00', '17:00', '18:00'],
        )

    def test_scheduler_nao_preenche_foto_com_reel_quando_falta_image(self):
        self.profile.reels_por_dia = 6
        self.profile.save(update_fields=['reels_por_dia'])
        now = timezone.datetime(2025, 12, 31, 23, 59, tzinfo=ZoneInfo('America/Sao_Paulo')).astimezone(timezone.get_current_timezone())
        for index in range(6):
            self._ready_content_for_schedule(SocialContent.MediaType.REEL, index)
        result = preencher_agenda(self.profile, now=now, days=2)

        agendados = list(self.profile.contents.filter(status=SocialContent.Status.AGENDADO).order_by('scheduled_at'))
        self.assertEqual(result.scheduled, 6)
        self.assertGreaterEqual(result.skipped, 14)
        self.assertTrue(all(content.media_type == SocialContent.MediaType.REEL for content in agendados))
        self.assertEqual(
            [content.scheduled_at.astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%H:%M') for content in agendados],
            ['03:00', '06:00', '09:00', '13:00', '16:00', '19:00'],
        )

    def test_scheduler_respeita_dia_parcialmente_agendado_por_posicao(self):
        self.profile.reels_por_dia = 6
        self.profile.save(update_fields=['reels_por_dia'])
        zone = ZoneInfo('America/Sao_Paulo')
        now = timezone.datetime(2025, 12, 31, 23, 59, tzinfo=zone).astimezone(timezone.get_current_timezone())
        existentes = []
        for index in range(8):
            scheduled_at = timezone.datetime(2026, 1, 1, index, 0, tzinfo=zone).astimezone(timezone.get_current_timezone())
            existentes.append(
                self._ready_content_for_schedule(SocialContent.MediaType.IMAGE, index, scheduled_at=scheduled_at, status=SocialContent.Status.AGENDADO).id
            )
        for index in range(8):
            self._ready_content_for_schedule(SocialContent.MediaType.IMAGE, 100 + index)
        for index in range(4):
            self._ready_content_for_schedule(SocialContent.MediaType.REEL, 200 + index)

        result = preencher_agenda(self.profile, now=now, days=2)
        novos = self.profile.contents.filter(status=SocialContent.Status.AGENDADO).exclude(id__in=existentes).order_by('scheduled_at')
        self.assertEqual(result.scheduled, 12)
        self.assertEqual(
            [(content.scheduled_at.astimezone(zone).strftime('%H:%M'), content.media_type) for content in novos],
            [
                ('08:00', SocialContent.MediaType.IMAGE),
                ('09:00', SocialContent.MediaType.REEL),
                ('10:00', SocialContent.MediaType.IMAGE),
                ('11:00', SocialContent.MediaType.IMAGE),
                ('12:00', SocialContent.MediaType.IMAGE),
                ('13:00', SocialContent.MediaType.REEL),
                ('14:00', SocialContent.MediaType.IMAGE),
                ('15:00', SocialContent.MediaType.IMAGE),
                ('16:00', SocialContent.MediaType.REEL),
                ('17:00', SocialContent.MediaType.IMAGE),
                ('18:00', SocialContent.MediaType.IMAGE),
                ('19:00', SocialContent.MediaType.REEL),
            ],
        )

    def test_agendamentos_existentes_e_alteracao_manual_nao_sao_revertidos(self):
        self.profile.reels_por_dia = 6
        self.profile.save(update_fields=['reels_por_dia'])
        zone = ZoneInfo('America/Sao_Paulo')
        now = timezone.datetime(2025, 12, 31, 23, 59, tzinfo=zone).astimezone(timezone.get_current_timezone())
        manual_slot = timezone.datetime(2026, 1, 1, 3, 0, tzinfo=zone).astimezone(timezone.get_current_timezone())
        manual = self._ready_content_for_schedule(SocialContent.MediaType.IMAGE, 1, scheduled_at=manual_slot, status=SocialContent.Status.AGENDADO)
        for index in range(4):
            self._ready_content_for_schedule(SocialContent.MediaType.REEL, index)

        preencher_agenda(self.profile, now=now, days=2)

        manual.refresh_from_db()
        self.assertEqual(manual.media_type, SocialContent.MediaType.IMAGE)
        self.assertEqual(manual.scheduled_at, manual_slot)

    def test_perfis_diferentes_possuem_planos_independentes(self):
        outro = SocialProfile.objects.create(
            nome='Perfil menor',
            username='perfil_menor',
            posts_por_dia=10,
            reels_por_dia=2,
            horarios_publicacao=[f'{hour:02d}:30' for hour in range(10)],
        )
        self.assertEqual(build_daily_media_plan(self.profile.posts_por_dia, 6).count(SocialContent.MediaType.REEL), 6)
        self.assertEqual(build_daily_media_plan(outro.posts_por_dia, outro.reels_por_dia).count(SocialContent.MediaType.REEL), 2)

    def test_diagnostico_mix_diario_lista_planejado_e_agendado(self):
        self.profile.reels_por_dia = 6
        self.profile.save(update_fields=['reels_por_dia'])
        zone = ZoneInfo('America/Sao_Paulo')
        scheduled_at = timezone.datetime(2026, 8, 29, 3, 0, tzinfo=zone).astimezone(timezone.get_current_timezone())
        self._ready_content_for_schedule(SocialContent.MediaType.REEL, 1, scheduled_at=scheduled_at, status=SocialContent.Status.AGENDADO)
        output = StringIO()

        call_command('diagnosticar_mix_diario', 'lailapistola', '2026-08-29', stdout=output)

        texto = output.getvalue()
        self.assertIn('Fotos planejadas: 14', texto)
        self.assertIn('Reels planejados: 6', texto)
        self.assertIn('03:00 REEL', texto)
        self.assertIn('03:00 REEL #', texto)

    def test_estoque_separado_e_deficit_prioriza_reel(self):
        image = self._image()
        for index in range(44):
            SocialContent.objects.create(
                profile=self.profile,
                base_image=image,
                media_type=SocialContent.MediaType.IMAGE,
                status=SocialContent.Status.APROVADO,
                final_image=imagem_social(f'foto-{index}.jpg'),
            )

        estoque = estoque_pronto_por_tipo(self.profile)
        plan = plano_geracao_por_deficit(self.profile, 60, 5)

        self.assertEqual(estoque[SocialContent.MediaType.IMAGE], 44)
        self.assertEqual(estoque[SocialContent.MediaType.REEL], 0)
        self.assertEqual(len(plan), 5)
        self.assertEqual(plan.count(SocialContent.MediaType.REEL), 5)

    def test_video_url_assinada_entrega_mp4_com_content_length(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content()
            content.final_video = video_mp4_teste()
            content.save(update_fields=['final_video'])
            signature = url_video_meta_compat(content).split('/')[-1].removesuffix('.mp4')
            expected_size = content.final_video.size

            validado = validar_assinatura_video_meta(content.id, signature)
            response = self.client.head(reverse('social_public_final_video_meta_compat', args=[content.id, signature]))

        self.assertEqual(validado.id, content.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'video/mp4')
        self.assertEqual(response['Content-Length'], str(expected_size))

    @override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_container_reel_usa_payload_oficial(self):
        captured = {}

        def fake_request(method, path, params=None):
            captured['method'] = method
            captured['path'] = path
            captured['params'] = params
            return {'id': 'container-reel-1'}

        with mock.patch('social_automation.instagram._request', side_effect=fake_request):
            container_id = criar_container_reel('https://dashboard-ambar.onrender.com/social-media/ig-video/1/token.mp4', 'Legenda')

        self.assertEqual(container_id, 'container-reel-1')
        self.assertEqual(captured['params']['media_type'], 'REELS')
        self.assertEqual(captured['params']['share_to_feed'], 'true')
        self.assertIn('video_url', captured['params'])

    @override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_publicacao_reel_pendente_persiste_container_sem_publicar(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content()
            content.status = SocialContent.Status.APROVADO
            content.final_video = video_mp4_teste()
            content.save(update_fields=['status', 'final_video'])

            with mock.patch('social_automation.instagram.verificar_configuracao_instagram'), mock.patch(
                'social_automation.instagram.obter_conta_instagram',
                return_value={'username': 'lailapistola'},
            ), mock.patch('social_automation.instagram.criar_container_reel', return_value='container-123') as create_mock, mock.patch(
                'social_automation.instagram.status_container_pronto',
                return_value=False,
            ), mock.patch('social_automation.instagram.publicar_container') as publish_mock:
                with self.assertRaises(InstagramContainerPending):
                    __import__('social_automation.instagram').instagram.publicar_conteudo_instagram(content)

            content.refresh_from_db()
            self.assertEqual(content.instagram_container_id, 'container-123')
            self.assertTrue(content.instagram_container_fingerprint)
            self.assertEqual(content.status, SocialContent.Status.AGENDADO)
            create_mock.assert_called_once()
            publish_mock.assert_not_called()

    @override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_publicacao_reel_reusa_container_existente(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content()
            content.status = SocialContent.Status.APROVADO
            content.instagram_container_id = 'container-existente'
            content.final_video = video_mp4_teste()
            content.save(update_fields=['status', 'instagram_container_id', 'final_video'])
            content.instagram_container_fingerprint = calculate_instagram_container_fingerprint(content)
            content.save(update_fields=['instagram_container_fingerprint'])

            with mock.patch('social_automation.instagram.verificar_configuracao_instagram'), mock.patch(
                'social_automation.instagram.obter_conta_instagram',
                return_value={'username': 'lailapistola'},
            ), mock.patch('social_automation.instagram.criar_container_reel') as create_mock, mock.patch(
                'social_automation.instagram.status_container_pronto',
                return_value=True,
            ), mock.patch('social_automation.instagram.publicar_container', return_value='media-1'), mock.patch(
                'social_automation.instagram.obter_midia_publicada',
                return_value={'id': 'media-1', 'permalink': 'https://instagram.com/reel/1'},
            ):
                __import__('social_automation.instagram').instagram.publicar_conteudo_instagram(content)

            content.refresh_from_db()
            self.assertEqual(content.status, SocialContent.Status.PUBLICADO)
            self.assertEqual(content.external_post_id, 'media-1')
            create_mock.assert_not_called()

    @override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_publicacao_reel_invalida_container_stale_por_nova_legenda(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content()
            content.status = SocialContent.Status.APROVADO
            content.instagram_container_id = 'container-antigo'
            content.final_video = video_mp4_teste()
            content.save(update_fields=['status', 'instagram_container_id', 'final_video'])
            content.instagram_container_fingerprint = calculate_instagram_container_fingerprint(content)
            content.legenda = 'Legenda nova'
            content.save(update_fields=['instagram_container_fingerprint', 'legenda'])

            with mock.patch('social_automation.instagram.verificar_configuracao_instagram'), mock.patch(
                'social_automation.instagram.obter_conta_instagram',
                return_value={'username': 'lailapistola'},
            ), mock.patch('social_automation.instagram.criar_container_reel', return_value='container-novo') as create_mock, mock.patch(
                'social_automation.instagram.status_container_pronto',
                return_value=True,
            ), mock.patch('social_automation.instagram.publicar_container', return_value='media-1') as publish_mock, mock.patch(
                'social_automation.instagram.obter_midia_publicada',
                return_value={'id': 'media-1'},
            ):
                __import__('social_automation.instagram').instagram.publicar_conteudo_instagram(content)

            create_mock.assert_called_once()
            publish_mock.assert_called_once_with('container-novo')

    @override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_publicacao_reel_invalida_container_stale_por_novo_mp4(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content()
            content.status = SocialContent.Status.APROVADO
            content.instagram_container_id = 'container-antigo'
            content.final_video = video_mp4_teste('reel-antigo.mp4', tamanho=1024)
            content.save(update_fields=['status', 'instagram_container_id', 'final_video'])
            old_fingerprint = calculate_instagram_container_fingerprint(content)
            content.instagram_container_fingerprint = old_fingerprint
            content.final_video = video_mp4_teste('reel-novo.mp4', tamanho=4096)
            content.save(update_fields=['instagram_container_fingerprint', 'final_video'])

            with mock.patch('social_automation.instagram.verificar_configuracao_instagram'), mock.patch(
                'social_automation.instagram.obter_conta_instagram',
                return_value={'username': 'lailapistola'},
            ), mock.patch('social_automation.instagram.criar_container_reel', return_value='container-novo') as create_mock, mock.patch(
                'social_automation.instagram.status_container_pronto',
                return_value=True,
            ), mock.patch('social_automation.instagram.publicar_container', return_value='media-1') as publish_mock, mock.patch(
                'social_automation.instagram.obter_midia_publicada',
                return_value={'id': 'media-1'},
            ):
                __import__('social_automation.instagram').instagram.publicar_conteudo_instagram(content)

            self.assertNotEqual(old_fingerprint, calculate_instagram_container_fingerprint(content))
            create_mock.assert_called_once()
            publish_mock.assert_called_once_with('container-novo')

    def test_fingerprint_muda_com_hashtags_e_share_to_feed(self):
        content = self._content()
        content.final_video = video_mp4_teste()
        content.save(update_fields=['final_video'])
        original = calculate_instagram_container_fingerprint(content)
        content.hashtags = '#laila #novo'
        content.save(update_fields=['hashtags'])
        self.assertNotEqual(original, calculate_instagram_container_fingerprint(content))

        com_hashtags = calculate_instagram_container_fingerprint(content)
        with mock.patch('social_automation.container_versioning.REEL_SHARE_TO_FEED', 'false'):
            self.assertNotEqual(com_hashtags, calculate_instagram_container_fingerprint(content))

        self.assertIn('#novo', build_instagram_caption(content))
        self.assertEqual(REEL_SHARE_TO_FEED, 'true')

    def test_auditoria_video_reel_valida_mp4(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content()
            content.final_video = video_mp4_teste()
            content.save(update_fields=['final_video'])

            audit = auditar_video_reel(content)
            resumo = resumir_video_url('https://dashboard-ambar.onrender.com/social-media/ig-video/1/token.mp4')

        self.assertEqual(audit['format'], 'MP4')
        self.assertEqual(audit['width'], 1080)
        self.assertEqual(audit['height'], 1920)
        self.assertEqual(audit['duration'], 7)
        self.assertTrue(resumo['has_mp4'])

    def test_comando_ffmpeg_reel_usa_frame_estatico_otimizado(self):
        command = _ffmpeg_command('/usr/bin/ffmpeg', Path('/tmp/frame.jpg'), Path('/tmp/reel.mp4'), 7)

        self.assertEqual(command[0], '/usr/bin/ffmpeg')
        self.assertIn('-loop', command)
        self.assertEqual(command[command.index('-loop') + 1], '1')
        self.assertEqual(command[command.index('-framerate') + 1], '30')
        self.assertEqual(command[command.index('-preset') + 1], 'veryfast')
        self.assertEqual(command[command.index('-tune') + 1], 'stillimage')
        self.assertEqual(command[command.index('-threads') + 1], '1')
        self.assertEqual(Path(command[-1]).name, 'reel.mp4')

    def test_render_reel_gera_um_frame_unico_e_salva_no_storage(self):
        content = self._content()
        captured = {}

        def fake_run(command, **kwargs):
            captured['command'] = command
            captured['kwargs'] = kwargs
            output_path = Path(command[-1])
            output_path.write_bytes(b'\x00\x00\x00\x18ftypmp42' + (b'0' * 256))
            captured['output_path'] = output_path
            return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            with mock.patch('social_automation.video_rendering.ffmpeg_path', return_value='/usr/bin/ffmpeg'), mock.patch(
                'social_automation.video_rendering._compose_reel_frame',
                return_value=Image.new('RGB', (1080, 1920), color='black'),
            ), mock.patch('social_automation.video_rendering.subprocess.run', side_effect=fake_run):
                renderizar_reel_social(content)

            content.refresh_from_db()
            self.assertTrue(content.final_video)
            self.assertTrue(content.final_video.storage.exists(content.final_video.name))

        command = captured['command']
        self.assertEqual(command[command.index('-i') + 1], str(Path(command[command.index('-i') + 1])))
        self.assertEqual(Path(command[command.index('-i') + 1]).name, 'frame.jpg')
        self.assertEqual(Path(command[-1]).name, 'reel.mp4')
        self.assertTrue(captured['kwargs']['check'])
        self.assertEqual(captured['kwargs']['timeout'], 30)
        self.assertFalse(captured['output_path'].exists())

    def test_render_reel_bem_sucedido_invalida_container_antigo(self):
        content = self._content()
        content.instagram_container_id = 'container-antigo'
        content.instagram_container_fingerprint = 'abc123'
        content.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint'])

        def fake_run(command, **kwargs):
            Path(command[-1]).write_bytes(b'\x00\x00\x00\x18ftypmp42' + (b'0' * 256))
            return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            with mock.patch('social_automation.video_rendering.ffmpeg_path', return_value='/usr/bin/ffmpeg'), mock.patch(
                'social_automation.video_rendering._compose_reel_frame',
                return_value=Image.new('RGB', (1080, 1920), color='black'),
            ), mock.patch('social_automation.video_rendering.subprocess.run', side_effect=fake_run):
                renderizar_reel_social(content)

            content.refresh_from_db()
            self.assertEqual(content.instagram_container_id, '')
            self.assertEqual(content.instagram_container_fingerprint, '')

    def test_render_reel_retorna_erro_amigavel_em_timeout(self):
        content = self._content()

        with mock.patch('social_automation.video_rendering.ffmpeg_path', return_value='/usr/bin/ffmpeg'), mock.patch(
            'social_automation.video_rendering._compose_reel_frame',
            return_value=Image.new('RGB', (1080, 1920), color='black'),
        ), mock.patch(
            'social_automation.video_rendering.subprocess.run',
            side_effect=subprocess.TimeoutExpired(cmd='ffmpeg', timeout=30),
        ):
            with self.assertRaisesMessage(SocialVideoRenderError, 'Nao foi possivel gerar o Reel'):
                renderizar_reel_social(content)
        content.refresh_from_db()
        self.assertEqual(content.instagram_container_id, '')

    def test_render_reel_retorna_erro_amigavel_em_falha_ffmpeg(self):
        content = self._content()
        error = subprocess.CalledProcessError(1, 'ffmpeg', stderr='falha controlada do encoder')

        with mock.patch('social_automation.video_rendering.ffmpeg_path', return_value='/usr/bin/ffmpeg'), mock.patch(
            'social_automation.video_rendering._compose_reel_frame',
            return_value=Image.new('RGB', (1080, 1920), color='black'),
        ), mock.patch('social_automation.video_rendering.subprocess.run', side_effect=error):
            with self.assertRaisesMessage(SocialVideoRenderError, 'Nao foi possivel gerar o Reel'):
                renderizar_reel_social(content)

    def test_validacao_rejeita_mp4_vazio_e_acima_do_limite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_path = Path(temp_dir) / 'reel.mp4'
            empty_path.write_bytes(b'')
            with self.assertRaisesMessage(SocialVideoRenderError, 'vazio'):
                _validate_output_file(empty_path)

            large_path = Path(temp_dir) / 'grande.mp4'
            large_path.write_bytes(b'123')
            with override_settings(SOCIAL_REEL_MAX_FILE_MB=0):
                with self.assertRaisesMessage(SocialVideoRenderError, 'tamanho maximo'):
                    _validate_output_file(large_path)

    def test_render_reel_falha_controlada_sem_ffmpeg(self):
        content = self._content()
        with mock.patch('social_automation.video_rendering.ffmpeg_path', return_value=None):
            with self.assertRaises(SocialRenderError):
                renderizar_reel_social(content)

    def test_render_com_falha_preserva_container_anterior(self):
        content = self._content()
        content.status = SocialContent.Status.APROVADO
        content.instagram_container_id = 'container-valido'
        content.instagram_container_fingerprint = 'fingerprint-valido'
        content.save(update_fields=['status', 'instagram_container_id', 'instagram_container_fingerprint'])

        with mock.patch('social_automation.views.renderizar_midia_social', side_effect=SocialVideoRenderError('falha controlada')):
            response = self.client.post(reverse('social_automation:content_render', args=[content.id]))

        self.assertEqual(response.status_code, 302)
        content.refresh_from_db()
        self.assertEqual(content.instagram_container_id, 'container-valido')
        self.assertEqual(content.instagram_container_fingerprint, 'fingerprint-valido')

    def test_criacao_manual_de_reel_nao_derruba_interface_quando_render_falha(self):
        image = self._image()
        url = reverse('social_automation:profile_content_create', args=[self.profile.id])
        payload = {
            'profile': self.profile.id,
            'media_type': SocialContent.MediaType.REEL,
            'base_image': image.id,
            'frase': 'Segunda-feira veio sem pedir licenca',
            'legenda': 'Legenda',
            'hashtags': '#laila',
        }

        with mock.patch(
            'social_automation.views.renderizar_midia_social',
            side_effect=SocialVideoRenderError('falha controlada'),
        ):
            response = self.client.post(url, payload)

        self.assertEqual(response.status_code, 302)
        content = SocialContent.objects.latest('id')
        self.assertEqual(content.media_type, SocialContent.MediaType.REEL)
        self.assertEqual(content.status, SocialContent.Status.RASCUNHO)
        self.assertFalse(content.final_video)

    def test_conteudo_publicado_nao_exibe_nem_executa_renderizar_novamente(self):
        content = self._content()
        content.status = SocialContent.Status.PUBLICADO
        content.final_video = video_mp4_teste()
        content.save(update_fields=['status', 'final_video'])
        original_video_name = content.final_video.name

        detail = self.client.get(reverse('social_automation:content_detail', args=[content.id]))
        self.assertNotContains(detail, 'Renderizar novamente')

        with mock.patch('social_automation.views.renderizar_midia_social') as render_mock:
            response = self.client.post(reverse('social_automation:content_render', args=[content.id]))

        self.assertEqual(response.status_code, 302)
        render_mock.assert_not_called()
        content.refresh_from_db()
        self.assertEqual(content.final_video.name, original_video_name)

    @override_settings(INSTAGRAM_ACCESS_TOKEN='token-teste', INSTAGRAM_USER_ID='178000000000', PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
    def test_diagnostico_container_reel_salva_container_e_fingerprint(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            content = self._content()
            content.final_video = video_mp4_teste()
            content.save(update_fields=['final_video'])
            output = StringIO()

            with mock.patch('social_automation.instagram._request', return_value={'id': 'container-reel-1'}), mock.patch(
                'social_automation.instagram.publicar_container'
            ) as publish_mock:
                call_command('diagnosticar_container_reel_instagram', str(content.id), stdout=output)

            content.refresh_from_db()
            self.assertEqual(content.instagram_container_id, 'container-reel-1')
            self.assertEqual(content.instagram_container_fingerprint, calculate_instagram_container_fingerprint(content))
            self.assertIn('Fingerprint:', output.getvalue())
            publish_mock.assert_not_called()


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

                def fake_generation(profile, quantidade, tema, usuario, media_types=None):
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


@override_settings(
    PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    SOCIAL_INSTAGRAM_LEGACY_FALLBACK=False,
    SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY='zCqifZSDofMEnNAGXaUnOpI0XzXDy3NCc8RxV9RI3l4=',
)
class SocialAutomationMultiProfileInstagramTests(TestCase):
    def setUp(self):
        self.profile_a = SocialProfile.objects.create(
            nome='Perfil A',
            username='perfil_a',
            posts_por_dia=20,
            reels_por_dia=5,
            horarios_publicacao=['12:00'],
        )
        self.profile_b = SocialProfile.objects.create(
            nome='Perfil B',
            username='perfil_b',
            posts_por_dia=10,
            reels_por_dia=2,
            horarios_publicacao=['13:00'],
        )
        self.connection_a = self._connection(self.profile_a, '178-A', 'perfil_a', 'token-a')
        self.connection_b = self._connection(self.profile_b, '178-B', 'perfil_b', 'token-b')

    def _connection(self, profile, user_id, username, token):
        connection = SocialInstagramConnection(
            profile=profile,
            instagram_user_id=user_id,
            username=username,
            account_type=SocialInstagramConnection.AccountType.BUSINESS,
        )
        connection.set_access_token(token)
        connection.save()
        return connection

    def _content(self, profile, frase='Frase teste'):
        content = SocialContent.objects.create(
            profile=profile,
            frase=frase,
            legenda='Legenda',
            status=SocialContent.Status.APROVADO,
        )
        content.final_image.save(f'{profile.username}.jpg', imagem_teste(f'{profile.username}.jpg'))
        return content

    def test_token_fica_criptografado_no_banco(self):
        self.assertNotIn('token-a', self.connection_a.access_token_encrypted)
        self.assertEqual(self.connection_a.get_access_token(), 'token-a')
        encrypted = encrypt_instagram_token('segredo-extra')
        self.assertNotEqual(encrypted, 'segredo-extra')
        self.assertEqual(decrypt_instagram_token(encrypted), 'segredo-extra')

    @override_settings(SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY='')
    def test_chave_ausente_bloqueia_criptografia(self):
        with self.assertRaisesMessage(InstagramTokenEncryptionError, 'SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY nao configurada.'):
            encrypt_instagram_token('token-teste')

    @override_settings(SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY='chave-invalida')
    def test_chave_invalida_bloqueia_criptografia(self):
        with self.assertRaisesMessage(InstagramTokenEncryptionError, 'Chave de criptografia do Instagram invalida.'):
            encrypt_instagram_token('token-teste')

    def test_token_criptografado_com_uma_chave_nao_abre_com_outra(self):
        encrypted = encrypt_instagram_token('token-teste')
        with override_settings(SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY='nFycY45v7D4kR1US9DJy0nXHXTaXpaI80MOTvF4Cy6k='):
            with self.assertRaisesMessage(InstagramTokenEncryptionError, 'Token Instagram nao pode ser descriptografado.'):
                decrypt_instagram_token(encrypted)

    def test_account_type_media_creator_e_publicavel(self):
        self.assertEqual(normalize_instagram_account_type('MEDIA_CREATOR'), SocialInstagramConnection.AccountType.CREATOR)
        self.assertTrue(is_publishable_instagram_account_type('MEDIA_CREATOR'))

    def test_account_type_media_business_e_publicavel(self):
        self.assertEqual(normalize_instagram_account_type('MEDIA_BUSINESS'), SocialInstagramConnection.AccountType.BUSINESS)
        self.assertTrue(is_publishable_instagram_account_type('MEDIA_BUSINESS'))

    def test_account_type_creator_business_legados_permanecem_publicaveis(self):
        self.assertTrue(is_publishable_instagram_account_type('CREATOR'))
        self.assertTrue(is_publishable_instagram_account_type('BUSINESS'))

    def test_account_type_personal_vazio_e_desconhecido_nao_sao_publicaveis(self):
        self.assertFalse(is_publishable_instagram_account_type('PERSONAL'))
        self.assertFalse(is_publishable_instagram_account_type(''))
        self.assertFalse(is_publishable_instagram_account_type('OUTRO'))

    def test_display_instagram_account_type_usa_normalizacao_compartilhada(self):
        self.assertEqual(display_instagram_account_type('MEDIA_CREATOR'), 'Creator')
        self.assertEqual(display_instagram_account_type('MEDIA_BUSINESS'), 'Business')

    def test_migracao_legacy_media_creator_cria_conexao_normalizada(self):
        output = StringIO()

        def fake_request(method, path, params=None, *, credentials=None):
            self.assertEqual(credentials.access_token, 'token-legacy')
            self.assertEqual(path, '178-LEGACY')
            return {'id': '178-LEGACY', 'username': 'perfil_a', 'account_type': 'MEDIA_CREATOR'}

        with override_settings(
            INSTAGRAM_ACCESS_TOKEN='token-legacy',
            INSTAGRAM_USER_ID='178-LEGACY',
            INSTAGRAM_EXPECTED_USERNAME='perfil_a',
        ), mock.patch('social_automation.instagram._request', side_effect=fake_request):
            call_command('migrar_instagram_legacy_para_perfil', 'perfil_a', '--apply', stdout=output)

        self.connection_a.refresh_from_db()
        texto = output.getvalue()
        self.assertIn('Conta: Creator', texto)
        self.assertIn('Publicavel: SIM', texto)
        self.assertEqual(self.connection_a.account_type, SocialInstagramConnection.AccountType.CREATOR)
        self.assertEqual(self.connection_a.instagram_user_id, '178-LEGACY')
        self.assertEqual(self.connection_a.username, 'perfil_a')
        self.assertNotIn('token-legacy', self.connection_a.access_token_encrypted)
        self.assertEqual(self.connection_a.get_access_token(), 'token-legacy')

    def test_migracao_legacy_media_creator_dry_run_nao_cria_conexao(self):
        self.connection_a.delete()
        output = StringIO()

        def fake_request(method, path, params=None, *, credentials=None):
            return {'id': '178-LEGACY', 'username': 'perfil_a', 'account_type': 'MEDIA_CREATOR'}

        with override_settings(
            INSTAGRAM_ACCESS_TOKEN='token-legacy',
            INSTAGRAM_USER_ID='178-LEGACY',
            INSTAGRAM_EXPECTED_USERNAME='perfil_a',
        ), mock.patch('social_automation.instagram._request', side_effect=fake_request):
            call_command('migrar_instagram_legacy_para_perfil', 'perfil_a', '--dry-run', stdout=output)

        texto = output.getvalue()
        self.assertIn('Conta: Creator', texto)
        self.assertIn('Publicavel: SIM', texto)
        self.assertFalse(SocialInstagramConnection.objects.filter(profile=self.profile_a).exists())

    def test_testar_instagram_mostra_conta_normalizada(self):
        output = StringIO()

        def fake_request(method, path, params=None, *, credentials=None):
            if path == '178-A':
                return {'id': '178-A', 'username': 'perfil_a', 'account_type': 'MEDIA_CREATOR'}
            if path == 'me/permissions':
                return {'data': [{'permission': 'instagram_business_content_publish', 'status': 'granted'}]}
            return {}

        with mock.patch('social_automation.instagram._request', side_effect=fake_request):
            call_command('testar_instagram', '--perfil', 'perfil_a', stdout=output)

        texto = output.getvalue()
        self.assertIn('Instagram API: OK', texto)
        self.assertIn('Conta: Creator', texto)

    def test_publicacao_usa_credencial_do_proprio_perfil(self):
        content_a = self._content(self.profile_a, 'Conteudo A')
        content_b = self._content(self.profile_b, 'Conteudo B')
        chamadas = []

        def fake_request(method, path, params=None, *, credentials=None):
            chamadas.append((credentials.access_token, credentials.instagram_user_id, method, path))
            if method == 'GET' and path in {'178-A', '178-B'}:
                username = 'perfil_a' if path == '178-A' else 'perfil_b'
                return {'id': path, 'username': username, 'account_type': 'MEDIA_BUSINESS'}
            if method == 'POST' and path.endswith('/media'):
                return {'id': f'container-{credentials.instagram_user_id}'}
            if method == 'GET' and path.startswith('container-'):
                return {'id': path, 'status_code': 'FINISHED'}
            if method == 'POST' and path.endswith('/media_publish'):
                return {'id': f'media-{credentials.instagram_user_id}'}
            if method == 'GET' and path.startswith('media-'):
                return {'id': path, 'permalink': f'https://instagram.test/{path}'}
            return {}

        with mock.patch('social_automation.instagram._request', side_effect=fake_request):
            publicar_conteudo_instagram(content_a)
            publicar_conteudo_instagram(content_b)

        tokens_a = [token for token, user_id, _method, _path in chamadas if user_id == '178-A']
        tokens_b = [token for token, user_id, _method, _path in chamadas if user_id == '178-B']
        self.assertTrue(tokens_a)
        self.assertTrue(tokens_b)
        self.assertEqual(set(tokens_a), {'token-a'})
        self.assertEqual(set(tokens_b), {'token-b'})

    @override_settings(INSTAGRAM_ACCESS_TOKEN='', INSTAGRAM_USER_ID='', INSTAGRAM_EXPECTED_USERNAME='')
    def test_perfil_sem_conexao_nao_publica(self):
        profile = SocialProfile.objects.create(nome='Sem IG', username='semig', horarios_publicacao=['12:00'])
        content = self._content(profile)
        with self.assertRaisesMessage(Exception, 'Conecte uma conta Instagram'):
            publicar_conteudo_instagram(content)
        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.ERRO)

    def test_estoque_minimo_e_alvo_sao_por_volume_do_perfil(self):
        self.assertEqual(estoque_minimo_profile(self.profile_a), 40)
        self.assertEqual(estoque_alvo_profile(self.profile_a), 60)
        self.assertEqual(estoque_minimo_profile(self.profile_b), 20)
        self.assertEqual(estoque_alvo_profile(self.profile_b), 30)

    def test_troca_de_conexao_invalida_container_do_perfil(self):
        content_a = self._content(self.profile_a)
        content_b = self._content(self.profile_b)
        SocialContent.objects.filter(pk__in=[content_a.pk, content_b.pk]).update(
            instagram_container_id='container-antigo',
            instagram_container_fingerprint='abc123',
        )
        self.connection_a.instagram_user_id = '178-A-NOVO'
        self.connection_a.save()
        content_a.refresh_from_db()
        content_b.refresh_from_db()
        self.assertEqual(content_a.instagram_container_id, '')
        self.assertEqual(content_a.instagram_container_fingerprint, '')
        self.assertEqual(content_b.instagram_container_id, 'container-antigo')

    def test_ui_mostra_status_e_acoes_da_conexao(self):
        user = User.objects.create_user('staff-social', password='123', is_staff=True)
        self.client.force_login(user)
        response = self.client.get(reverse('social_automation:profile_detail', args=[self.profile_a.id]))
        self.assertContains(response, '@perfil_a')
        self.assertContains(response, 'Testar conexao')
        self.assertContains(response, 'Desconectar')


@override_settings(
    SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY='zCqifZSDofMEnNAGXaUnOpI0XzXDy3NCc8RxV9RI3l4=',
    PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    INSTAGRAM_ACCESS_TOKEN='',
    INSTAGRAM_USER_ID='',
    INSTAGRAM_EXPECTED_USERNAME='',
)
class SocialAutomationCarouselTests(TestCase):
    def setUp(self):
        self.profile = SocialProfile.objects.create(
            nome='Perfil Carrossel',
            username='perfil_carrossel',
            posts_por_dia=20,
            reels_por_dia=6,
            carousels_por_dia=0,
            horarios_publicacao=['08:00', '12:00'],
        )
        self.connection = SocialInstagramConnection.objects.create(
            profile=self.profile,
            instagram_user_id='178-CAROUSEL',
            username='perfil_carrossel',
            account_type=SocialInstagramConnection.AccountType.BUSINESS,
        )
        self.connection.set_access_token('token-carousel')
        self.connection.save()
        self.template = SocialCarouselTemplate.objects.create(profile=self.profile, name='Padrao', is_default=True)

    def _content(self):
        content = SocialContent.objects.create(
            profile=self.profile,
            carousel_template=self.template,
            media_type=SocialContent.MediaType.CAROUSEL,
            frase='Capa do carrossel',
            legenda='Legenda do carrossel',
            hashtags='#teste',
            status=SocialContent.Status.APROVADO,
        )
        SocialCarouselSlide.objects.create(content=content, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='Capa')
        SocialCarouselSlide.objects.create(content=content, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, title='Ponto 1', body='Texto curto do primeiro slide.')
        SocialCarouselSlide.objects.create(content=content, order=3, slide_type=SocialCarouselSlide.SlideType.CTA, title='Chamada final')
        return content

    def test_mix_antigo_sem_carrossel_permanece_20_6_14(self):
        plan = build_daily_media_plan(20, 6, 0)
        self.assertEqual(len(plan), 20)
        self.assertEqual(plan.count(SocialContent.MediaType.REEL), 6)
        self.assertEqual(plan.count(SocialContent.MediaType.CAROUSEL), 0)
        self.assertEqual(plan.count(SocialContent.MediaType.IMAGE), 14)

    def test_mix_com_carrossel_distribui_tres_tipos(self):
        plan = build_daily_media_plan(12, 3, 2)
        self.assertEqual(plan.count(SocialContent.MediaType.REEL), 3)
        self.assertEqual(plan.count(SocialContent.MediaType.CAROUSEL), 2)
        self.assertEqual(plan.count(SocialContent.MediaType.IMAGE), 7)

    def test_renderiza_carrossel_em_slides_jpeg(self):
        content = self._content()
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        slides = list(content.carousel_slides.order_by('order'))
        self.assertTrue(content.final_media_ready)
        for slide in slides:
            self.assertTrue(slide.rendered_image)
            audit = auditar_imagem_slide_carrossel(slide)
            self.assertEqual(audit['format'], 'JPEG')
            self.assertIn((audit['width'], audit['height']), {(1080, 1080), (1080, 1350)})

    def test_assinatura_de_slide_usa_rota_protegida(self):
        content = self._content()
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        slide = content.carousel_slides.order_by('order').first()
        signature = gerar_assinatura_carousel_slide_meta(slide)
        self.assertEqual(validar_assinatura_carousel_slide_meta(content.id, slide.id, signature), slide)
        url = url_carousel_slide_meta_compat(slide)
        self.assertIn('/social-media/ig-carousel/', url)
        response = self.client.get(reverse('social_public_carousel_slide_meta_compat', args=[content.id, slide.id, signature]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')

    def test_fingerprint_muda_quando_slide_muda(self):
        content = self._content()
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        slide = content.carousel_slides.order_by('order').first()
        original = calculate_instagram_carousel_slide_fingerprint(slide, '178-CAROUSEL')
        slide.title = 'Capa alterada'
        slide.save(update_fields=['title', 'updated_at'])
        renderizar_midia_social(content)
        slide.refresh_from_db()
        self.assertNotEqual(original, calculate_instagram_carousel_slide_fingerprint(slide, '178-CAROUSEL'))

    def test_publicacao_carrossel_cria_filhos_pai_e_publica(self):
        content = self._content()
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        calls = []

        def fake_request(method, path, params=None, *, credentials=None):
            params = params or {}
            calls.append((method, path, params.copy()))
            if method == 'GET' and path == '178-CAROUSEL':
                return {'id': '178-CAROUSEL', 'username': 'perfil_carrossel', 'account_type': 'BUSINESS'}
            if method == 'POST' and path.endswith('/media') and params.get('is_carousel_item') == 'true':
                return {'id': f'child-{len([call for call in calls if call[2].get("is_carousel_item") == "true"])}'}
            if method == 'POST' and path.endswith('/media') and params.get('media_type') == 'CAROUSEL':
                return {'id': 'parent-1'}
            if method == 'GET' and (path.startswith('child-') or path == 'parent-1'):
                return {'id': path, 'status_code': 'FINISHED'}
            if method == 'POST' and path.endswith('/media_publish'):
                return {'id': 'media-carousel'}
            if method == 'GET' and path == 'media-carousel':
                return {'id': 'media-carousel', 'permalink': 'https://instagram.test/media-carousel'}
            return {}

        with mock.patch('social_automation.instagram._request', side_effect=fake_request):
            publicar_conteudo_instagram(content)

        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.PUBLICADO)
        self.assertEqual(content.external_post_id, 'media-carousel')
        parent_payloads = [params for method, path, params in calls if method == 'POST' and path.endswith('/media') and params.get('media_type') == 'CAROUSEL']
        self.assertEqual(parent_payloads[0]['children'], 'child-1,child-2,child-3')


class SocialAutomationCarouselFormSetTests(TestCase):
    def setUp(self):
        self.profile = SocialProfile.objects.create(
            nome='Perfil Formset',
            username='perfil_formset',
            horarios_publicacao=['08:00'],
        )
        self.template = SocialCarouselTemplate.objects.create(profile=self.profile, name='Template', is_default=True)

    def _content(self):
        return SocialContent.objects.create(
            profile=self.profile,
            carousel_template=self.template,
            media_type=SocialContent.MediaType.CAROUSEL,
            frase='Carrossel manual',
            legenda='Legenda',
            hashtags='#teste',
        )

    def _payload(self, content, rows, total_forms=6, initial_forms=0, existing_slides=None):
        prefix = SocialCarouselSlideFormSet(instance=content).prefix
        payload = {
            f'{prefix}-TOTAL_FORMS': str(total_forms),
            f'{prefix}-INITIAL_FORMS': str(initial_forms),
            f'{prefix}-MIN_NUM_FORMS': '0',
            f'{prefix}-MAX_NUM_FORMS': '1000',
        }
        existing_slides = existing_slides or []
        for index in range(total_forms):
            payload[f'{prefix}-{index}-id'] = ''
            payload[f'{prefix}-{index}-order'] = '1'
            payload[f'{prefix}-{index}-slide_type'] = SocialCarouselSlide.SlideType.CONTENT
            payload[f'{prefix}-{index}-title'] = ''
            payload[f'{prefix}-{index}-body'] = ''
            payload[f'{prefix}-{index}-is_active'] = 'on'
            if index < len(existing_slides):
                payload[f'{prefix}-{index}-id'] = str(existing_slides[index].id)
        for index, values in rows.items():
            for field, value in values.items():
                payload[f'{prefix}-{index}-{field}'] = value
        return payload

    def _formset(self, content, rows, total_forms=6, initial_forms=0, existing_slides=None):
        return SocialCarouselSlideFormSet(
            self._payload(content, rows, total_forms=total_forms, initial_forms=initial_forms, existing_slides=existing_slides),
            instance=content,
        )

    def test_carrossel_novo_com_tres_slides_e_extras_vazios_e_valido(self):
        content = self._content()
        formset = self._formset(
            content,
            {
                0: {'order': '1', 'slide_type': SocialCarouselSlide.SlideType.COVER, 'title': 'Capa'},
                1: {'order': '2', 'slide_type': SocialCarouselSlide.SlideType.CONTENT, 'body': 'Conteudo'},
                2: {'order': '3', 'slide_type': SocialCarouselSlide.SlideType.CTA, 'body': 'CTA'},
            },
            total_forms=6,
        )

        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())
        formset.save()
        self.assertEqual(content.carousel_slides.count(), 3)

    def test_duplicidade_real_de_order_continua_invalida(self):
        content = self._content()
        formset = self._formset(
            content,
            {
                0: {'order': '1', 'slide_type': SocialCarouselSlide.SlideType.COVER, 'title': 'Capa'},
                1: {'order': '1', 'slide_type': SocialCarouselSlide.SlideType.CONTENT, 'body': 'Conteudo'},
            },
        )

        self.assertFalse(formset.is_valid())
        self.assertIn('ordem unica', str(formset.non_form_errors()))

    def test_defaults_de_extra_nao_criam_slide_vazio(self):
        content = self._content()
        formset = self._formset(content, {}, total_forms=6)

        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())
        formset.save()
        self.assertEqual(content.carousel_slides.count(), 0)

    def test_minimo_de_slides_ativos_e_preservado(self):
        content = self._content()
        um_slide = self._formset(content, {0: {'order': '1', 'slide_type': SocialCarouselSlide.SlideType.COVER, 'title': 'Capa'}})
        self.assertFalse(um_slide.is_valid())
        self.assertIn('minimo 2', str(um_slide.non_form_errors()))

        dois_slides = self._formset(
            content,
            {
                0: {'order': '1', 'slide_type': SocialCarouselSlide.SlideType.COVER, 'title': 'Capa'},
                1: {'order': '2', 'slide_type': SocialCarouselSlide.SlideType.CONTENT, 'body': 'Conteudo'},
            },
        )
        self.assertTrue(dois_slides.is_valid(), dois_slides.errors or dois_slides.non_form_errors())

    def test_maximo_de_dez_slides_ativos_e_preservado(self):
        content = self._content()
        dez = {
            index: {'order': str(index + 1), 'slide_type': SocialCarouselSlide.SlideType.CONTENT, 'body': f'Slide {index + 1}'}
            for index in range(10)
        }
        formset_dez = self._formset(content, dez, total_forms=10)
        self.assertTrue(formset_dez.is_valid(), formset_dez.errors or formset_dez.non_form_errors())

        onze = {
            index: {'order': str(index + 1), 'slide_type': SocialCarouselSlide.SlideType.CONTENT, 'body': f'Slide {index + 1}'}
            for index in range(11)
        }
        formset_onze = self._formset(content, onze, total_forms=11)
        self.assertFalse(formset_onze.is_valid())
        self.assertIn('maximo 10', str(formset_onze.non_form_errors()))

    def test_edicao_com_extras_vazios_nao_cria_slides_nem_duplica_order(self):
        content = self._content()
        slides = [
            SocialCarouselSlide.objects.create(content=content, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='Capa'),
            SocialCarouselSlide.objects.create(content=content, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, body='Conteudo'),
            SocialCarouselSlide.objects.create(content=content, order=3, slide_type=SocialCarouselSlide.SlideType.CTA, body='CTA'),
        ]
        formset = self._formset(
            content,
            {
                0: {'order': '1', 'slide_type': SocialCarouselSlide.SlideType.COVER, 'title': 'Capa'},
                1: {'order': '2', 'slide_type': SocialCarouselSlide.SlideType.CONTENT, 'body': 'Conteudo'},
                2: {'order': '3', 'slide_type': SocialCarouselSlide.SlideType.CTA, 'body': 'CTA'},
            },
            total_forms=9,
            initial_forms=3,
            existing_slides=slides,
        )

        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())
        formset.save()
        self.assertEqual(content.carousel_slides.count(), 3)

    def test_delete_ignora_slide_removido_em_quantidade_e_order(self):
        content = self._content()
        slides = [
            SocialCarouselSlide.objects.create(content=content, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='Capa'),
            SocialCarouselSlide.objects.create(content=content, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, body='Conteudo'),
            SocialCarouselSlide.objects.create(content=content, order=3, slide_type=SocialCarouselSlide.SlideType.CTA, body='CTA'),
        ]
        formset = self._formset(
            content,
            {
                0: {'order': '1', 'slide_type': SocialCarouselSlide.SlideType.COVER, 'title': 'Capa'},
                1: {'order': '2', 'slide_type': SocialCarouselSlide.SlideType.CONTENT, 'body': 'Conteudo', 'DELETE': 'on'},
                2: {'order': '3', 'slide_type': SocialCarouselSlide.SlideType.CTA, 'body': 'CTA'},
            },
            total_forms=9,
            initial_forms=3,
            existing_slides=slides,
        )

        self.assertTrue(formset.is_valid(), formset.errors or formset.non_form_errors())
        formset.save()
        self.assertEqual(list(content.carousel_slides.order_by('order').values_list('order', flat=True)), [1, 3])


@override_settings(PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com')
class SocialAutomationCarouselVisualComposerTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-visual-composer', password='senha', is_staff=True)
        self.client.force_login(self.staff)
        self.profile_a = SocialProfile.objects.create(nome='Perfil Visual A', username='visual_a', horarios_publicacao=['08:00'])
        self.profile_b = SocialProfile.objects.create(nome='Perfil Visual B', username='visual_b', horarios_publicacao=['09:00'])
        self.template_a = SocialCarouselTemplate.objects.create(profile=self.profile_a, name='Familia A', is_default=True)
        self.template_b = SocialCarouselTemplate.objects.create(profile=self.profile_b, name='Familia B', is_default=True)

    def _image_file(self, name, color):
        buffer = BytesIO()
        Image.new('RGB', (1080, 1080), color=color).save(buffer, format='JPEG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')

    def _base_image(self, profile=None, name='base.jpg', color=(240, 240, 240), **kwargs):
        profile = profile or self.profile_a
        return SocialBaseImage.objects.create(
            profile=profile,
            nome=name,
            arquivo=self._image_file(name, color),
            tags=kwargs.pop('tags', 'teste'),
            **kwargs,
        )

    def _content(self, base_image=None):
        return SocialContent.objects.create(
            profile=self.profile_a,
            carousel_template=self.template_a,
            base_image=base_image,
            media_type=SocialContent.MediaType.CAROUSEL,
            frase='Titulo do carrossel',
            legenda='Legenda',
            hashtags='#teste',
        )

    def _slide(self, **kwargs):
        content = kwargs.pop('content', None)
        base_image = kwargs.pop('base_image', None)
        if content is None:
            content = self._content(base_image)
        return SocialCarouselSlide.objects.create(
            content=content,
            order=kwargs.pop('order', 1),
            slide_type=kwargs.pop('slide_type', SocialCarouselSlide.SlideType.COVER),
            title=kwargs.pop('title', 'Titulo'),
            body=kwargs.pop('body', 'Corpo do slide'),
            **kwargs,
        )

    def _overlap_ratio(self, text_box, region):
        left = max(text_box[0], region[0])
        right = min(text_box[0] + text_box[2], region[0] + region[2])
        top = max(text_box[1], region[1])
        bottom = min(text_box[1] + text_box[3], region[1] + region[3])
        if right <= left or bottom <= top:
            return 0
        text_area = max(text_box[2] * text_box[3], 0.001)
        return ((right - left) * (bottom - top)) / text_area

    def _assert_no_protected_overlap(self, decision):
        for region in decision.metadata['protected_regions']:
            self.assertLessEqual(self._overlap_ratio(decision.metadata['text_zone'], region), 0.02)

    def test_identidade_visual_e_isolada_por_perfil(self):
        SocialVisualIdentity.objects.create(profile=self.profile_a, name='Marca A', accent_color='#ff0000', brand_name='Marca A')
        SocialVisualIdentity.objects.create(profile=self.profile_b, name='Marca B', accent_color='#0000ff', brand_name='Marca B')

        self.assertEqual(visual_identity_for_profile(self.profile_a).accent_color, '#ff0000')
        self.assertEqual(visual_identity_for_profile(self.profile_b).accent_color, '#0000ff')

    def test_render_multi_perfil_nao_mistura_identidade_template_ou_midia(self):
        from .rendering import renderizar_midia_social

        SocialVisualIdentity.objects.create(profile=self.profile_a, name='Marca A', brand_name='Marca A', accent_color='#ff0000')
        SocialVisualIdentity.objects.create(profile=self.profile_b, name='Marca B', brand_name='Marca B', accent_color='#0000ff')
        image_a = self._base_image(profile=self.profile_a, name='perfil-a.jpg', color=(30, 30, 30))
        image_b = self._base_image(profile=self.profile_b, name='perfil-b.jpg', color=(230, 230, 230))
        content_a = self._content(base_image=image_a)
        content_b = SocialContent.objects.create(
            profile=self.profile_b,
            carousel_template=self.template_b,
            base_image=image_b,
            media_type=SocialContent.MediaType.CAROUSEL,
            frase='Titulo B',
            legenda='Legenda B',
            hashtags='#b',
        )
        SocialCarouselSlide.objects.create(content=content_a, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='A')
        SocialCarouselSlide.objects.create(content=content_a, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, body='A')
        SocialCarouselSlide.objects.create(content=content_b, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='B')
        SocialCarouselSlide.objects.create(content=content_b, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, body='B')

        renderizar_midia_social(content_a)
        renderizar_midia_social(content_b)

        slide_a = content_a.carousel_slides.order_by('order').first()
        slide_b = content_b.carousel_slides.order_by('order').first()
        slide_a.refresh_from_db()
        slide_b.refresh_from_db()
        self.assertEqual(slide_a.render_metadata['brand_name'], 'Marca A')
        self.assertEqual(slide_b.render_metadata['brand_name'], 'Marca B')
        self.assertEqual(slide_a.render_metadata['source_base_image_id'], image_a.id)
        self.assertEqual(slide_b.render_metadata['source_base_image_id'], image_b.id)

    def test_variant_incompativel_rejeitada_e_auto_e_deterministico(self):
        variant = SocialCarouselTemplateVariant.objects.create(
            template=self.template_a,
            name='Somente conteudo',
            allowed_slide_types=[SocialCarouselSlide.SlideType.CONTENT],
            layout_type=SocialCarouselTemplateVariant.LayoutType.TEXT_TOP,
        )
        slide = self._slide(variant=variant, slide_type=SocialCarouselSlide.SlideType.COVER)

        with self.assertRaises(ValidationError):
            slide.full_clean()

        slide.variant = None
        first = compose_carousel_slide(slide, self.template_a, 3)
        second = compose_carousel_slide(slide, self.template_a, 3)
        self.assertEqual(first.layout_type, second.layout_type)

    def test_variants_compativeis_por_tipo_de_slide_sao_respeitadas(self):
        cases = [
            (SocialCarouselSlide.SlideType.COVER, SocialCarouselTemplateVariant.LayoutType.HERO_LEFT),
            (SocialCarouselSlide.SlideType.CONTENT, SocialCarouselTemplateVariant.LayoutType.TEXT_TOP),
            (SocialCarouselSlide.SlideType.CTA, SocialCarouselTemplateVariant.LayoutType.MINIMAL),
        ]
        for slide_type, layout in cases:
            with self.subTest(slide_type=slide_type):
                variant = SocialCarouselTemplateVariant.objects.create(
                    template=self.template_a,
                    name=f'Variant {slide_type}',
                    allowed_slide_types=[slide_type],
                    layout_type=layout,
                )
                slide = self._slide(slide_type=slide_type)
                decision = compose_carousel_slide(slide, self.template_a, 3)
                self.assertEqual(decision.variant_name, variant.name)
                self.assertEqual(decision.layout_type, layout)

    def test_variant_incompativel_nao_e_selecionada_automaticamente(self):
        SocialCarouselTemplateVariant.objects.create(
            template=self.template_a,
            name='CTA apenas',
            allowed_slide_types=[SocialCarouselSlide.SlideType.CTA],
            layout_type=SocialCarouselTemplateVariant.LayoutType.MINIMAL,
        )
        slide = self._slide(slide_type=SocialCarouselSlide.SlideType.COVER)

        decision = compose_carousel_slide(slide, self.template_a, 3)

        self.assertNotEqual(decision.variant_name, 'CTA apenas')

    def test_safe_area_evitar_regiao_protegida(self):
        image = self._base_image(
            text_safe_zone=SocialBaseImage.TextSafeZone.RIGHT,
            subject_position=SocialBaseImage.SubjectPosition.RIGHT,
        )
        SocialBaseImageProtectedRegion.objects.create(image=image, x=0.50, y=0.10, width=0.48, height=0.80)
        slide = self._slide(base_image=image, visual_intent=SocialCarouselTemplateVariant.LayoutType.HERO_RIGHT)

        decision = compose_carousel_slide(slide, self.template_a, 3)
        self.assertNotEqual(decision.layout_type, SocialCarouselTemplateVariant.LayoutType.HERO_RIGHT)
        if not decision.use_source_photo:
            self.assertEqual(decision.layout_type, SocialCarouselTemplateVariant.LayoutType.FULL_TEXT)
            return

        text_box = decision.metadata['text_zone']
        for region in protected_regions_for_image(image):
            left = max(text_box[0], region[0])
            right = min(text_box[0] + text_box[2], region[0] + region[2])
            top = max(text_box[1], region[1])
            bottom = min(text_box[1] + text_box[3], region[1] + region[3])
            self.assertTrue(right <= left or bottom <= top)

    def test_protected_region_centro_direita_escolhe_area_segura_sem_intersecao(self):
        image = self._base_image(
            text_safe_zone=SocialBaseImage.TextSafeZone.LEFT,
            subject_position=SocialBaseImage.SubjectPosition.RIGHT,
        )
        SocialBaseImageProtectedRegion.objects.create(image=image, x=0.55, y=0.18, width=0.40, height=0.62)
        slide = self._slide(base_image=image, title='Titulo grande para validar a caixa de texto protegida')

        decision = compose_carousel_slide(slide, self.template_a, 3)

        self.assertNotIn(decision.layout_type, [SocialCarouselTemplateVariant.LayoutType.HERO_RIGHT, SocialCarouselTemplateVariant.LayoutType.SPLIT_RIGHT])
        self._assert_no_protected_overlap(decision)

    def test_protected_region_esquerda_nao_usa_hero_left_colidindo(self):
        image = self._base_image(
            text_safe_zone=SocialBaseImage.TextSafeZone.RIGHT,
            subject_position=SocialBaseImage.SubjectPosition.LEFT,
        )
        SocialBaseImageProtectedRegion.objects.create(image=image, x=0.04, y=0.15, width=0.48, height=0.70)
        slide = self._slide(base_image=image)

        decision = compose_carousel_slide(slide, self.template_a, 3)

        self.assertNotEqual(decision.layout_type, SocialCarouselTemplateVariant.LayoutType.HERO_LEFT)
        self._assert_no_protected_overlap(decision)

    def test_protected_region_central_grande_usa_full_text_quando_nada_e_seguro(self):
        image = self._base_image()
        SocialBaseImageProtectedRegion.objects.create(image=image, x=0.02, y=0.02, width=0.96, height=0.96)
        slide = self._slide(base_image=image)

        decision = compose_carousel_slide(slide, self.template_a, 3)

        self.assertEqual(decision.layout_type, SocialCarouselTemplateVariant.LayoutType.FULL_TEXT)
        self.assertFalse(decision.use_source_photo)
        self.assertEqual(decision.metadata['source_base_image_id'], None)

    def test_full_text_e_fallback_real(self):
        safe_image = self._base_image(text_safe_zone=SocialBaseImage.TextSafeZone.LEFT)
        safe_decision = compose_carousel_slide(self._slide(base_image=safe_image), self.template_a, 3)
        self.assertNotEqual(safe_decision.layout_type, SocialCarouselTemplateVariant.LayoutType.FULL_TEXT)

        blocked_image = self._base_image(name='bloqueada.jpg')
        SocialBaseImageProtectedRegion.objects.create(image=blocked_image, x=0.01, y=0.01, width=0.98, height=0.98)
        blocked_decision = compose_carousel_slide(self._slide(base_image=blocked_image), self.template_a, 3)
        self.assertEqual(blocked_decision.layout_type, SocialCarouselTemplateVariant.LayoutType.FULL_TEXT)

    def test_contraste_automatico_em_imagem_clara_e_escura(self):
        light = self._base_image(name='clara.jpg', color=(245, 245, 245))
        dark = self._base_image(name='escura.jpg', color=(10, 10, 10))
        SocialVisualIdentity.objects.create(
            profile=self.profile_a,
            name='Contraste',
            light_text_color='#ffffff',
            dark_text_color='#111827',
            accent_color='#22c55e',
        )

        light_decision = compose_carousel_slide(self._slide(base_image=light), self.template_a, 3)
        dark_decision = compose_carousel_slide(self._slide(base_image=dark), self.template_a, 3)

        self.assertEqual(light_decision.text_color, (17, 24, 39))
        self.assertEqual(dark_decision.text_color, (255, 255, 255))
        self.assertNotEqual(light_decision.overlay_type, SocialCarouselTemplateVariant.OverlayType.NONE)
        self.assertEqual(dark_decision.overlay_type, SocialCarouselTemplateVariant.OverlayType.LIGHT)

    def test_overlay_respeita_identidade_visual_e_override(self):
        SocialVisualIdentity.objects.create(profile=self.profile_a, name='Overlay', default_overlay_strength=35)
        image = self._base_image(color=(140, 140, 140))
        decision = compose_carousel_slide(self._slide(base_image=image), self.template_a, 3)
        self.assertEqual(decision.overlay_strength, 35)

        slide = self._slide(base_image=image, overlay_override=SocialCarouselTemplateVariant.OverlayType.NONE)
        override_decision = compose_carousel_slide(slide, self.template_a, 3)
        self.assertEqual(override_decision.overlay_type, SocialCarouselTemplateVariant.OverlayType.NONE)
        self.assertEqual(override_decision.overlay_strength, 0)

    def test_determinismo_mesmo_input_mesma_decisao_e_metadata(self):
        image = self._base_image(text_safe_zone=SocialBaseImage.TextSafeZone.LEFT)
        slide = self._slide(base_image=image)

        first = compose_carousel_slide(slide, self.template_a, 4)
        second = compose_carousel_slide(slide, self.template_a, 4)

        self.assertEqual(first.layout_type, second.layout_type)
        self.assertEqual(first.metadata, second.metadata)

    def test_selecao_de_midia_considera_safe_zone_e_subject_position(self):
        image_a = self._base_image(
            name='texto-esquerda.jpg',
            subject_position=SocialBaseImage.SubjectPosition.RIGHT,
            text_safe_zone=SocialBaseImage.TextSafeZone.LEFT,
        )
        image_b = self._base_image(
            name='texto-direita.jpg',
            subject_position=SocialBaseImage.SubjectPosition.LEFT,
            text_safe_zone=SocialBaseImage.TextSafeZone.RIGHT,
        )
        content = self._content()

        left = SocialCarouselSlide.objects.create(
            content=content,
            order=1,
            slide_type=SocialCarouselSlide.SlideType.COVER,
            visual_intent=SocialCarouselTemplateVariant.LayoutType.HERO_LEFT,
            title='Texto esquerda',
        )
        right = SocialCarouselSlide.objects.create(
            content=content,
            order=2,
            slide_type=SocialCarouselSlide.SlideType.COVER,
            visual_intent=SocialCarouselTemplateVariant.LayoutType.HERO_RIGHT,
            title='Texto direita',
        )

        self.assertEqual(compose_carousel_slide(left, self.template_a, 2).source_base_image.id, image_a.id)
        self.assertEqual(compose_carousel_slide(right, self.template_a, 2).source_base_image.id, image_b.id)

    def test_override_manual_respeita_variant_e_imagem_quando_seguro(self):
        variant = SocialCarouselTemplateVariant.objects.create(
            template=self.template_a,
            name='Manual direita',
            allowed_slide_types=[SocialCarouselSlide.SlideType.COVER],
            layout_type=SocialCarouselTemplateVariant.LayoutType.HERO_RIGHT,
        )
        image = self._base_image(text_safe_zone=SocialBaseImage.TextSafeZone.RIGHT)
        slide = self._slide(variant=variant, source_base_image=image)

        decision = compose_carousel_slide(slide, self.template_a, 3)

        self.assertEqual(decision.variant_name, variant.name)
        self.assertEqual(decision.source_base_image.id, image.id)
        self.assertEqual(decision.layout_type, SocialCarouselTemplateVariant.LayoutType.HERO_RIGHT)

    def test_override_manual_com_conflito_nao_cobre_regiao_protegida(self):
        image = self._base_image(text_safe_zone=SocialBaseImage.TextSafeZone.LEFT)
        SocialBaseImageProtectedRegion.objects.create(image=image, x=0.04, y=0.15, width=0.50, height=0.70)
        slide = self._slide(source_base_image=image, visual_intent=SocialCarouselTemplateVariant.LayoutType.HERO_LEFT)

        decision = compose_carousel_slide(slide, self.template_a, 3)

        self.assertEqual(decision.layout_type, SocialCarouselTemplateVariant.LayoutType.FULL_TEXT)
        self.assertFalse(decision.use_source_photo)

    def test_template_legado_sem_variants_continua_renderizando(self):
        from .rendering import renderizar_midia_social

        content = self._content()
        SocialCarouselSlide.objects.create(content=content, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='Capa antiga')
        SocialCarouselSlide.objects.create(content=content, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, body='Conteudo antigo')

        renderizar_midia_social(content)

        self.assertEqual(content.carousel_slides.filter(rendered_image__gt='').count(), 2)

    def test_render_salva_metadata_visual_e_preserva_fluxo_carrossel(self):
        from .rendering import renderizar_midia_social

        image = self._base_image(name='render.jpg', color=(80, 80, 80))
        content = self._content(base_image=image)
        SocialCarouselSlide.objects.create(content=content, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='Capa')
        SocialCarouselSlide.objects.create(content=content, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, body='Conteudo')

        renderizar_midia_social(content)

        slide = content.carousel_slides.order_by('order').first()
        slide.refresh_from_db()
        self.assertTrue(slide.rendered_image)
        self.assertIn('layout_type', slide.render_metadata)
        self.assertIn('text_zone', slide.render_metadata)
        self.assertIn('text_color', slide.render_metadata)
        self.assertIn('overlay', slide.render_metadata)
        self.assertIn('source_base_image_id', slide.render_metadata)

    def test_carrossel_publicado_nao_e_rerenderizado_por_alteracao_visual(self):
        from .rendering import renderizar_midia_social

        image = self._base_image(name='publicado.jpg')
        content = self._content(base_image=image)
        content.status = SocialContent.Status.PUBLICADO
        content.published_at = timezone.now()
        content.save(update_fields=['status', 'published_at'])
        SocialCarouselSlide.objects.create(content=content, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='Publicado')
        SocialCarouselSlide.objects.create(content=content, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, body='Publicado')
        renderizar_midia_social(content)
        slide = content.carousel_slides.order_by('order').first()
        original_image = slide.rendered_image.name

        SocialVisualIdentity.objects.create(profile=self.profile_a, name='Nova marca', brand_name='Nova marca', is_default=False)
        SocialBaseImageProtectedRegion.objects.create(image=image, x=0.20, y=0.20, width=0.20, height=0.20)
        response = self.client.post(reverse('social_automation:content_update', args=[content.id]), {'frase': 'Tentativa'})
        slide.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(slide.rendered_image.name, original_image)

    def test_preview_carrossel_tem_imagem_principal_thumbnails_modal_e_rota_autenticada(self):
        from .rendering import renderizar_midia_social

        content = self._content()
        SocialCarouselSlide.objects.create(content=content, order=1, slide_type=SocialCarouselSlide.SlideType.COVER, title='Capa')
        SocialCarouselSlide.objects.create(content=content, order=2, slide_type=SocialCarouselSlide.SlideType.CONTENT, body='Conteudo')
        renderizar_midia_social(content)
        slide = content.carousel_slides.order_by('order').first()

        response = self.client.get(reverse('social_automation:content_detail', args=[content.id]))
        self.assertContains(response, 'data-carousel-main')
        self.assertContains(response, 'data-carousel-thumb')
        self.assertContains(response, 'data-carousel-modal')
        self.assertContains(response, 'data-carousel-counter')
        self.assertContains(response, 'data-carousel-prev')
        self.assertContains(response, 'data-carousel-next')
        self.assertNotContains(response, '/social-media/ig-carousel/')

        preview = self.client.get(reverse('social_automation:carousel_slide_preview', args=[slide.id]))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview['Content-Type'], 'image/jpeg')


@override_settings(
    SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY='zCqifZSDofMEnNAGXaUnOpI0XzXDy3NCc8RxV9RI3l4=',
    PLATFORM_BASE_URL='https://dashboard-ambar.onrender.com',
    INSTAGRAM_ACCESS_TOKEN='',
    INSTAGRAM_USER_ID='',
    INSTAGRAM_EXPECTED_USERNAME='',
)
class SocialAutomationCarouselHardeningTests(TestCase):
    def setUp(self):
        self.profile_a = SocialProfile.objects.create(
            nome='Perfil A',
            username='perfil_a_carrossel',
            posts_por_dia=8,
            reels_por_dia=2,
            carousels_por_dia=2,
            carousel_default_slide_count=4,
            carousel_default_cta='CTA A',
            carousel_ai_instructions='Instrucoes A',
            image_ai_instructions='Visual A',
            horarios_publicacao=['08:00', '10:00', '12:00', '14:00'],
        )
        self.profile_b = SocialProfile.objects.create(
            nome='Perfil B',
            username='perfil_b_carrossel',
            posts_por_dia=4,
            reels_por_dia=0,
            carousels_por_dia=1,
            carousel_ai_instructions='Instrucoes B',
            image_ai_instructions='Visual B',
            horarios_publicacao=['09:00', '11:00'],
        )
        self.template_a = SocialCarouselTemplate.objects.create(profile=self.profile_a, name='Template A', is_default=True)
        self.template_b = SocialCarouselTemplate.objects.create(
            profile=self.profile_b,
            name='Template B',
            aspect_ratio=SocialCarouselTemplate.AspectRatio.PORTRAIT,
            is_default=True,
        )
        self.base_a = SocialBaseImage.objects.create(profile=self.profile_a, nome='Base A', arquivo=imagem_social('base-a.jpg'))
        self.base_b = SocialBaseImage.objects.create(profile=self.profile_b, nome='Base B', arquivo=imagem_social('base-b.jpg'))
        self.connection_a = SocialInstagramConnection.objects.create(
            profile=self.profile_a,
            instagram_user_id='178-A-CAROUSEL',
            username='perfil_a_carrossel',
            account_type=SocialInstagramConnection.AccountType.BUSINESS,
        )
        self.connection_a.set_access_token('token-a-carousel')
        self.connection_a.save()
        self.connection_b = SocialInstagramConnection.objects.create(
            profile=self.profile_b,
            instagram_user_id='178-B-CAROUSEL',
            username='perfil_b_carrossel',
            account_type=SocialInstagramConnection.AccountType.BUSINESS,
        )
        self.connection_b.set_access_token('token-b-carousel')
        self.connection_b.save()

    def _carousel(self, profile=None, template=None, slide_count=3, status=SocialContent.Status.APROVADO):
        profile = profile or self.profile_a
        template = template or (self.template_a if profile == self.profile_a else self.template_b)
        content = SocialContent.objects.create(
            profile=profile,
            carousel_template=template,
            media_type=SocialContent.MediaType.CAROUSEL,
            frase='Capa operacional',
            legenda='Legenda final',
            hashtags='#obra #teste',
            status=status,
        )
        for order in range(1, slide_count + 1):
            slide_type = SocialCarouselSlide.SlideType.COVER if order == 1 else SocialCarouselSlide.SlideType.CONTENT
            if order == slide_count:
                slide_type = SocialCarouselSlide.SlideType.CTA
            SocialCarouselSlide.objects.create(
                content=content,
                order=order,
                slide_type=slide_type,
                title=f'Slide {order}',
                body=f'Descricao do slide {order}',
            )
        return content

    def _fake_meta(self, calls, fail_child_index=None, publish_error=None):
        def fake_request(method, path, params=None, *, credentials=None):
            params = params or {}
            calls.append((credentials.instagram_user_id if credentials else '', method, path, params.copy()))
            if method == 'GET' and path in {'178-A-CAROUSEL', '178-B-CAROUSEL'}:
                username = 'perfil_a_carrossel' if path == '178-A-CAROUSEL' else 'perfil_b_carrossel'
                return {'id': path, 'username': username, 'account_type': 'BUSINESS'}
            if method == 'POST' and path.endswith('/media') and params.get('is_carousel_item') == 'true':
                child_number = len([call for call in calls if call[3].get('is_carousel_item') == 'true'])
                if fail_child_index and child_number == fail_child_index:
                    raise InstagramAPIError('falha child', status=500, is_transient=True)
                return {'id': f'child-{child_number}'}
            if method == 'GET' and path.startswith('child-'):
                return {'id': path, 'status_code': 'FINISHED'}
            if method == 'POST' and path.endswith('/media') and params.get('media_type') == 'CAROUSEL':
                return {'id': 'parent-1'}
            if method == 'GET' and path == 'parent-1':
                return {'id': 'parent-1', 'status_code': 'FINISHED'}
            if method == 'POST' and path.endswith('/media_publish'):
                if publish_error:
                    raise publish_error
                return {'id': 'media-parent'}
            if method == 'GET' and path == 'media-parent':
                return {'id': 'media-parent', 'permalink': 'https://instagram.test/media-parent'}
            return {}

        return fake_request

    def test_model_defaults_e_validacoes_do_mix(self):
        profile = SocialProfile.objects.create(nome='Antigo', username='antigo', posts_por_dia=20, reels_por_dia=6)
        self.assertEqual(profile.carousels_por_dia, 0)
        self.assertEqual(build_daily_media_plan(20, 6, 0).count(SocialContent.MediaType.IMAGE), 14)
        self.assertEqual(build_daily_media_plan(20, 6, 0).count(SocialContent.MediaType.REEL), 6)
        self.assertEqual(build_daily_media_plan(8, 2, 2).count(SocialContent.MediaType.IMAGE), 4)
        with self.assertRaises(ValidationError):
            SocialProfile(nome='Invalido', username='x', posts_por_dia=2, reels_por_dia=2, carousels_por_dia=1).full_clean()
        SocialProfile(nome='Valido', username='y', posts_por_dia=2, reels_por_dia=1, carousels_por_dia=1, horarios_publicacao=['08:00']).full_clean()
        with self.assertRaises(ValidationError):
            SocialProfile(nome='Negativo', username='z', posts_por_dia=2, carousels_por_dia=-1).full_clean()

    def test_social_content_aceita_tres_tipos_de_midia(self):
        for media_type in [SocialContent.MediaType.IMAGE, SocialContent.MediaType.REEL, SocialContent.MediaType.CAROUSEL]:
            with self.subTest(media_type=media_type):
                content = SocialContent(profile=self.profile_a, media_type=media_type, frase='Teste')
                content.full_clean(exclude=['base_image', 'carousel_template'])

    def test_quantidade_de_slides_e_prontidao_final(self):
        for count, expected_ready_after_render in [(2, True), (10, True), (1, False), (11, False)]:
            with self.subTest(count=count):
                content = self._carousel(slide_count=count)
                if 2 <= count <= 10:
                    from .rendering import renderizar_midia_social

                    renderizar_midia_social(content)
                self.assertEqual(content.final_media_ready, expected_ready_after_render)

    def test_ordem_de_slides_preservada_e_pk_nao_define_publicacao(self):
        content = SocialContent.objects.create(
            profile=self.profile_a,
            carousel_template=self.template_a,
            media_type=SocialContent.MediaType.CAROUSEL,
            frase='Ordenacao',
            legenda='Legenda',
            status=SocialContent.Status.APROVADO,
        )
        slide_b = SocialCarouselSlide.objects.create(content=content, order=2, title='Segundo')
        slide_a = SocialCarouselSlide.objects.create(content=content, order=1, title='Primeiro')
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        self.assertLess(slide_b.id, slide_a.id)
        self.assertEqual(list(content.carousel_slides.order_by('order').values_list('title', flat=True)), ['Primeiro', 'Segundo'])

    def test_slide_de_outro_conteudo_e_rejeitado_por_assinatura(self):
        content_a = self._carousel()
        content_b = self._carousel()
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content_a)
        renderizar_midia_social(content_b)
        slide_b = content_b.carousel_slides.first()
        signature = gerar_assinatura_carousel_slide_meta(slide_b)
        with self.assertRaises(ValidationError):
            validar_assinatura_carousel_slide_meta(content_a.id, slide_b.id, signature)

    def test_template_e_form_filtram_por_perfil(self):
        self.assertIn(self.template_a, self.profile_a.carousel_templates.all())
        self.assertNotIn(self.template_b, self.profile_a.carousel_templates.all())
        from .forms import SocialContentForm

        form = SocialContentForm(profile=self.profile_a)
        self.assertIn(self.template_a, form.fields['carousel_template'].queryset)
        self.assertNotIn(self.template_b, form.fields['carousel_template'].queryset)

    def test_conteudo_nao_aceita_template_de_outro_perfil(self):
        content = SocialContent(
            profile=self.profile_b,
            carousel_template=self.template_a,
            media_type=SocialContent.MediaType.CAROUSEL,
            frase='Tenant errado',
        )
        with self.assertRaises(ValidationError):
            content.full_clean(exclude=['base_image'])

    def test_render_square_portrait_tipos_e_storage(self):
        for template, expected_size in [(self.template_a, (1080, 1080)), (self.template_b, (1080, 1350))]:
            with self.subTest(template=template.name):
                content = self._carousel(profile=template.profile, template=template)
                from .rendering import renderizar_midia_social

                renderizar_midia_social(content)
                sizes = []
                types = set()
                for slide in content.carousel_slides.order_by('order'):
                    audit = auditar_imagem_slide_carrossel(slide)
                    sizes.append((audit['width'], audit['height']))
                    types.add(slide.slide_type)
                    self.assertTrue(slide.rendered_image.storage.exists(slide.rendered_image.name))
                self.assertEqual(set(sizes), {expected_size})
                self.assertEqual(types, {SocialCarouselSlide.SlideType.COVER, SocialCarouselSlide.SlideType.CONTENT, SocialCarouselSlide.SlideType.CTA})

    def test_carrossel_sem_cta_renderiza(self):
        self.profile_a.carousel_cta_enabled = False
        self.profile_a.save(update_fields=['carousel_cta_enabled', 'updated_at'])
        content = self._carousel(slide_count=2)
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        self.assertTrue(content.final_media_ready)

    def test_texto_longo_demais_falha_sem_apagar_render_anterior(self):
        content = self._carousel(slide_count=2)
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        slide = content.carousel_slides.order_by('order').first()
        old_file = slide.rendered_image.name
        slide.instagram_container_id = 'child-valido'
        slide.instagram_container_fingerprint = 'fingerprint-valido'
        slide.title = 'X' * 3000
        slide.save(update_fields=['title', 'instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
        with self.assertRaises(SocialRenderError):
            renderizar_midia_social(content)
        slide.refresh_from_db()
        self.assertEqual(slide.rendered_image.name, old_file)
        self.assertEqual(slide.instagram_container_id, 'child-valido')

    def test_signed_url_blindagem(self):
        content = self._carousel()
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        slide = content.carousel_slides.order_by('order').first()
        signature = gerar_assinatura_carousel_slide_meta(slide)
        response = self.client.head(reverse('social_public_carousel_slide_meta_compat', args=[content.id, slide.id, signature]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertGreater(int(response['Content-Length']), 0)
        self.assertNotIn(str(settings.MEDIA_ROOT), response.get('Content-Disposition', ''))
        for args in [
            [content.id, slide.id, signature + 'x'],
            [content.id + 999, slide.id, signature],
            [content.id, slide.id + 999, signature],
        ]:
            with self.subTest(args=args):
                self.assertEqual(self.client.get(reverse('social_public_carousel_slide_meta_compat', args=args)).status_code, 404)
        with override_settings(INSTAGRAM_MEDIA_URL_TTL_SECONDS=-1):
            self.assertEqual(self.client.get(reverse('social_public_carousel_slide_meta_compat', args=[content.id, slide.id, signature])).status_code, 404)

    def test_meta_children_parent_ordem_e_media_publish(self):
        content = self._carousel(slide_count=4)
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        calls = []
        with mock.patch('social_automation.instagram._request', side_effect=self._fake_meta(calls)):
            publicar_conteudo_instagram(content)
        child_payloads = [params for _uid, method, path, params in calls if method == 'POST' and path.endswith('/media') and params.get('is_carousel_item') == 'true']
        parent_payloads = [params for _uid, method, path, params in calls if method == 'POST' and path.endswith('/media') and params.get('media_type') == 'CAROUSEL']
        publish_payloads = [params for _uid, method, path, params in calls if method == 'POST' and path.endswith('/media_publish')]
        self.assertEqual(len(child_payloads), 4)
        self.assertTrue(all(payload['is_carousel_item'] == 'true' for payload in child_payloads))
        self.assertTrue(all('/social-media/ig-carousel/' in payload['image_url'] for payload in child_payloads))
        self.assertEqual(parent_payloads[0]['children'], 'child-1,child-2,child-3,child-4')
        self.assertEqual(parent_payloads[0]['caption'], montar_caption(content))
        self.assertEqual(publish_payloads[0]['creation_id'], 'parent-1')
        self.assertNotIn('child-', publish_payloads[0]['creation_id'])

    def test_child_reutilizado_e_falha_parcial_retomada(self):
        content = self._carousel(slide_count=6)
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        calls = []
        with mock.patch('social_automation.instagram._request', side_effect=self._fake_meta(calls, fail_child_index=4)):
            with self.assertRaises(InstagramAPIError):
                publicar_conteudo_instagram(content)
        self.assertEqual(content.carousel_slides.exclude(instagram_container_id='').count(), 3)
        self.assertFalse(any(params.get('media_type') == 'CAROUSEL' for _uid, method, path, params in calls if method == 'POST' and path.endswith('/media')))
        content.refresh_from_db()
        content.status = SocialContent.Status.APROVADO
        content.erro = ''
        content.save(update_fields=['status', 'erro', 'updated_at'])
        calls.clear()
        with mock.patch('social_automation.instagram._request', side_effect=self._fake_meta(calls)):
            publicar_conteudo_instagram(content)
        child_payloads = [params for _uid, method, path, params in calls if method == 'POST' and path.endswith('/media') and params.get('is_carousel_item') == 'true']
        self.assertEqual(len(child_payloads), 3)
        self.assertEqual(content.carousel_slides.exclude(instagram_container_id='').count(), 0)

    def test_fingerprints_child_e_parent_mudam_com_midia_ordem_caption_e_conta(self):
        content = self._carousel(slide_count=3)
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        slide = content.carousel_slides.order_by('order').first()
        child_a = calculate_instagram_carousel_slide_fingerprint(slide, '178-A-CAROUSEL')
        parent_a = calculate_instagram_container_fingerprint(content, '178-A-CAROUSEL')
        self.assertNotEqual(child_a, calculate_instagram_carousel_slide_fingerprint(slide, '178-B-CAROUSEL'))
        self.assertNotEqual(parent_a, calculate_instagram_container_fingerprint(content, '178-B-CAROUSEL'))
        slide.order = 9
        slide.save(update_fields=['order', 'updated_at'])
        self.assertNotEqual(child_a, calculate_instagram_carousel_slide_fingerprint(slide, '178-A-CAROUSEL'))
        self.assertNotEqual(parent_a, calculate_instagram_container_fingerprint(content, '178-A-CAROUSEL'))
        slide.order = 1
        slide.save(update_fields=['order', 'updated_at'])
        content.hashtags = '#alterada'
        content.save(update_fields=['hashtags', 'updated_at'])
        self.assertNotEqual(parent_a, calculate_instagram_container_fingerprint(content, '178-A-CAROUSEL'))

    def test_render_novo_bem_sucedido_invalida_child_antigo(self):
        content = self._carousel()
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        slide = content.carousel_slides.order_by('order').first()
        slide.instagram_container_id = 'child-antigo'
        slide.instagram_container_fingerprint = 'hash-antigo'
        slide.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
        renderizar_midia_social(content)
        slide.refresh_from_db()
        self.assertEqual(slide.instagram_container_id, '')
        self.assertEqual(slide.instagram_container_fingerprint, '')

    def test_media_publish_ambiguo_preserva_parent_e_publicado_nao_republica(self):
        content = self._carousel()
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content)
        calls = []
        error = InstagramAPIError('timeout ambiguo', is_transient=True)
        with mock.patch('social_automation.instagram._request', side_effect=self._fake_meta(calls, publish_error=error)):
            with self.assertRaises(InstagramAPIError):
                publicar_conteudo_instagram(content)
        content.refresh_from_db()
        self.assertEqual(content.status, SocialContent.Status.ERRO)
        self.assertEqual(content.instagram_container_id, 'parent-1')
        content.status = SocialContent.Status.PUBLICADO
        content.external_post_id = 'media-ja-publicada'
        content.save(update_fields=['status', 'external_post_id', 'updated_at'])
        with self.assertRaises(InstagramPublishError):
            publicar_conteudo_instagram(content)

    def test_scheduler_tres_tipos_e_sem_fallback(self):
        expected_laila = [
            'image', 'image', 'image', 'reel', 'image', 'image', 'reel', 'image', 'image', 'reel',
            'image', 'image', 'image', 'reel', 'image', 'image', 'reel', 'image', 'image', 'reel',
        ]
        self.assertEqual(build_daily_media_plan(20, 6, 0), expected_laila)
        cases = [(8, 2, 2, 4, 2, 2), (10, 0, 3, 7, 0, 3), (10, 3, 0, 7, 3, 0), (5, 0, 0, 5, 0, 0)]
        for posts, reels, carousels, images, expected_reels, expected_carousels in cases:
            with self.subTest(posts=posts, reels=reels, carousels=carousels):
                plan = build_daily_media_plan(posts, reels, carousels)
                self.assertEqual(plan.count(SocialContent.MediaType.IMAGE), images)
                self.assertEqual(plan.count(SocialContent.MediaType.REEL), expected_reels)
                self.assertEqual(plan.count(SocialContent.MediaType.CAROUSEL), expected_carousels)
                self.assertEqual(plan, build_daily_media_plan(posts, reels, carousels))
        self.assertEqual(media_type_for_slot(0, 8, 2, 2), build_daily_media_plan(8, 2, 2)[0])

    def test_preencher_agenda_respeita_tipo_e_nao_altera_agendado_existente(self):
        now = timezone.datetime(2026, 8, 29, 7, 0, tzinfo=timezone.get_current_timezone())
        self.profile_a.horarios_publicacao = ['08:00', '10:00', '12:00', '14:00']
        self.profile_a.save(update_fields=['horarios_publicacao', 'updated_at'])
        existing = self._carousel(status=SocialContent.Status.AGENDADO)
        existing.scheduled_at = now + timedelta(hours=1)
        existing.save(update_fields=['scheduled_at', 'updated_at'])
        ready_image = SocialContent.objects.create(profile=self.profile_a, base_image=self.base_a, media_type=SocialContent.MediaType.IMAGE, frase='Imagem', status=SocialContent.Status.APROVADO)
        ready_image.final_image.save('ready-image.jpg', imagem_social('ready-image.jpg'), save=True)
        ready_carousel = self._carousel(status=SocialContent.Status.APROVADO)
        from .rendering import renderizar_midia_social

        renderizar_midia_social(ready_carousel)
        preencher_agenda(self.profile_a, now=now, days=1)
        existing.refresh_from_db()
        ready_image.refresh_from_db()
        ready_carousel.refresh_from_db()
        self.assertEqual(existing.scheduled_at, now + timedelta(hours=1))
        agendados = list(self.profile_a.contents.filter(status=SocialContent.Status.AGENDADO).order_by('scheduled_at'))
        self.assertIn(existing, agendados)
        self.assertTrue(all(content.scheduled_at for content in agendados))

    def test_estoque_deficit_e_isolamento_por_perfil(self):
        draft = self._carousel(status=SocialContent.Status.APROVADO)
        self.assertFalse(draft.final_media_ready)
        self.assertEqual(estoque_pronto_por_tipo(self.profile_a)[SocialContent.MediaType.CAROUSEL], 0)
        from .rendering import renderizar_midia_social

        renderizar_midia_social(draft)
        self.assertEqual(estoque_pronto_por_tipo(self.profile_a)[SocialContent.MediaType.CAROUSEL], 1)
        self.assertEqual(estoque_pronto(self.profile_a), 1)
        target = estoque_alvo_profile(self.profile_a)
        plan = plano_geracao_por_deficit(self.profile_a, target, 30)
        self.assertIn(SocialContent.MediaType.CAROUSEL, plan)
        self.assertEqual(estoque_pronto(self.profile_b), 0)

    @override_settings(SOCIAL_AUTOMATION_MAX_CAROUSELS_PER_TICK=1)
    def test_tick_respeita_maximo_de_carrosseis_por_lote(self):
        self.profile_a.modo_operacao = SocialProfile.ModoOperacao.AUTOMATICO
        self.profile_a.posts_por_dia = 6
        self.profile_a.reels_por_dia = 0
        self.profile_a.carousels_por_dia = 3
        self.profile_a.save(update_fields=['modo_operacao', 'posts_por_dia', 'reels_por_dia', 'carousels_por_dia', 'updated_at'])
        with mock.patch('social_automation.automation.gerar_lote_conteudos', return_value=GenerationResult(solicitados=1)) as mocked_generate:
            executar_tick_social(use_lock=False)
        media_types = mocked_generate.call_args.kwargs['media_types']
        self.assertLessEqual(media_types.count(SocialContent.MediaType.CAROUSEL), 1)

    def test_multi_perfil_publica_carrossel_com_credencial_correta_e_isola_erro(self):
        content_a = self._carousel(profile=self.profile_a, template=self.template_a)
        content_b = self._carousel(profile=self.profile_b, template=self.template_b)
        from .rendering import renderizar_midia_social

        renderizar_midia_social(content_a)
        renderizar_midia_social(content_b)
        calls = []
        with mock.patch('social_automation.instagram._request', side_effect=self._fake_meta(calls)):
            publicar_conteudo_instagram(content_a)
            publicar_conteudo_instagram(content_b)
        self.assertIn('178-A-CAROUSEL', {uid for uid, _method, _path, _params in calls})
        self.assertIn('178-B-CAROUSEL', {uid for uid, _method, _path, _params in calls})

    def test_geracao_ia_texto_cria_slides_caption_hashtags_e_usa_perfil_correto(self):
        item = GeneratedContent(
            frase='Capa curta',
            legenda='Primeiro ponto. Segundo ponto. Terceiro ponto.',
            hashtags=['obra', 'rotina'],
            tags_imagem=['carrossel'],
        )
        with mock.patch('social_automation.generation.gerar_conteudos_ia', return_value=[item]), mock.patch('social_automation.generation.moderar_conteudo', return_value=False):
            result = gerar_lote_conteudos(self.profile_a, 1, 'tema', None, media_types=[SocialContent.MediaType.CAROUSEL])
        self.assertEqual(result.criados, 1)
        content = result.conteudos[0]
        self.assertEqual(content.carousel_slides.filter(is_active=True).count(), self.profile_a.carousel_default_slide_count)
        self.assertEqual(content.carousel_slides.order_by('order').first().slide_type, SocialCarouselSlide.SlideType.COVER)
        self.assertEqual(content.carousel_slides.order_by('-order').first().slide_type, SocialCarouselSlide.SlideType.CTA)
        self.assertIn('#obra', content.hashtags)
        self.assertEqual(content.profile, self.profile_a)

    def test_image_generation_foundation(self):
        self.assertFalse(image_generation_available(self.profile_a))
        self.profile_a.ai_image_generation_enabled = True
        self.profile_a.save(update_fields=['ai_image_generation_enabled', 'updated_at'])
        with override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test'):
            self.assertTrue(image_generation_available(self.profile_a))
            self.assertFalse(image_generation_available(self.profile_b))
            prompt = build_image_generation_prompt(self.profile_a, 'Base')
            self.assertIn('Visual A', prompt)
            with self.assertRaises(SocialImageGenerationDisabled):
                generate_social_image(SocialImagePrompt(profile_id=self.profile_a.id, prompt=prompt))

    def test_regressao_image_reel_scheduler_publicacao_e_fingerprint(self):
        image_content = SocialContent.objects.create(profile=self.profile_a, base_image=self.base_a, media_type=SocialContent.MediaType.IMAGE, frase='Imagem', legenda='Legenda', status=SocialContent.Status.APROVADO)
        reel_content = SocialContent.objects.create(profile=self.profile_a, base_image=self.base_a, media_type=SocialContent.MediaType.REEL, frase='Reel', legenda='Legenda', status=SocialContent.Status.APROVADO)
        image_content.final_image.save('image-ready.jpg', imagem_social('image-ready.jpg'), save=True)
        reel_content.final_video.save('reel-ready.mp4', video_mp4_teste('reel-ready.mp4'), save=True)
        self.assertTrue(calculate_instagram_container_fingerprint(image_content, '178-A-CAROUSEL'))
        self.assertTrue(calculate_instagram_container_fingerprint(reel_content, '178-A-CAROUSEL'))
        plan = build_daily_media_plan(10, 3, 0)
        self.assertEqual(plan.count(SocialContent.MediaType.IMAGE), 7)
        self.assertEqual(plan.count(SocialContent.MediaType.REEL), 3)
        calls = []

        def fake_request(method, path, params=None, *, credentials=None):
            params = params or {}
            calls.append((method, path, params.copy()))
            if method == 'GET' and path == '178-A-CAROUSEL':
                return {'id': path, 'username': 'perfil_a_carrossel', 'account_type': 'BUSINESS'}
            if method == 'POST' and path.endswith('/media'):
                return {'id': 'container-image'}
            if method == 'GET' and path == 'container-image':
                return {'id': path, 'status_code': 'FINISHED'}
            if method == 'POST' and path.endswith('/media_publish'):
                return {'id': 'media-image'}
            if method == 'GET' and path == 'media-image':
                return {'id': 'media-image', 'permalink': 'https://instagram.test/image'}
            return {}

        with mock.patch('social_automation.instagram._request', side_effect=fake_request):
            publicar_conteudo_instagram(image_content)
        image_content.refresh_from_db()
        self.assertEqual(image_content.status, SocialContent.Status.PUBLICADO)

    def test_carrossel_publicado_nao_rerenderiza_pela_view(self):
        user = User.objects.create_user(username='staff-carousel-hardening', password='senha', is_staff=True)
        self.client.force_login(user)
        content = self._carousel(status=SocialContent.Status.PUBLICADO)
        response = self.client.post(reverse('social_automation:content_render', args=[content.id]))
        self.assertRedirects(response, reverse('social_automation:content_detail', args=[content.id]))
        self.assertContains(self.client.get(reverse('social_automation:content_detail', args=[content.id])), 'Conteudo publicado preserva a midia enviada ao Instagram.')

    def test_management_commands_de_carrossel(self):
        content = self._carousel()
        output = StringIO()
        with mock.patch('social_automation.instagram._request') as mocked_meta:
            call_command('diagnosticar_render_carrossel', content.id, stdout=output)
        self.assertFalse(mocked_meta.called)
        self.assertIn('renderizado', output.getvalue())
        output = StringIO()
        call_command('diagnosticar_mix_diario', 'perfil_a_carrossel', '2026-08-29', stdout=output)
        self.assertIn('Carrosseis planejados', output.getvalue())
        output = StringIO()
        with mock.patch('social_automation.instagram._request', side_effect=self._fake_meta([])):
            call_command('diagnosticar_container_carrossel_instagram', content.id, stdout=output)
        self.assertIn('Containers criados sem publicar', output.getvalue())


class SocialAutomationAIVisionTests(TestCase):
    def setUp(self):
        self.profile = SocialProfile.objects.create(
            nome='Perfil Generico',
            username='perfil_generico',
            horarios_publicacao=['12:00'],
            ai_image_generation_enabled=True,
            ai_image_mode=SocialProfile.AIImagePolicy.AI_WHEN_NEEDED,
            image_ai_instructions='Visual limpo e generico.',
        )
        self.image = SocialBaseImage.objects.create(
            profile=self.profile,
            arquivo=imagem_social('banco.jpg'),
            nome='Imagem banco obra limpa',
            descricao='Area segura a esquerda com assunto a direita',
            tags='obra, limpo, clean',
            text_safe_zone=SocialBaseImage.TextSafeZone.LEFT,
            subject_position=SocialBaseImage.SubjectPosition.RIGHT,
            primary_text_box_x=7,
            primary_text_box_y=20,
            primary_text_box_width=42,
            primary_text_box_height=46,
        )

    def test_media_resolver_usa_banco_quando_score_e_suficiente(self):
        result = resolve_slide_media(
            self.profile,
            media_intent='obra limpa',
            visual_intent='CLEAN',
            preferred_layout='HERO_LEFT',
            aspect_ratio='SQUARE',
            media_required=True,
        )
        self.assertEqual(result.status, STATUS_SELECTED)
        self.assertEqual(result.image, self.image)

    def test_media_resolver_solicita_geracao_quando_banco_nao_casa(self):
        result = resolve_slide_media(
            self.profile,
            media_intent='laboratorio espacial futurista',
            visual_intent='DRAMATIC',
            preferred_layout='HERO_RIGHT',
            aspect_ratio='SQUARE',
            media_required=True,
        )
        self.assertEqual(result.status, STATUS_NEEDS_GENERATION)

    def test_slide_sem_midia_obrigatoria_vira_full_text(self):
        result = resolve_slide_media(self.profile, media_required=False)
        self.assertEqual(result.status, STATUS_FULL_TEXT)

    @override_settings(SOCIAL_IMAGE_ANALYSIS_MIN_CONFIDENCE=0.6)
    def test_persist_image_analysis_preserva_manual_e_cria_regiao_ia(self):
        SocialBaseImageProtectedRegion.objects.create(image=self.image, x=0.1, y=0.1, width=0.2, height=0.2)
        result = ImageAnalysisResult(
            subject_position=SocialBaseImage.SubjectPosition.RIGHT,
            focal_x=0.7,
            focal_y=0.4,
            safe_zones=[SocialBaseImage.TextSafeZone.LEFT],
            protected_regions=[{'x': 0.55, 'y': 0.15, 'width': 0.35, 'height': 0.60, 'region_type': 'subject', 'confidence': 0.9}],
            confidence=0.85,
            raw={'ok': True},
        )
        persist_image_analysis(self.image, result, model='vision-test')
        self.image.refresh_from_db()
        self.assertEqual(self.image.analysis_model, 'vision-test')
        self.assertEqual(self.image.protected_regions.filter(source=SocialBaseImageProtectedRegion.Source.MANUAL).count(), 1)
        self.assertEqual(self.image.protected_regions.filter(source=SocialBaseImageProtectedRegion.Source.AI_ANALYSIS).count(), 1)

    def test_policy_bank_only_bloqueia_generate_social_image(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.BANK_ONLY
        self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
        with override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test'):
            with self.assertRaises(SocialImageGenerationDisabled):
                generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Imagem teste'))

    def _fake_image_response(self, nome='generated.jpg'):
        image = Image.new('RGB', (1024, 1024), color='navy')
        buffer = BytesIO()
        image.save(buffer, format='JPEG')
        payload = base64.b64encode(buffer.getvalue()).decode('ascii')
        data = type('Data', (), {'b64_json': payload})()
        return type('Response', (), {'data': [data], 'id': nome})()

    def _provider(self, side_effect=None):
        generate = mock.Mock(side_effect=side_effect) if side_effect is not None else mock.Mock(return_value=self._fake_image_response())
        return type('Client', (), {'images': type('Images', (), {'generate': generate})()})(), generate

    def _blueprint(self, media_required=True, count=6, all_required=False):
        slides = []
        for index in range(1, count + 1):
            slides.append(
                GeneratedCarouselSlide(
                    order=index,
                    slide_type=SocialCarouselSlide.SlideType.COVER if index == 1 else SocialCarouselSlide.SlideType.CONTENT,
                    title=f'Slide {index}',
                    body='Texto curto',
                    visual_intent='CLEAN',
                    media_intent='midia inexistente',
                    media_required=media_required if (all_required or index == 1) else False,
                    preferred_layout='HERO_LEFT' if index == 1 else 'FULL_TEXT',
                )
            )
        return GeneratedCarouselBlueprint(topic='Tema', hook='Hook seguro', caption='Legenda segura', hashtags=['teste'], slides=slides)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test')
    def test_feature_flag_desligada_bloqueia_antes_do_provider(self):
        self.profile.ai_image_generation_enabled = False
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.save(update_fields=['ai_image_generation_enabled', 'ai_image_mode', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            with self.assertRaises(SocialImageGenerationDisabled):
                generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt teste'))
        self.assertEqual(provider.call_count, 0)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test')
    def test_policy_matrix_nao_chama_provider_quando_nao_deve(self):
        for policy in [SocialProfile.AIImagePolicy.NONE, SocialProfile.AIImagePolicy.BANK_ONLY]:
            with self.subTest(policy=policy):
                self.profile.ai_image_mode = policy
                self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
                client, provider = self._provider()
                with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
                    with self.assertRaises(SocialImageGenerationDisabled):
                        generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt=f'Prompt {policy}'))
                self.assertEqual(provider.call_count, 0)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY=2)
    def test_quota_diaria_bloqueia_antes_da_api(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.ai_generated_images_reusable = False
        self.profile.ai_image_daily_limit = 2
        self.profile.save(update_fields=['ai_image_mode', 'ai_generated_images_reusable', 'ai_image_daily_limit', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt 1'))
            generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt 2'))
            with self.assertRaises(SocialImageGenerationDisabled):
                generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt 3'))
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(SocialBaseImage.objects.filter(profile=self.profile, source=SocialBaseImage.Source.AI).count(), 2)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', OPENAI_SOCIAL_IMAGE_QUALITY='standard')
    def test_idempotencia_reutiliza_request_igual_e_request_diferente_gera(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            first = generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Mesmo prompt', aspect_ratio='SQUARE'))
            second = generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Mesmo prompt', aspect_ratio='SQUARE'))
            third = generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Outro prompt', aspect_ratio='SQUARE'))
        self.assertEqual(first.id, second.id)
        self.assertNotEqual(first.id, third.id)
        self.assertEqual(provider.call_count, 2)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='modelo-a', OPENAI_SOCIAL_IMAGE_QUALITY='standard')
    def test_idempotencia_considera_modelo_e_qualidade(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            first = generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Mesmo prompt'))
            with override_settings(OPENAI_SOCIAL_IMAGE_MODEL='modelo-b'):
                second = generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Mesmo prompt'))
            with override_settings(OPENAI_SOCIAL_IMAGE_QUALITY='hd'):
                third = generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Mesmo prompt'))
        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.id, third.id)
        self.assertEqual(provider.call_count, 3)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test')
    def test_erro_provider_registra_usage_sem_criar_imagem(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
        client, provider = self._provider(side_effect=TimeoutError('timeout controlado key-test'))
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            with self.assertRaises(OpenAIUnavailable):
                generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt timeout'))
        self.assertEqual(provider.call_count, 1)
        self.assertFalse(SocialBaseImage.objects.filter(profile=self.profile, source=SocialBaseImage.Source.AI).exists())
        usage = SocialAIUsage.objects.get(profile=self.profile, operation=SocialAIUsage.Operation.IMAGE_GENERATION)
        self.assertFalse(usage.success)
        self.assertNotIn('key-test', usage.error)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test')
    def test_erros_429_e_5xx_sao_controlados_sem_retry(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
        client, provider = self._provider(side_effect=[Exception('HTTP 429 rate limit'), Exception('HTTP 500 servidor')])
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            with self.assertRaises(OpenAIUnavailable):
                generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt 429'))
            with self.assertRaises(OpenAIUnavailable):
                generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt 500'))
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(SocialAIUsage.objects.filter(profile=self.profile, success=False).count(), 2)
        self.assertFalse(SocialBaseImage.objects.filter(profile=self.profile, source=SocialBaseImage.Source.AI).exists())

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', SOCIAL_AI_IMAGE_MAX_BYTES=10)
    def test_resposta_acima_do_limite_nao_cria_imagem_utilizavel(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            with self.assertRaises(OpenAIUnavailable):
                generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt grande'))
        self.assertEqual(provider.call_count, 1)
        self.assertFalse(SocialBaseImage.objects.filter(profile=self.profile, source=SocialBaseImage.Source.AI).exists())

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-2', OPENAI_SOCIAL_IMAGE_QUALITY='medium')
    def test_gpt_image_2_nao_envia_response_format_e_salva_b64(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            image = generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt='Prompt gpt-image-2', aspect_ratio='SQUARE'))
        self.assertEqual(provider.call_count, 1)
        kwargs = provider.call_args.kwargs
        self.assertEqual(kwargs['model'], 'gpt-image-2')
        self.assertEqual(kwargs['quality'], 'medium')
        self.assertEqual(kwargs['size'], '1024x1024')
        self.assertEqual(kwargs['n'], 1)
        self.assertNotIn('response_format', kwargs)
        self.assertEqual(image.source, SocialBaseImage.Source.AI)
        self.assertEqual(image.ai_model, 'gpt-image-2')
        self.assertTrue(image.arquivo.name)
        self.assertNotIn('b64_json', image.analysis_metadata)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-2', OPENAI_SOCIAL_IMAGE_QUALITY='medium')
    def test_resposta_sem_data_ou_sem_b64_falha_controlada(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.ai_generated_images_reusable = False
        self.profile.save(update_fields=['ai_image_mode', 'ai_generated_images_reusable', 'updated_at'])
        responses = [
            type('Response', (), {'data': [], 'id': 'sem-data'})(),
            type('Response', (), {'data': [type('Data', (), {})()], 'id': 'sem-b64'})(),
        ]
        with mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            for index, response in enumerate(responses, start=1):
                client, provider = self._provider(side_effect=[response])
                with mock.patch('social_automation.image_generation._client', return_value=client):
                    with self.assertRaises(OpenAIUnavailable):
                        generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt=f'Prompt resposta incompleta {index}'))
                self.assertEqual(provider.call_count, 1)
        self.assertFalse(SocialBaseImage.objects.filter(profile=self.profile, source=SocialBaseImage.Source.AI).exists())

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test')
    def test_respostas_invalidas_nao_criam_imagem_utilizavel(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.ai_generated_images_reusable = False
        self.profile.save(update_fields=['ai_image_mode', 'ai_generated_images_reusable', 'updated_at'])
        invalid_payloads = [
            type('Response', (), {'data': [type('Data', (), {'b64_json': ''})()], 'id': 'empty'})(),
            type('Response', (), {'data': [type('Data', (), {'b64_json': 'base64-invalido!'})()], 'id': 'bad64'})(),
            type('Response', (), {'data': [type('Data', (), {'b64_json': base64.b64encode(b'nao-e-imagem').decode('ascii')})()], 'id': 'badimage'})(),
        ]
        with mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            for index, response in enumerate(invalid_payloads, start=1):
                client, provider = self._provider(side_effect=[response])
                with mock.patch('social_automation.image_generation._client', return_value=client):
                    with self.assertRaises(OpenAIUnavailable):
                        generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt=f'Prompt invalido {index}'))
                self.assertEqual(provider.call_count, 1)
        self.assertFalse(SocialBaseImage.objects.filter(profile=self.profile, source=SocialBaseImage.Source.AI).exists())

    @override_settings(SOCIAL_IMAGE_ANALYSIS_MIN_CONFIDENCE=0.8)
    def test_analysis_confidence_e_bbox_invalida_nao_persistem_regiao(self):
        low = ImageAnalysisResult(confidence=0.4, protected_regions=[{'x': 0.1, 'y': 0.1, 'width': 0.2, 'height': 0.2, 'region_type': 'subject', 'confidence': 0.9}], raw={})
        persist_image_analysis(self.image, low, model='vision-test')
        self.assertEqual(self.image.protected_regions.count(), 0)
        invalid = ImageAnalysisResult(
            confidence=0.95,
            protected_regions=[{'x': -0.2, 'y': 0.1, 'width': 1.8, 'height': 0.2, 'region_type': 'subject', 'confidence': 0.95}],
            raw={},
        )
        persist_image_analysis(self.image, invalid, model='vision-test')
        self.assertEqual(self.image.protected_regions.count(), 0)

    def test_resolver_isola_midia_por_perfil_e_penaliza_uso_recente(self):
        other_profile = SocialProfile.objects.create(nome='Outro', username='outro', horarios_publicacao=['13:00'])
        other = SocialBaseImage.objects.create(profile=other_profile, arquivo=imagem_social('outra.jpg'), nome='Imagem obra limpa', tags='obra, limpo')
        recent = SocialBaseImage.objects.create(
            profile=self.profile,
            arquivo=imagem_social('recente.jpg'),
            nome='Imagem obra limpa recente',
            tags='obra, limpo',
            text_safe_zone=SocialBaseImage.TextSafeZone.LEFT,
            subject_position=SocialBaseImage.SubjectPosition.RIGHT,
            vezes_usada=20,
            ultima_utilizacao=timezone.now(),
        )
        result = resolve_slide_media(self.profile, media_intent='obra limpa', visual_intent='CLEAN', preferred_layout='HERO_LEFT', media_required=True)
        self.assertNotEqual(result.image, other)
        self.assertNotEqual(result.image, recent)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', SOCIAL_MEDIA_MATCH_MIN_SCORE=88)
    def test_multi_perfil_isola_policy_prompt_midia_quota_e_usage(self):
        profile_b = SocialProfile.objects.create(
            nome='Perfil B',
            username='perfil_b',
            horarios_publicacao=['13:00'],
            ai_image_generation_enabled=False,
            ai_image_mode=SocialProfile.AIImagePolicy.AI_WHEN_NEEDED,
            ai_image_daily_limit=1,
            image_ai_instructions='Instrucoes exclusivas B.',
        )
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.ai_image_daily_limit = 1
        self.profile.image_ai_instructions = 'Instrucoes exclusivas A.'
        self.profile.save(update_fields=['ai_image_mode', 'ai_image_daily_limit', 'image_ai_instructions', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            generated = generate_social_image(SocialImagePrompt(profile_id=self.profile.id, prompt=build_image_generation_prompt(self.profile, 'Prompt A')))
            with self.assertRaises(SocialImageGenerationDisabled):
                generate_social_image(SocialImagePrompt(profile_id=profile_b.id, prompt=build_image_generation_prompt(profile_b, 'Prompt B')))
        self.assertEqual(provider.call_count, 1)
        prompt_sent = provider.call_args.kwargs['prompt']
        self.assertIn('Instrucoes exclusivas A.', prompt_sent)
        self.assertNotIn('Instrucoes exclusivas B.', prompt_sent)
        self.assertEqual(generated.profile, self.profile)
        self.assertEqual(SocialAIUsage.objects.filter(profile=self.profile, success=True).count(), 1)
        self.assertEqual(SocialAIUsage.objects.filter(profile=profile_b).count(), 0)
        result_b = resolve_slide_media(profile_b, media_intent='ia', visual_intent='CLEAN', preferred_layout='HERO_LEFT', media_required=True)
        self.assertNotEqual(result_b.image, generated)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', SOCIAL_MEDIA_MATCH_MIN_SCORE=99)
    def test_carrossel_autonomo_gera_uma_imagem_e_nao_chama_meta(self):
        from .autonomous_carousel import gerar_carrossel_autonomo

        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_WHEN_NEEDED
        self.profile.ai_generated_images_reusable = False
        self.profile.save(update_fields=['ai_image_mode', 'ai_generated_images_reusable', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.autonomous_carousel.gerar_carrossel_blueprint_ia', return_value=self._blueprint(media_required=True)), mock.patch('social_automation.autonomous_carousel.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.autonomous_carousel.analyze_social_image'), mock.patch('social_automation.instagram._request') as meta:
            result = gerar_carrossel_autonomo(self.profile, tema='teste', slides=6)
        self.assertEqual(provider.call_count, 1)
        self.assertFalse(meta.called)
        self.assertEqual(result.content.status, SocialContent.Status.RASCUNHO)
        self.assertTrue(result.content.final_media_ready)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', SOCIAL_MEDIA_MATCH_MIN_SCORE=99)
    def test_carrossel_sem_midia_required_nao_gasta_ia(self):
        from .autonomous_carousel import gerar_carrossel_autonomo

        client, provider = self._provider()
        with mock.patch('social_automation.autonomous_carousel.gerar_carrossel_blueprint_ia', return_value=self._blueprint(media_required=False)), mock.patch('social_automation.autonomous_carousel.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.instagram._request') as meta:
            result = gerar_carrossel_autonomo(self.profile, tema='teste', slides=6)
        self.assertEqual(provider.call_count, 0)
        self.assertFalse(meta.called)
        self.assertEqual(result.full_text_slides, 6)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test')
    def test_falha_parcial_preserva_conteudo_sem_pronto(self):
        from .autonomous_carousel import gerar_carrossel_autonomo

        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.save(update_fields=['ai_image_mode', 'updated_at'])
        blueprint = self._blueprint(media_required=True, count=3)
        blueprint.slides[1] = GeneratedCarouselSlide(2, SocialCarouselSlide.SlideType.CONTENT, 'Slide 2', 'Texto', 'CLEAN', 'midia dois', True, 'HERO_LEFT')
        client, provider = self._provider(side_effect=[self._fake_image_response('one'), TimeoutError('timeout')])
        with mock.patch('social_automation.autonomous_carousel.gerar_carrossel_blueprint_ia', return_value=blueprint), mock.patch('social_automation.autonomous_carousel.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation._client', return_value=client):
            result = gerar_carrossel_autonomo(self.profile, tema='teste', slides=3)
        self.assertEqual(provider.call_count, 2)
        self.assertIsNotNone(result.content)
        self.assertFalse(result.content.final_media_ready)
        self.assertTrue(result.content.erro)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', SOCIAL_MEDIA_MATCH_MIN_SCORE=99)
    def test_carrossel_com_duas_midias_requeridas_gera_duas_imagens(self):
        from .autonomous_carousel import gerar_carrossel_autonomo

        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.ai_generated_images_reusable = False
        self.profile.ai_image_daily_limit = 5
        self.profile.save(update_fields=['ai_image_mode', 'ai_generated_images_reusable', 'ai_image_daily_limit', 'updated_at'])
        blueprint = self._blueprint(media_required=True, count=6)
        blueprint.slides[3] = GeneratedCarouselSlide(4, SocialCarouselSlide.SlideType.CONTENT, 'Slide 4', 'Texto', 'CLEAN', 'midia quatro', True, 'HERO_LEFT')
        client, provider = self._provider()
        with mock.patch('social_automation.autonomous_carousel.gerar_carrossel_blueprint_ia', return_value=blueprint), mock.patch('social_automation.autonomous_carousel.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.autonomous_carousel.analyze_social_image'), mock.patch('social_automation.instagram._request') as meta:
            result = gerar_carrossel_autonomo(self.profile, tema='teste', slides=6)
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(result.generated_images, 2)
        self.assertFalse(meta.called)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', SOCIAL_MEDIA_MATCH_MIN_SCORE=99, SOCIAL_AI_IMAGE_MAX_PER_TICK=2, SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY=99)
    def test_runaway_20_conteudos_10_slides_respeita_maximo_por_tick(self):
        from .autonomous_carousel import gerar_carrossel_autonomo

        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.ai_generated_images_reusable = False
        self.profile.ai_image_daily_limit = 99
        self.profile.save(update_fields=['ai_image_mode', 'ai_generated_images_reusable', 'ai_image_daily_limit', 'updated_at'])
        client, provider = self._provider()
        with mock.patch('social_automation.autonomous_carousel.gerar_carrossel_blueprint_ia', return_value=self._blueprint(media_required=True, count=10, all_required=True)), mock.patch('social_automation.autonomous_carousel.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.autonomous_carousel.analyze_social_image'), mock.patch('social_automation.instagram._request'):
            for _ in range(20):
                gerar_carrossel_autonomo(self.profile, tema='runaway', slides=10)
        self.assertLessEqual(provider.call_count, 2)
        self.assertEqual(SocialAIUsage.objects.filter(profile=self.profile, operation=SocialAIUsage.Operation.IMAGE_GENERATION, success=True).count(), 2)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test')
    def test_command_diagnostico_dry_run_nao_chama_openai_e_generate_gera_uma(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_ALWAYS
        self.profile.ai_generated_images_reusable = False
        self.profile.save(update_fields=['ai_image_mode', 'ai_generated_images_reusable', 'updated_at'])
        client, provider = self._provider()
        output = StringIO()
        with mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False):
            call_command('diagnosticar_geracao_imagem_social', self.profile.username, stdout=output)
            self.assertEqual(provider.call_count, 0)
            call_command('diagnosticar_geracao_imagem_social', self.profile.username, '--generate', stdout=output)
        self.assertEqual(provider.call_count, 1)

    @override_settings(OPENAI_API_KEY='key-test', OPENAI_SOCIAL_IMAGE_MODEL='gpt-image-test', SOCIAL_MEDIA_MATCH_MIN_SCORE=99)
    def test_command_gerar_carrossel_ia_cria_rascunho_sem_meta(self):
        self.profile.ai_image_mode = SocialProfile.AIImagePolicy.AI_WHEN_NEEDED
        self.profile.ai_generated_images_reusable = False
        self.profile.save(update_fields=['ai_image_mode', 'ai_generated_images_reusable', 'updated_at'])
        client, provider = self._provider()
        output = StringIO()
        with mock.patch('social_automation.autonomous_carousel.gerar_carrossel_blueprint_ia', return_value=self._blueprint(media_required=True)), mock.patch('social_automation.autonomous_carousel.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation.moderar_conteudo', return_value=False), mock.patch('social_automation.image_generation._client', return_value=client), mock.patch('social_automation.autonomous_carousel.analyze_social_image'), mock.patch('social_automation.instagram._request') as meta:
            call_command('gerar_carrossel_ia', self.profile.username, '--tema=teste', '--slides=6', stdout=output)
        self.assertEqual(provider.call_count, 1)
        self.assertFalse(meta.called)
        self.assertTrue(SocialContent.objects.filter(profile=self.profile, media_type=SocialContent.MediaType.CAROUSEL, status=SocialContent.Status.RASCUNHO).exists())

    def test_perfil_novo_nasce_com_ia_visual_desligada(self):
        profile = SocialProfile.objects.create(nome='Novo', username='novo', horarios_publicacao=['10:00'])
        self.assertFalse(profile.ai_image_generation_enabled)
        self.assertEqual(profile.ai_image_policy, SocialProfile.AIImagePolicy.NONE)
