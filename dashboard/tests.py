from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from obras.models import AditivoContrato, DespesaObra, ImpostoNotaFiscal, NotaFiscal, Obra, RetencaoNotaFiscal


class DashboardHomeTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='diretor', password='senha-forte-123')
        self.client.force_login(self.user)

    def test_dashboard_exibe_totais_reais_e_alertas(self):
        obra_ok = Obra.objects.create(
            nome_obra='Obra Azul',
            cliente='Cliente A',
            valor_contrato=Decimal('1000.00'),
            projecao_despesa=Decimal('400.00'),
        )
        obra_alerta = Obra.objects.create(
            nome_obra='Obra Vermelha',
            cliente='Cliente B',
            valor_contrato=Decimal('500.00'),
            projecao_despesa=Decimal('450.00'),
        )

        AditivoContrato.objects.create(
            obra=obra_ok,
            data_referencia=date(2026, 4, 20),
            descricao='Aditivo 1',
            valor=Decimal('200.00'),
        )

        nota_ok = NotaFiscal.objects.create(
            obra=obra_ok,
            numero='NF-100',
            data_emissao=date(2026, 4, 20),
            valor_bruto=Decimal('600.00'),
            status='emitida',
        )
        RetencaoNotaFiscal.objects.create(
            nota_fiscal=nota_ok,
            tipo='inss',
            valor=Decimal('20.00'),
        )
        ImpostoNotaFiscal.objects.create(
            nota_fiscal=nota_ok,
            tipo='simples',
            valor=Decimal('30.00'),
        )
        DespesaObra.objects.create(
            obra=obra_ok,
            data_referencia=date(2026, 4, 20),
            categoria='material',
            descricao='Compra de insumos',
            valor=Decimal('200.00'),
        )

        nota_alerta = NotaFiscal.objects.create(
            obra=obra_alerta,
            numero='NF-200',
            data_emissao=date(2026, 4, 20),
            valor_bruto=Decimal('100.00'),
            status='emitida',
        )
        RetencaoNotaFiscal.objects.create(
            nota_fiscal=nota_alerta,
            tipo='iss',
            valor=Decimal('10.00'),
        )
        ImpostoNotaFiscal.objects.create(
            nota_fiscal=nota_alerta,
            tipo='iss',
            valor=Decimal('5.00'),
        )
        DespesaObra.objects.create(
            obra=obra_alerta,
            data_referencia=date(2026, 4, 20),
            categoria='terceiro',
            descricao='Servico terceirizado',
            valor=Decimal('180.00'),
        )

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard Geral')
        self.assertContains(response, 'R$ 1.500,00')
        self.assertContains(response, 'R$ 200,00')
        self.assertContains(response, 'R$ 700,00')
        self.assertContains(response, 'R$ 35,00')
        self.assertContains(response, 'R$ 30,00')
        self.assertContains(response, 'R$ 635,00')
        self.assertContains(response, 'R$ 380,00')
        self.assertContains(response, 'Obra Vermelha')
        self.assertContains(response, 'graficoOperacional')
        self.assertIn('grafico_operacional', response.context)
        self.assertIn('grafico_resultado_real', response.context)
        self.assertIn('grafico_status', response.context)
        self.assertEqual(response.context['quantidade_obras_em_alerta'], 1)

    def test_dashboard_ordena_obras_por_resultado_real(self):
        obra_melhor = Obra.objects.create(nome_obra='Obra Melhor', valor_contrato=Decimal('1000.00'))
        obra_pior = Obra.objects.create(nome_obra='Obra Pior', valor_contrato=Decimal('1000.00'))

        NotaFiscal.objects.create(
            obra=obra_melhor,
            numero='NF-1',
            data_emissao=date(2026, 4, 20),
            valor_bruto=Decimal('500.00'),
            status='emitida',
        )
        NotaFiscal.objects.create(
            obra=obra_pior,
            numero='NF-2',
            data_emissao=date(2026, 4, 20),
            valor_bruto=Decimal('100.00'),
            status='emitida',
        )
        DespesaObra.objects.create(
            obra=obra_pior,
            data_referencia=date(2026, 4, 20),
            categoria='outra',
            descricao='Custo alto',
            valor=Decimal('150.00'),
        )

        response = self.client.get(reverse('home'))

        obras = response.context['obras']
        self.assertEqual(obras[0].nome_obra, 'Obra Melhor')
        self.assertEqual(obras[1].nome_obra, 'Obra Pior')

    def test_relatorio_geral_aplica_filtro_por_cliente(self):
        Obra.objects.create(nome_obra='Obra Cliente A', cliente='Cliente A', valor_contrato=Decimal('100.00'))
        Obra.objects.create(nome_obra='Obra Cliente B', cliente='Cliente B', valor_contrato=Decimal('200.00'))

        response = self.client.get(reverse('relatorio_geral'), {'cliente': 'Cliente A'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Relatorio Geral')
        self.assertContains(response, 'Obra Cliente A')
        self.assertNotContains(response, 'Obra Cliente B')

    def test_relatorio_geral_mostra_erro_para_status_invalido(self):
        response = self.client.get(reverse('relatorio_geral'), {'status': 'invalido'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'invalido')

    def test_dashboard_redireciona_para_login_sem_autenticacao(self):
        self.client.logout()

        response = self.client.get(reverse('home'))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('home')}")
