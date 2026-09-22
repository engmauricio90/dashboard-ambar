from django.contrib.staticfiles import finders
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from empresas.models import Empresa, UsuarioEmpresa

from .models import PublicLead


def lead_payload(**overrides):
    payload = {
        'nome': 'Joao Teste',
        'empresa': 'Construtora Teste',
        'telefone': '(51) 99999-0000',
        'email': 'joao@example.com',
        'quantidade_obras': '3',
        'cargo_funcao': 'Diretoria',
        'como_controla_hoje': PublicLead.ComoControlaHoje.EXCEL,
        'principal_dificuldade': PublicLead.PrincipalDificuldade.MEDICOES_FATURAMENTO,
        'mensagem': 'Quero organizar medicoes e financeiro.',
        'consentimento': 'on',
        'utm_source': 'google',
        'utm_medium': 'cpc',
        'utm_campaign': 'medicoes',
        'utm_content': 'anuncio-a',
        'utm_term': 'sistema de medicao',
        'gclid': 'gclid-123',
        'fbclid': 'fbclid-456',
        'landing_path': '/?utm_source=google',
        'billing_preference': PublicLead.BillingPreference.ANUAL,
    }
    payload.update(overrides)
    return payload


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
    PUBLIC_GA4_ID='',
    PUBLIC_GOOGLE_ADS_ID='',
    PUBLIC_META_PIXEL_ID='',
    PUBLIC_WHATSAPP_NUMBER='5551999990000',
    PUBLIC_LEAD_RATE_LIMIT=5,
    PUBLIC_LEAD_RATE_LIMIT_WINDOW=3600,
)
class PublicLandingTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_home_publica_retorna_200(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ESTRIBO')
        self.assertContains(response, 'Do contrato ao')
        self.assertContains(response, 'resultado')

    def test_home_tem_link_de_login_e_title(self):
        response = self.client.get('/')

        self.assertContains(response, f'href="{reverse("login")}"')
        self.assertContains(response, '<title>Estribo | Gest\u00e3o de obras para construtoras</title>', html=True)

    def test_home_nao_contem_mojibake_ou_caractere_substituto(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertIn('Gest&atilde;o', content)
        self.assertIn('Medi&ccedil;&otilde;es', content)
        self.assertIn('relat&oacute;rios', content)
        for broken in [chr(65533), chr(195), chr(194)]:
            self.assertNotIn(broken, content)

    def test_home_referencia_identidade_visual_oficial(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertIn('site_publico/brand/logo-estribo-horizontal.png', content)
        self.assertIn('site_publico/brand/logo-estribo-horizontal-white.png', content)
        self.assertIn('alt="Estribo - Gest&atilde;o para construtoras"', content)
        self.assertNotIn('site_publico/brand/logo-estribo-horizontal.svg', content)
        self.assertNotIn('site_publico/brand/logo-estribo-horizontal-white.svg', content)
        self.assertNotIn('class="brand-name"', content)
        self.assertNotIn('class="footer-brand"', content)

    def test_home_configura_favicon_e_app_icon(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertIn('site_publico/brand/favicon-32.png', content)
        self.assertIn('site_publico/brand/apple-touch-icon.png', content)
        self.assertNotIn('site_publico/brand/favicon.svg', content)

    def test_assets_oficiais_png_existem_no_staticfiles(self):
        assets = [
            'site_publico/brand/logo-estribo-horizontal.png',
            'site_publico/brand/logo-estribo-horizontal-white.png',
            'site_publico/brand/favicon-32.png',
            'site_publico/brand/apple-touch-icon.png',
        ]

        for asset in assets:
            self.assertIsNotNone(finders.find(asset), asset)

    def test_home_sem_ids_nao_carrega_scripts_de_analytics(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertNotIn('googletagmanager.com/gtag/js', content)
        self.assertNotIn('connect.facebook.net', content)

    @override_settings(PUBLIC_GA4_ID='G-TESTE123', PUBLIC_META_PIXEL_ID='123456789')
    def test_home_com_ids_renderiza_configuracao_sem_script_externo(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertIn('data-ga4-id="G-TESTE123"', content)
        self.assertIn('data-meta-pixel-id="123456789"', content)
        self.assertNotIn('googletagmanager.com/gtag/js', content)
        self.assertNotIn('connect.facebook.net', content)

    def test_home_contem_secoes_principais(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        for anchor in ['id="plataforma"', 'id="solucoes"', 'id="construtoras"', 'id="seguranca"', 'id="planos"', 'id="demonstracao"']:
            self.assertIn(anchor, content)
        self.assertIn('application/ld+json', content)

    def test_home_exibe_plano_unico_e_precos_aprovados(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertIn('Plano &uacute;nico', content)
        self.assertIn('Um plano. Tudo incluso.', content)
        self.assertIn('R$ 149,90', content)
        self.assertIn('R$ 799', content)
        self.assertIn('R$ 1.399', content)
        self.assertIn('Obras ilimitadas', content)
        self.assertIn('Usu&aacute;rios ilimitados', content)
        self.assertIn('10 GB de armazenamento', content)
        self.assertIn('data-default-period="ANUAL"', content)
        self.assertNotIn('Escolha o escopo ideal', content)
        self.assertNotIn('Valores sob consulta', content)

    def test_home_remove_modelo_antigo_de_tres_planos(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertNotIn('Conversar sobre este plano', content)
        self.assertNotIn('<h3>Obra</h3>', content)
        self.assertNotIn('<h3>Construtora</h3>', content)
        self.assertNotIn('<h3>Gest&atilde;o</h3>', content)

    def test_cta_do_pricing_continua_levando_ao_formulario(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertIn('href="#demonstracao"', content)
        self.assertIn('data-billing-cta', content)

    def test_home_nao_cria_promessas_nao_suportadas(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        for claim in ['CRM', 'SINAPI', 'assinatura autom\u00e1tica', 'emiss\u00e3o autom\u00e1tica de nota']:
            self.assertNotIn(claim, content)

    def test_home_nao_expoe_dados_reais_conhecidos(self):
        response = self.client.get('/')
        content = response.content.decode('utf-8')

        self.assertNotIn('\u00c2mbar', content)
        self.assertNotIn('Cassoni', content)
        self.assertNotIn('Santher', content)
        self.assertNotIn('35.693.640/0001-09', content)

    def test_rota_privada_continua_protegida(self):
        response = self.client.get('/dashboard/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_post_cria_lead_com_status_padrao_e_atribuicao(self):
        response = self.client.post(
            '/',
            data=lead_payload(),
            HTTP_REFERER='https://google.com/search?q=estribo',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recebemos sua solicita')
        lead = PublicLead.objects.get()
        self.assertEqual(lead.status, PublicLead.Status.NOVO)
        self.assertEqual(lead.utm_source, 'google')
        self.assertEqual(lead.utm_campaign, 'medicoes')
        self.assertEqual(lead.gclid, 'gclid-123')
        self.assertEqual(lead.fbclid, 'fbclid-456')
        self.assertEqual(lead.telefone_normalizado, '5551999990000')
        self.assertEqual(lead.billing_preference, PublicLead.BillingPreference.ANUAL)
        self.assertIsNotNone(lead.consent_at)

    def test_billing_preference_e_opcional(self):
        response = self.client.post('/', data=lead_payload(billing_preference=''))

        self.assertEqual(response.status_code, 200)
        lead = PublicLead.objects.get()
        self.assertEqual(lead.billing_preference, '')

    def test_post_sem_consentimento_nao_cria_lead(self):
        payload = lead_payload()
        payload.pop('consentimento')
        response = self.client.post('/', data=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PublicLead.objects.count(), 0)

    def test_honeypot_descarta_bot_sem_criar_lead(self):
        response = self.client.post('/', data=lead_payload(website='https://bot.example'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recebemos sua solicita')
        self.assertEqual(PublicLead.objects.count(), 0)

    @override_settings(PUBLIC_LEAD_RATE_LIMIT=1)
    def test_rate_limit_bloqueia_excesso_de_posts(self):
        self.client.post('/', data=lead_payload(email='primeiro@example.com'))
        response = self.client.post('/', data=lead_payload(email='segundo@example.com'))

        self.assertEqual(PublicLead.objects.count(), 1)
        self.assertContains(response, 'muitas solicita')

    def test_privacidade_e_termos_sao_publicos(self):
        self.assertEqual(self.client.get('/privacidade/').status_code, 200)
        self.assertEqual(self.client.get('/termos/').status_code, 200)

    def test_leads_plataforma_exige_login(self):
        response = self.client.get(reverse('leads_plataforma'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_tenant_admin_nao_acessa_leads(self):
        user = User.objects.create_user(username='tenant-admin', password='senha')
        empresa = Empresa.objects.create(nome='Empresa Cliente', slug='empresa-cliente')
        UsuarioEmpresa.objects.create(usuario=user, empresa=empresa, administrador_empresa=True)
        self.client.login(username='tenant-admin', password='senha')

        response = self.client.get(reverse('leads_plataforma'))

        self.assertEqual(response.status_code, 403)

    def test_staff_lista_busca_e_filtra_leads(self):
        staff = User.objects.create_user(username='staff-leads', password='senha', is_staff=True)
        PublicLead.objects.create(nome='Maria', empresa='Construtora A', email='maria@example.com', telefone='5199', status=PublicLead.Status.NOVO, utm_source='google', utm_campaign='medicoes', billing_preference=PublicLead.BillingPreference.SEMESTRAL)
        PublicLead.objects.create(nome='Carlos', empresa='Construtora B', email='carlos@example.com', telefone='5188', status=PublicLead.Status.PERDIDO, utm_source='meta', utm_campaign='compras')
        self.client.login(username='staff-leads', password='senha')

        response = self.client.get(reverse('leads_plataforma'), {'status': PublicLead.Status.NOVO, 'utm_source': 'google'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Maria')
        self.assertContains(response, 'Semestral')
        self.assertNotContains(response, 'Carlos')

    def test_staff_atualiza_status_e_observacao(self):
        staff = User.objects.create_user(username='staff-detail', password='senha', is_staff=True)
        lead = PublicLead.objects.create(nome='Maria', empresa='Construtora A', email='maria@example.com', telefone='51999990000')
        self.client.login(username='staff-detail', password='senha')

        response = self.client.post(
            reverse('detalhe_lead_plataforma', args=[lead.id]),
            {'status': PublicLead.Status.CONTATADO, 'observacao_comercial': 'Contato feito.'},
        )

        self.assertEqual(response.status_code, 302)
        lead.refresh_from_db()
        self.assertEqual(lead.status, PublicLead.Status.CONTATADO)
        self.assertEqual(lead.observacao_comercial, 'Contato feito.')
