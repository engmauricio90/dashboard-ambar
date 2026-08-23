from datetime import timedelta
from io import StringIO
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from empresas.models import Empresa, UsuarioEmpresa

from .models import SocialBaseImage, SocialContent, SocialContentEvent, SocialProfile


User = get_user_model()


def imagem_teste(nome='base.jpg'):
    buffer = StringIO()
    image = Image.new('RGB', (10, 10), color='white')
    bytes_buffer = __import__('io').BytesIO()
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
