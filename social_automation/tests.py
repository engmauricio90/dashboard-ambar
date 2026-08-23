from datetime import timedelta
from io import BytesIO, StringIO
import os
from pathlib import Path
import tempfile
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
from .generation import gerar_lote_conteudos
from .image_selection import selecionar_imagem_base
from .instagram import (
    InstagramAPIError,
    MEDIA_SIGNING_SALT,
    PUBLICADO_INSTAGRAM,
    gerar_token_midia_temporaria,
    publicar_conteudo_instagram,
    validar_token_midia_temporaria,
)
from .rendering import SocialRenderError, renderizar_conteudo_social
from .rendering import _layout_text, _region


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
        b''.join(response.streaming_content)
        response.close()

        response = self.client.get(reverse('social_public_final_image', args=['token-invalido']))
        self.assertEqual(response.status_code, 404)

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
