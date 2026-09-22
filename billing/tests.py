import hashlib
import hmac
import json
import uuid
from io import StringIO
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from empresas.models import Empresa, UsuarioEmpresa
from site_publico.models import PublicLead

from .models import Assinatura, CheckoutIntent, EventoWebhook, Pagamento
from .services.comercial import adicionar_meses, periodo_inicial, valor_periodicidade
from .services.entitlements import empresa_tem_acesso
from .services.mercadopago import (
    MercadoPagoError,
    MercadoPagoUnavailable,
    aplicar_pagamento_gateway,
    consultar_pagamento_autorizado_gateway,
    criar_checkout_intent_recorrente,
    registrar_webhook,
    validar_assinatura_webhook,
)
from .services.self_service import converter_checkout_intent, criar_checkout_intent, processar_checkout_gateway


def criar_empresa(nome='Empresa Billing', slug='empresa-billing'):
    return Empresa.objects.create(nome=nome, slug=slug)


def criar_usuario_empresa(empresa, username='usuario-billing', **vinculo_kwargs):
    user = User.objects.create_user(username=username, password='senha')
    UsuarioEmpresa.objects.create(usuario=user, empresa=empresa, **vinculo_kwargs)
    return user


class BillingModelTests(TestCase):
    def test_valores_comerciais_sao_decimal(self):
        self.assertEqual(valor_periodicidade(Assinatura.Periodicidade.MENSAL), Decimal('149.90'))
        self.assertEqual(valor_periodicidade(Assinatura.Periodicidade.SEMESTRAL), Decimal('799.00'))
        self.assertEqual(valor_periodicidade(Assinatura.Periodicidade.ANUAL), Decimal('1399.00'))

    def test_periodicidades_calculam_proxima_cobranca_em_meses(self):
        inicio = timezone.datetime(2026, 1, 31, 12, tzinfo=timezone.get_current_timezone())

        self.assertEqual(adicionar_meses(inicio, 1).date().isoformat(), '2026-02-28')
        self.assertEqual(adicionar_meses(inicio, 6).date().isoformat(), '2026-07-31')
        self.assertEqual(adicionar_meses(inicio, 12).date().isoformat(), '2027-01-31')

    def test_assinatura_aprovada_fica_ativa_com_periodo(self):
        empresa = criar_empresa()
        assinatura = Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
        )
        inicio, fim, proxima = periodo_inicial(assinatura.periodicidade)

        assinatura.marcar_ativa(inicio=inicio, fim_periodo=fim, proxima_cobranca=proxima)

        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)
        self.assertIsNone(assinatura.grace_until)
        self.assertEqual(assinatura.proxima_cobranca, proxima)


class BillingEntitlementTests(TestCase):
    def test_empresa_legada_sem_assinatura_continua_com_acesso(self):
        empresa = criar_empresa()

        self.assertTrue(empresa_tem_acesso(empresa))

    @override_settings(BILLING_GRACE_DAYS=5)
    def test_atraso_dentro_da_tolerancia_mantem_acesso(self):
        empresa = criar_empresa()
        assinatura = Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
        )
        assinatura.registrar_falha_pagamento()

        self.assertTrue(empresa_tem_acesso(empresa))
        self.assertEqual(Assinatura.objects.get(pk=assinatura.pk).status, Assinatura.Status.EM_ATRASO)

    def test_atraso_fora_da_tolerancia_suspende_sem_apagar_dados(self):
        empresa = criar_empresa()
        assinatura = Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
            status=Assinatura.Status.EM_ATRASO,
            grace_until=timezone.now() - timezone.timedelta(minutes=1),
        )

        self.assertFalse(empresa_tem_acesso(empresa))
        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.SUSPENSA)

    def test_recuperacao_por_pagamento_aprovado_remove_tolerancia(self):
        empresa = criar_empresa()
        assinatura = Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
            status=Assinatura.Status.EM_ATRASO,
            grace_until=timezone.now() + timezone.timedelta(days=1),
        )

        aplicar_pagamento_gateway({
            'id': 'pay-1',
            'status': 'approved',
            'transaction_amount': '149.90',
            'currency_id': 'BRL',
            'external_reference': f'assinatura:{assinatura.id}',
        })

        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)
        self.assertIsNone(assinatura.grace_until)
        self.assertTrue(Pagamento.objects.filter(assinatura=assinatura, status=Pagamento.Status.APROVADO).exists())


class BillingMiddlewareTests(TestCase):
    def test_assinatura_suspensa_bloqueia_modulos_operacionais(self):
        empresa = criar_empresa()
        user = criar_usuario_empresa(empresa)
        Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
            status=Assinatura.Status.SUSPENSA,
        )
        self.client.login(username=user.username, password='senha')

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('billing:assinatura_pendente'), response['Location'])

    def test_staff_tem_bypass_de_billing(self):
        empresa = criar_empresa()
        user = User.objects.create_user(username='staff-billing', password='senha', is_staff=True)
        UsuarioEmpresa.objects.create(usuario=user, empresa=empresa)
        Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
            status=Assinatura.Status.SUSPENSA,
        )
        self.client.login(username=user.username, password='senha')

        response = self.client.get(reverse('home'))

        self.assertNotEqual(response.status_code, 302)

    def test_usuario_comum_nao_acessa_painel_staff_de_assinaturas(self):
        empresa = criar_empresa()
        user = criar_usuario_empresa(empresa, administrador_empresa=True)
        self.client.login(username=user.username, password='senha')

        response = self.client.get(reverse('assinaturas_plataforma'))

        self.assertEqual(response.status_code, 403)


class BillingWebhookTests(TestCase):
    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='segredo-webhook', MERCADOPAGO_ENVIRONMENT='production')
    def test_validacao_webhook_por_hmac(self):
        body = b'{"id":"evt-1"}'
        signature = hmac.new(b'segredo-webhook', body, hashlib.sha256).hexdigest()

        self.assertTrue(validar_assinatura_webhook(body, {'x-signature': f'ts=1,v1={signature}'}))
        self.assertFalse(validar_assinatura_webhook(body, {'x-signature': 'v1=assinatura-errada'}))

    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='segredo-webhook', MERCADOPAGO_ENVIRONMENT='production')
    def test_validacao_webhook_aceita_formato_oficial_com_request_id_e_data_id(self):
        manifest = b'id:999999999;request-id:req-123;ts:1704908010;'
        signature = hmac.new(b'segredo-webhook', manifest, hashlib.sha256).hexdigest()

        self.assertTrue(validar_assinatura_webhook(
            b'{}',
            {'x-signature': f'ts=1704908010,v1={signature}', 'x-request-id': 'req-123'},
            data_id='999999999',
        ))

    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='', MERCADOPAGO_ENVIRONMENT='production')
    def test_producao_sem_secret_rejeita_webhook(self):
        self.assertFalse(validar_assinatura_webhook(b'{}', {}))

    def test_webhook_idempotente_nao_duplica_evento_ou_pagamento(self):
        empresa = criar_empresa()
        assinatura = Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
        )
        payload = {
            'id': 'evt-1',
            'type': 'payment',
            'data': {'id': 'pay-1'},
        }
        payment_data = {
            'id': 'pay-1',
            'status': 'approved',
            'transaction_amount': '149.90',
            'external_reference': f'assinatura:{assinatura.id}',
        }

        registrar_webhook(payload, body=json.dumps(payload).encode('utf-8'), service_consultar_pagamento=lambda _id: payment_data)
        evento, created = registrar_webhook(payload, body=json.dumps(payload).encode('utf-8'), service_consultar_pagamento=lambda _id: payment_data)

        self.assertFalse(created)
        self.assertEqual(evento.status_processamento, EventoWebhook.StatusProcessamento.PROCESSADO)
        self.assertEqual(EventoWebhook.objects.count(), 1)
        self.assertEqual(Pagamento.objects.count(), 1)

    def test_falha_externa_no_webhook_nao_suspende_assinatura(self):
        empresa = criar_empresa()
        assinatura = Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
            status=Assinatura.Status.ATIVA,
        )
        payload = {'id': 'evt-offline', 'type': 'payment', 'data': {'id': 'pay-offline'}}

        evento, created = registrar_webhook(
            payload,
            body=json.dumps(payload).encode('utf-8'),
            service_consultar_pagamento=lambda _id: (_ for _ in ()).throw(MercadoPagoUnavailable('offline')),
        )

        assinatura.refresh_from_db()
        self.assertTrue(created)
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)
        self.assertEqual(evento.status_processamento, EventoWebhook.StatusProcessamento.RECEBIDO)
        self.assertEqual(EventoWebhook.objects.get().status_processamento, EventoWebhook.StatusProcessamento.RECEBIDO)

    @mock.patch('billing.services.mercadopago._request_json')
    def test_pagamento_autorizado_usa_endpoint_proprio(self, request_json):
        request_json.return_value = {'id': 'invoice-1'}

        consultar_pagamento_autorizado_gateway('invoice-1')

        request_json.assert_called_once_with('GET', '/authorized_payments/invoice-1')

    def _assinatura_gateway(self):
        empresa = criar_empresa(nome='Empresa Webhook', slug='empresa-webhook')
        return Assinatura.objects.create(
            empresa=empresa,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
            gateway_subscription_id='preapproval-1',
        )

    def _authorized_data(self, assinatura, status='approved'):
        return {
            'id': 'invoice-1',
            'preapproval_id': assinatura.gateway_subscription_id,
            'external_reference': f'assinatura:{assinatura.id}',
            'transaction_amount': '149.90',
            'currency_id': 'BRL',
            'summarized': status,
            'payment': {'id': 'pay-1', 'status': status},
        }

    def _payment_data(self, assinatura, status='approved'):
        return {
            'id': 'pay-1',
            'invoice_id': 'invoice-1',
            'preapproval_id': assinatura.gateway_subscription_id,
            'external_reference': f'assinatura:{assinatura.id}',
            'transaction_amount': '149.90',
            'currency_id': 'BRL',
            'status': status,
        }

    def test_authorized_payment_primeiro_e_payment_depois_nao_duplicam(self):
        assinatura = self._assinatura_gateway()
        authorized_payload = {'id': 'evt-auth-1', 'type': 'subscription_authorized_payment', 'data': {'id': 'invoice-1'}}
        payment_payload = {'id': 'evt-pay-1', 'type': 'payment', 'data': {'id': 'pay-1'}}

        registrar_webhook(
            authorized_payload,
            service_consultar_pagamento_autorizado=lambda _id: self._authorized_data(assinatura),
        )
        registrar_webhook(
            payment_payload,
            service_consultar_pagamento=lambda _id: self._payment_data(assinatura),
        )

        self.assertEqual(Pagamento.objects.count(), 1)
        pagamento = Pagamento.objects.get()
        self.assertEqual(pagamento.gateway_payment_id, 'pay-1')
        self.assertEqual(pagamento.gateway_invoice_id, 'invoice-1')
        self.assertEqual(pagamento.status, Pagamento.Status.APROVADO)

    def test_payment_primeiro_e_authorized_payment_depois_nao_duplicam(self):
        assinatura = self._assinatura_gateway()
        payment_payload = {'id': 'evt-pay-2', 'type': 'payment', 'data': {'id': 'pay-1'}}
        authorized_payload = {'id': 'evt-auth-2', 'type': 'subscription_authorized_payment', 'data': {'id': 'invoice-1'}}

        registrar_webhook(
            payment_payload,
            service_consultar_pagamento=lambda _id: self._payment_data(assinatura),
        )
        registrar_webhook(
            authorized_payload,
            service_consultar_pagamento_autorizado=lambda _id: self._authorized_data(assinatura),
        )

        self.assertEqual(Pagamento.objects.count(), 1)
        self.assertEqual(Pagamento.objects.get().gateway_invoice_id, 'invoice-1')

    def test_authorized_payment_recusado_registra_atraso(self):
        assinatura = self._assinatura_gateway()
        payload = {'id': 'evt-auth-rejected', 'type': 'subscription_authorized_payment', 'data': {'id': 'invoice-1'}}

        registrar_webhook(
            payload,
            service_consultar_pagamento_autorizado=lambda _id: self._authorized_data(assinatura, status='rejected'),
        )

        assinatura.refresh_from_db()
        self.assertEqual(Pagamento.objects.get().status, Pagamento.Status.RECUSADO)
        self.assertEqual(assinatura.status, Assinatura.Status.EM_ATRASO)

    def test_subscription_preapproval_consulta_assinatura_separadamente(self):
        assinatura = self._assinatura_gateway()
        payload = {'id': 'evt-sub-1', 'type': 'subscription_preapproval', 'data': {'id': 'preapproval-1'}}
        consultar = mock.Mock(return_value={
            'id': 'preapproval-1',
            'external_reference': f'assinatura:{assinatura.id}',
            'status': 'authorized',
        })

        registrar_webhook(payload, service_consultar_assinatura=consultar)

        consultar.assert_called_once_with('preapproval-1')
        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)


class BillingStaffFlowTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff-contratacao', password='senha', is_staff=True)
        self.empresa = criar_empresa(nome='Cliente Estribo', slug='cliente-estribo')
        self.lead = PublicLead.objects.create(
            nome='Maria',
            empresa='Cliente Estribo',
            email='maria@example.com',
            telefone='51999990000',
            status=PublicLead.Status.GANHO,
            billing_preference=PublicLead.BillingPreference.SEMESTRAL,
        )

    def test_lead_exibe_acao_de_preparar_contratacao_para_staff(self):
        self.client.login(username=self.staff.username, password='senha')

        response = self.client.get(reverse('detalhe_lead_plataforma', args=[self.lead.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('preparar_contratacao_lead', args=[self.lead.id]))
        self.assertContains(response, 'Preparar contratação')

    @override_settings(MERCADOPAGO_ACCESS_TOKEN='')
    def test_preparar_contratacao_cria_assinatura_sem_chamar_gateway_sem_credencial(self):
        self.client.login(username=self.staff.username, password='senha')

        with mock.patch('billing.views.criar_assinatura_recorrente') as criar_gateway:
            response = self.client.post(
                reverse('preparar_contratacao_lead', args=[self.lead.id]),
                {'empresa': self.empresa.id, 'periodicidade': Assinatura.Periodicidade.ANUAL},
            )

        self.assertEqual(response.status_code, 302)
        criar_gateway.assert_not_called()
        assinatura = Assinatura.objects.get()
        self.assertEqual(assinatura.empresa, self.empresa)
        self.assertEqual(assinatura.lead_origem, self.lead)
        self.assertEqual(assinatura.valor_contratado, Decimal('1399.00'))

    @override_settings(MERCADOPAGO_ACCESS_TOKEN='token-teste', MERCADOPAGO_PUBLIC_KEY='public-key-teste')
    def test_html_de_assinatura_nao_expoe_secrets(self):
        assinatura = Assinatura.objects.create(
            empresa=self.empresa,
            lead_origem=self.lead,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
            gateway_subscription_id='sub_1234567890',
        )
        self.client.login(username=self.staff.username, password='senha')

        response = self.client.get(reverse('detalhe_assinatura_plataforma', args=[assinatura.id]))
        content = response.content.decode('utf-8')

        self.assertNotIn('token-teste', content)
        self.assertNotIn('public-key-teste', content)
        self.assertIn('sub_123456', content)

    def test_cancelamento_sem_gateway_id_marca_cancel_at_period_end(self):
        assinatura = Assinatura.objects.create(
            empresa=self.empresa,
            lead_origem=self.lead,
            periodicidade=Assinatura.Periodicidade.MENSAL,
            valor_contratado=Decimal('149.90'),
            status=Assinatura.Status.ATIVA,
            data_fim_periodo=timezone.now() + timezone.timedelta(days=20),
        )
        self.client.login(username=self.staff.username, password='senha')

        response = self.client.post(reverse('cancelar_assinatura_plataforma', args=[assinatura.id]))

        self.assertEqual(response.status_code, 302)
        assinatura.refresh_from_db()
        self.assertTrue(assinatura.cancel_at_period_end)
        self.assertIsNone(assinatura.canceled_at)
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)
        self.assertTrue(assinatura.permite_acesso())


class BillingCancellationCommandTests(TestCase):
    def setUp(self):
        self.empresa = criar_empresa(nome='Empresa Cancelamento', slug='empresa-cancelamento')

    def _assinatura(self, fim, **kwargs):
        defaults = {
            'empresa': self.empresa,
            'periodicidade': Assinatura.Periodicidade.MENSAL,
            'valor_contratado': Decimal('149.90'),
            'status': Assinatura.Status.ATIVA,
            'data_fim_periodo': fim,
            'proxima_cobranca': fim,
            'gateway_subscription_id': 'preapproval-cancel-1',
            'cancel_at_period_end': True,
        }
        defaults.update(kwargs)
        return Assinatura.objects.create(**defaults)

    @mock.patch('billing.management.commands.process_billing_cancellations.cancelar_assinatura_gateway')
    def test_cancelamento_futuro_preserva_acesso_e_nao_chama_gateway_antes_da_janela(self, cancelar):
        assinatura = self._assinatura(timezone.now() + timezone.timedelta(days=10))

        call_command('process_billing_cancellations', stdout=StringIO())

        cancelar.assert_not_called()
        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)
        self.assertTrue(assinatura.permite_acesso())

    @mock.patch('billing.management.commands.process_billing_cancellations.cancelar_assinatura_gateway')
    def test_cancelamento_na_janela_impede_renovacao_mas_preserva_acesso(self, cancelar):
        assinatura = self._assinatura(timezone.now() + timezone.timedelta(minutes=30))

        call_command('process_billing_cancellations', stdout=StringIO())

        cancelar.assert_called_once()
        assinatura.refresh_from_db()
        self.assertIsNotNone(assinatura.canceled_at)
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)
        self.assertTrue(assinatura.permite_acesso())

    @mock.patch('billing.management.commands.process_billing_cancellations.cancelar_assinatura_gateway')
    def test_data_final_cancela_localmente_e_comando_e_idempotente(self, cancelar):
        fim = timezone.now() - timezone.timedelta(minutes=1)
        assinatura = self._assinatura(fim)

        call_command('process_billing_cancellations', stdout=StringIO())
        call_command('process_billing_cancellations', stdout=StringIO())

        cancelar.assert_called_once()
        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.CANCELADA)
        self.assertFalse(assinatura.permite_acesso())
        self.assertIsNone(assinatura.proxima_cobranca)

    @mock.patch('billing.management.commands.process_billing_cancellations.cancelar_assinatura_gateway')
    def test_falha_externa_preserva_assinatura_ativa(self, cancelar):
        cancelar.side_effect = MercadoPagoError('offline')
        assinatura = self._assinatura(timezone.now() + timezone.timedelta(minutes=30))

        call_command('process_billing_cancellations', stdout=StringIO())

        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)
        self.assertIsNone(assinatura.canceled_at)

    @mock.patch('billing.management.commands.reconcile_billing.consultar_assinatura_gateway')
    def test_reconciliacao_preserva_acesso_apos_cancelamento_remoto_antecipado(self, consultar):
        assinatura = self._assinatura(timezone.now() + timezone.timedelta(days=2), canceled_at=timezone.now())
        consultar.return_value = {
            'id': assinatura.gateway_subscription_id,
            'external_reference': f'assinatura:{assinatura.id}',
            'status': 'cancelled',
        }
        call_command('reconcile_billing', '--assinatura', str(assinatura.id), stdout=StringIO())
        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.ATIVA)
        self.assertTrue(assinatura.permite_acesso())

    @mock.patch('billing.management.commands.reconcile_billing.consultar_assinatura_gateway')
    def test_reconciliacao_cancelada_sem_agendamento_encerra_acesso(self, consultar):
        assinatura = self._assinatura(
            timezone.now() + timezone.timedelta(days=2), cancel_at_period_end=False,
        )
        consultar.return_value = {
            'id': assinatura.gateway_subscription_id,
            'external_reference': f'assinatura:{assinatura.id}',
            'status': 'cancelled',
        }
        call_command('reconcile_billing', '--assinatura', str(assinatura.id), stdout=StringIO())
        assinatura.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.CANCELADA)
        self.assertFalse(assinatura.permite_acesso())


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PLATFORM_BASE_URL='https://app.estribo.test',
    PUBLIC_BASE_URL='https://checkout.estribo.test',
    MERCADOPAGO_ACCESS_TOKEN='token-de-teste',
    MERCADOPAGO_ENVIRONMENT='test',
    MERCADOPAGO_TEST_PAYER_EMAIL='buyer@testuser.com',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class BillingSelfServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.payload = {
            'nome_responsavel': 'Ana Souza',
            'nome_empresa': 'Construtora Teste',
            'email': 'ana@example.com',
            'telefone': '51999999999',
            'periodicidade': Assinatura.Periodicidade.ANUAL,
            'consentimento': 'on',
            'utm_source': 'google',
            'utm_campaign': 'lancamento',
            'gclid': 'click-123',
        }

    def _intent(self, status=CheckoutIntent.Status.INICIADO):
        intent = criar_checkout_intent(self.payload, referrer='https://google.com/')
        intent.status = status
        intent.gateway_subscription_id = 'preapproval-self-1'
        intent.gateway_checkout_url = 'https://mercadopago.test/checkout'
        intent.save()
        return intent

    def test_checkout_publico_abre_sem_login_e_default_anual(self):
        response = self.client.get(reverse('checkout_publico'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].initial['periodicidade'], Assinatura.Periodicidade.ANUAL)

    def test_periodicidades_da_query_sao_respeitadas(self):
        for query, esperado in (
            ('mensal', Assinatura.Periodicidade.MENSAL),
            ('semestral', Assinatura.Periodicidade.SEMESTRAL),
            ('anual', Assinatura.Periodicidade.ANUAL),
        ):
            response = self.client.get(reverse('checkout_publico'), {'periodo': query})
            self.assertEqual(response.context['form'].initial['periodicidade'], esperado)

    @mock.patch('billing.views.criar_checkout_intent_recorrente')
    def test_checkout_cria_intent_preserva_atribuicao_e_usa_preco_do_backend(self, criar_gateway):
        criar_gateway.return_value = {
            'id': 'preapproval-public-1', 'init_point': 'https://mercadopago.test/checkout',
        }
        adulterado = {**self.payload, 'preco': '0.01'}

        response = self.client.post(reverse('checkout_publico'), adulterado)

        self.assertEqual(response.status_code, 302)
        intent = CheckoutIntent.objects.get()
        self.assertEqual(intent.utm_source, 'google')
        self.assertEqual(intent.gclid, 'click-123')
        self.assertIsNotNone(intent.consent_at)
        self.assertIsInstance(intent.public_id, uuid.UUID)
        self.assertNotIn(intent.email, intent.external_reference)
        self.assertIsNone(intent.empresa_id)
        args, kwargs = criar_gateway.call_args
        self.assertEqual(args[0].periodicidade, Assinatura.Periodicidade.ANUAL)
        self.assertEqual(kwargs['payer_email'], 'buyer@testuser.com')

    @override_settings(MERCADOPAGO_ENVIRONMENT='production')
    @mock.patch('billing.views.criar_checkout_intent_recorrente')
    def test_producao_usa_email_informado(self, criar_gateway):
        criar_gateway.return_value = {'id': 'sub', 'init_point': 'https://mercadopago.test/checkout'}
        self.client.post(reverse('checkout_publico'), self.payload)
        self.assertEqual(criar_gateway.call_args.kwargs['payer_email'], 'ana@example.com')

    def test_consentimento_e_obrigatorio_e_honeypot_nao_cria_intent(self):
        sem_consentimento = {**self.payload}
        sem_consentimento.pop('consentimento')
        response = self.client.post(reverse('checkout_publico'), sem_consentimento)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CheckoutIntent.objects.count(), 0)

        response = self.client.post(reverse('checkout_publico'), {**self.payload, 'website': 'spam'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CheckoutIntent.objects.count(), 0)

    @override_settings(PUBLIC_CHECKOUT_RATE_LIMIT=1)
    def test_rate_limit_bloqueia_excesso(self):
        self.client.post(reverse('checkout_publico'), {**self.payload, 'consentimento': ''})
        response = self.client.post(reverse('checkout_publico'), {**self.payload, 'consentimento': ''})
        self.assertEqual(response.status_code, 429)

    @mock.patch('billing.views.criar_checkout_intent_recorrente', side_effect=MercadoPagoError('offline'))
    def test_falha_gateway_nao_cria_empresa(self, _gateway):
        response = self.client.post(reverse('checkout_publico'), self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CheckoutIntent.objects.get().status, CheckoutIntent.Status.FALHOU)
        self.assertFalse(Empresa.objects.filter(nome='Construtora Teste').exists())

    @mock.patch('billing.views.criar_checkout_intent_recorrente', return_value={'id': 'sub-sem-url'})
    def test_resposta_gateway_sem_url_marca_intent_como_falha(self, _gateway):
        response = self.client.post(reverse('checkout_publico'), self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'URL de pagamento')
        self.assertEqual(CheckoutIntent.objects.get().status, CheckoutIntent.Status.FALHOU)
        self.assertFalse(Empresa.objects.filter(nome='Construtora Teste').exists())

    def test_retorno_get_nao_converte_nem_cria_empresa(self):
        intent = self._intent(CheckoutIntent.Status.AGUARDANDO_PAGAMENTO)
        response = self.client.get(reverse('billing:checkout_retorno', args=[intent.public_id]), {'status': 'approved'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Empresa.objects.filter(nome='Construtora Teste').exists())

    def test_webhook_aprovado_converte_uma_unica_vez_e_cria_primeiro_admin(self):
        intent = self._intent(CheckoutIntent.Status.AGUARDANDO_PAGAMENTO)
        data = {
            'id': 'payment-self-1', 'status': 'approved', 'transaction_amount': '1399.00',
            'currency_id': 'BRL', 'external_reference': intent.external_reference,
            'preapproval_id': intent.gateway_subscription_id,
        }

        aplicar_pagamento_gateway(data)
        aplicar_pagamento_gateway(data)

        intent.refresh_from_db()
        self.assertEqual(intent.status, CheckoutIntent.Status.CONVERTIDO)
        self.assertEqual(Empresa.objects.filter(nome='Construtora Teste').count(), 1)
        self.assertEqual(Assinatura.objects.count(), 1)
        self.assertEqual(Pagamento.objects.count(), 1)
        user = User.objects.get(email='ana@example.com')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        vinculo = UsuarioEmpresa.objects.get(usuario=user, empresa=intent.empresa)
        self.assertTrue(vinculo.administrador_empresa)
        self.assertEqual(mail.outbox.__len__(), 1)

    def test_authorized_payment_e_payment_nao_duplicam_conversao(self):
        intent = self._intent(CheckoutIntent.Status.AGUARDANDO_PAGAMENTO)
        authorized = {
            'id': 'pay-shared', 'invoice_id': 'invoice-shared', 'status': 'approved',
            'transaction_amount': '1399.00', 'external_reference': intent.external_reference,
            'preapproval_id': intent.gateway_subscription_id,
        }
        aplicar_pagamento_gateway(authorized)
        aplicar_pagamento_gateway({**authorized, 'id': 'pay-shared'})
        self.assertEqual(Empresa.objects.filter(nome='Construtora Teste').count(), 1)
        self.assertEqual(Assinatura.objects.count(), 1)
        self.assertEqual(Pagamento.objects.count(), 1)

    @mock.patch('billing.services.mercadopago._request_json')
    def test_preapproval_publico_usa_frequencia_e_valor_centrais(self, request_json):
        request_json.return_value = {'id': 'sub'}
        for periodicidade, frequencia, valor in (
            (Assinatura.Periodicidade.MENSAL, 1, '149.90'),
            (Assinatura.Periodicidade.SEMESTRAL, 6, '799.00'),
            (Assinatura.Periodicidade.ANUAL, 12, '1399.00'),
        ):
            intent = self._intent()
            intent.periodicidade = periodicidade
            intent.save(update_fields=['periodicidade'])
            criar_checkout_intent_recorrente(
                intent, payer_email='buyer@testuser.com', back_url='https://checkout.estribo.test/retorno/',
            )
            payload = request_json.call_args.kwargs['payload']
            self.assertEqual(payload['auto_recurring']['frequency'], frequencia)
            self.assertEqual(payload['auto_recurring']['frequency_type'], 'months')
            self.assertEqual(payload['auto_recurring']['transaction_amount'], valor)

    @mock.patch('billing.services.self_service.enviar_convite_usuario_empresa', return_value=False)
    def test_falha_de_email_nao_duplica_onboarding(self, _enviar):
        intent = self._intent(CheckoutIntent.Status.PAGO)
        converter_checkout_intent(intent.id)
        converter_checkout_intent(intent.id)
        self.assertEqual(Empresa.objects.filter(nome='Construtora Teste').count(), 1)
        self.assertEqual(Assinatura.objects.count(), 1)
        self.assertEqual(User.objects.filter(email='ana@example.com').count(), 1)

    def test_pagamento_pendente_nao_converte(self):
        intent = self._intent(CheckoutIntent.Status.CHECKOUT_CRIADO)
        processar_checkout_gateway({
            'status': 'pending', 'external_reference': intent.external_reference,
        })
        intent.refresh_from_db()
        self.assertEqual(intent.status, CheckoutIntent.Status.AGUARDANDO_PAGAMENTO)
        self.assertFalse(Empresa.objects.filter(nome='Construtora Teste').exists())

    def test_email_existente_impede_conversao_ambigua(self):
        User.objects.create_user(username='existente', email='ana@example.com')
        intent = self._intent(CheckoutIntent.Status.PAGO)
        converter_checkout_intent(intent.id)
        intent.refresh_from_db()
        self.assertEqual(intent.status, CheckoutIntent.Status.FALHOU)
        self.assertFalse(Empresa.objects.filter(nome='Construtora Teste').exists())

    def test_staff_lista_e_usuario_tenant_recebe_403(self):
        self._intent()
        staff = User.objects.create_user(username='staff-self', password='senha', is_staff=True)
        self.client.login(username='staff-self', password='senha')
        self.assertEqual(self.client.get(reverse('contratacoes_plataforma')).status_code, 200)
        self.client.logout()
        empresa = criar_empresa(nome='Tenant Comum', slug='tenant-comum')
        user = criar_usuario_empresa(empresa, username='tenant-self')
        self.client.login(username=user.username, password='senha')
        self.assertEqual(self.client.get(reverse('contratacoes_plataforma')).status_code, 403)
