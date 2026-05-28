from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from obras.models import Obra

from .models import DiarioObra, EfetivoDiario, FrenteServicoDiario, HistoricoDiario


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
        for prefix in ['efetivos', 'equipamentos', 'materiais', 'ocorrencias', 'checklist', 'fotos']:
            data.update(self._management(prefix))
        data.update(self._management('frentes', '1'))
        data.update(
            {
                'frentes-0-nome': 'Rede pluvial',
                'frentes-0-descricao': 'Assentamento de tubos.',
                'frentes-0-local_trecho': 'Trecho 1',
                'frentes-0-percentual_executado': '35.50',
                'frentes-0-observacoes': '',
                'frentes-0-situacao': FrenteServicoDiario.SITUACAO_EM_EXECUCAO,
            }
        )
        return data

    def test_cria_diario_com_frente_de_servico(self):
        response = self.client.post(reverse('novo_diario'), self._post_data())

        diario = DiarioObra.objects.get()
        self.assertRedirects(response, reverse('detalhe_diario', args=[diario.id]))
        self.assertEqual(diario.status, DiarioObra.STATUS_RASCUNHO)
        self.assertEqual(diario.frentes.count(), 1)
        self.assertEqual(diario.historico.first().acao, HistoricoDiario.ACAO_CRIADO)

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

    def test_adiciona_efetivo_e_calcula_horas(self):
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
            horario_entrada=time(8, 0),
            horario_saida=time(12, 0),
        )

        diario.refresh_from_db()
        self.assertEqual(diario.total_efetivo, 2)
        self.assertEqual(diario.total_horas_efetivo, Decimal('8'))

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

    def test_lista_diarios_por_obra(self):
        DiarioObra.objects.create(
            obra=self.obra,
            data=date(2026, 5, 28),
            responsavel_preenchimento='Eng. Responsavel',
        )

        response = self.client.get(reverse('lista_diarios_obra', args=[self.obra.id]))

        self.assertContains(response, 'Obra Diario')
        self.assertContains(response, 'Eng. Responsavel')
