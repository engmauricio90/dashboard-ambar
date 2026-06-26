import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from obras.models import Obra

from .models import DiarioObra, EfetivoDiario, HistoricoDiario


class DiarioObraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='engenheiro', password='senha-forte-123')
        self.user.groups.add(Group.objects.get_or_create(name='Engenharia')[0])
        self.client.force_login(self.user)
        self.obra = Obra.objects.create(nome_obra='Obra Diario', cliente='Cliente X')

    def _management(self, prefix, total='0'):
        return {
            f'{prefix}-TOTAL_FORMS': total,
            f'{prefix}-INITIAL_FORMS': '0',
            f'{prefix}-MIN_NUM_FORMS': '0',
            f'{prefix}-MAX_NUM_FORMS': '1000',
        }

    def _post_data(self):
        data = {
            'obra': self.obra.id,
            'data': '2026-05-28',
            'responsavel_preenchimento': 'Eng. Responsavel',
            'responsavel_tecnico': 'Resp. tecnico',
            'condicao_climatica': DiarioObra.CLIMA_ENSOLARADO,
            'turno': DiarioObra.TURNO_INTEGRAL,
            'situacao_obra': DiarioObra.SITUACAO_ANDAMENTO,
            'descricao_servicos': 'Execucao de drenagem e pavimentacao.',
            'observacoes': '',
            'ocorrencias_interferencias': '',
            'pendencias': '',
            'orientacoes': '',
            'houve_visita': '',
            'visitante_nome': '',
            'status': DiarioObra.STATUS_RASCUNHO,
        }
        for prefix in ['efetivos', 'equipamentos', 'ocorrencias', 'checklist', 'fotos']:
            data.update(self._management(prefix))
        return data

    def test_cria_diario_rapido(self):
        response = self.client.post(reverse('novo_diario'), self._post_data())

        diario = DiarioObra.objects.get()
        self.assertRedirects(response, reverse('detalhe_diario', args=[diario.id]))
        self.assertEqual(diario.status, DiarioObra.STATUS_RASCUNHO)
        self.assertEqual(diario.historico.first().acao, HistoricoDiario.ACAO_CRIADO)

    def test_linha_vazia_de_ocorrencia_nao_bloqueia_salvamento(self):
        data = self._post_data()
        data.update(
            {
                'ocorrencias-TOTAL_FORMS': '1',
                'ocorrencias-0-tipo': 'chuva',
                'ocorrencias-0-descricao': '',
                'ocorrencias-0-impacto_prazo': 'nao',
                'ocorrencias-0-impacto_financeiro': 'nao',
                'ocorrencias-0-providencia': '',
                'ocorrencias-0-responsavel_providencia': '',
                'ocorrencias-0-prazo_solucao': '',
                'ocorrencias-0-status': 'aberta',
            }
        )

        response = self.client.post(reverse('novo_diario'), data)

        diario = DiarioObra.objects.get()
        self.assertRedirects(response, reverse('detalhe_diario', args=[diario.id]))
        self.assertEqual(diario.ocorrencias.count(), 0)

    def test_impede_duplicidade_por_obra_e_data(self):
        DiarioObra.objects.create(
            obra=self.obra,
            data=date(2026, 5, 28),
            responsavel_preenchimento='Eng. Responsavel',
        )

        response = self.client.post(reverse('novo_diario'), self._post_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ja existe diario para esta obra nesta data.')
        self.assertEqual(DiarioObra.objects.count(), 1)

    def test_adiciona_efetivo_por_funcao_e_quantidade(self):
        diario = DiarioObra.objects.create(
            obra=self.obra,
            data=date(2026, 5, 28),
            responsavel_preenchimento='Eng. Responsavel',
            descricao_servicos='Servico executado',
        )
        EfetivoDiario.objects.create(
            diario=diario,
            funcao='servente',
            quantidade=2,
        )

        diario.refresh_from_db()
        self.assertEqual(diario.total_efetivo, 2)

    def test_finaliza_diario(self):
        diario = DiarioObra.objects.create(
            obra=self.obra,
            data=date(2026, 5, 28),
            responsavel_preenchimento='Eng. Responsavel',
            condicao_climatica=DiarioObra.CLIMA_ENSOLARADO,
            situacao_obra=DiarioObra.SITUACAO_ANDAMENTO,
            descricao_servicos='Servico executado',
        )

        response = self.client.post(reverse('finalizar_diario', args=[diario.id]))

        self.assertRedirects(response, reverse('detalhe_diario', args=[diario.id]))
        diario.refresh_from_db()
        self.assertEqual(diario.status, DiarioObra.STATUS_FINALIZADO)

    def test_bloqueia_edicao_de_diario_finalizado_para_engenheiro(self):
        diario = DiarioObra.objects.create(
            obra=self.obra,
            data=date(2026, 5, 28),
            responsavel_preenchimento='Eng. Responsavel',
            status=DiarioObra.STATUS_FINALIZADO,
        )

        response = self.client.get(reverse('editar_diario', args=[diario.id]))

        self.assertRedirects(response, reverse('detalhe_diario', args=[diario.id]))

    def test_pdf_responde_pdf(self):
        diario = DiarioObra.objects.create(
            obra=self.obra,
            data=date(2026, 5, 28),
            responsavel_preenchimento='Eng. Responsavel',
            condicao_climatica=DiarioObra.CLIMA_ENSOLARADO,
            situacao_obra=DiarioObra.SITUACAO_ANDAMENTO,
            descricao_servicos='Servico executado',
        )

        response = self.client.get(reverse('diario_pdf', args=[diario.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_foto_do_diario_carrega_pela_url_de_media(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                diario = DiarioObra.objects.create(
                    obra=self.obra,
                    data=date(2026, 5, 28),
                    responsavel_preenchimento='Eng. Responsavel',
                    descricao_servicos='Servico executado',
                )
                gif = (
                    b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00'
                    b'\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
                )
                upload = SimpleUploadedFile('diario.gif', gif, content_type='image/gif')
                foto = diario.fotos.create(imagem=upload, legenda='Foto da obra', uploaded_by=self.user)

                response = self.client.get(foto.imagem.url)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], 'image/gif')
                response.close()

    def test_edita_diario_com_foto_existente_sem_reenviar_arquivo(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                diario = DiarioObra.objects.create(
                    obra=self.obra,
                    data=date(2026, 5, 28),
                    responsavel_preenchimento='Eng. Responsavel',
                    condicao_climatica=DiarioObra.CLIMA_ENSOLARADO,
                    turno=DiarioObra.TURNO_INTEGRAL,
                    situacao_obra=DiarioObra.SITUACAO_ANDAMENTO,
                    descricao_servicos='Servico executado',
                )
                gif = (
                    b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00'
                    b'\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
                )
                upload = SimpleUploadedFile('diario.gif', gif, content_type='image/gif')
                foto = diario.fotos.create(imagem=upload, legenda='Foto original', uploaded_by=self.user)
                data = {
                    'obra': self.obra.id,
                    'data': '2026-05-28',
                    'responsavel_preenchimento': 'Eng. Responsavel',
                    'responsavel_tecnico': '',
                    'condicao_climatica': DiarioObra.CLIMA_ENSOLARADO,
                    'turno': DiarioObra.TURNO_INTEGRAL,
                    'situacao_obra': DiarioObra.SITUACAO_ANDAMENTO,
                    'descricao_servicos': 'Servico editado',
                    'observacoes': '',
                    'ocorrencias_interferencias': '',
                    'pendencias': '',
                    'orientacoes': '',
                    'houve_visita': '',
                    'visitante_nome': '',
                    'status': DiarioObra.STATUS_RASCUNHO,
                    'fotos-TOTAL_FORMS': '1',
                    'fotos-INITIAL_FORMS': '1',
                    'fotos-MIN_NUM_FORMS': '0',
                    'fotos-MAX_NUM_FORMS': '1000',
                    'fotos-0-id': foto.id,
                    'fotos-0-legenda': 'Foto mantida',
                    'fotos-0-DELETE': '',
                }
                for prefix in ['efetivos', 'equipamentos', 'ocorrencias', 'checklist']:
                    data.update(self._management(prefix))

                response = self.client.post(reverse('editar_diario', args=[diario.id]), data)

                self.assertRedirects(response, reverse('detalhe_diario', args=[diario.id]))
                foto.refresh_from_db()
                self.assertEqual(foto.legenda, 'Foto mantida')
                self.assertTrue(foto.imagem.name)

    def test_lista_diarios_por_obra(self):
        DiarioObra.objects.create(
            obra=self.obra,
            data=date(2026, 5, 28),
            responsavel_preenchimento='Eng. Responsavel',
        )

        response = self.client.get(reverse('lista_diarios_obra', args=[self.obra.id]))

        self.assertContains(response, 'Obra Diario')
        self.assertContains(response, 'Eng. Responsavel')
