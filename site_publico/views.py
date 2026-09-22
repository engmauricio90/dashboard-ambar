import logging
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from .forms import ACQUISITION_FIELDS, PublicLeadForm, PublicLeadStatusForm
from .models import PublicLead


logger = logging.getLogger(__name__)


FAQS = [
    ('A Estribo serve para empresas com quantas obras?', 'Ela foi pensada para construtoras, empreiteiras e empresas de engenharia que precisam acompanhar uma ou v\u00e1rias obras com mais controle.'),
    ('Existem diferentes planos?', 'N\u00e3o. A Estribo possui um plano \u00fanico com todas as funcionalidades dispon\u00edveis, sem cobrar por m\u00f3dulo separado.'),
    ('Existe limite de obras?', 'N\u00e3o. O plano inclui obras ilimitadas para a sua empresa controlar a opera\u00e7\u00e3o sem precisar escolher quais obras entram no sistema.'),
    ('Existe limite de usu\u00e1rios?', 'N\u00e3o. O plano inclui usu\u00e1rios ilimitados, para envolver diretoria, engenharia, financeiro, compras e equipe de obra conforme a rotina exigir.'),
    ('Qual \u00e9 o limite de armazenamento?', 'S\u00e3o 10 GB inclu\u00eddos. Capacidade adicional pode ser contratada conforme a necessidade, com acr\u00e9scimo comercial de +10 GB por R$ 29,90/m\u00eas.'),
    ('Posso parcelar?', 'As condi\u00e7\u00f5es de pagamento dos planos semestral e anual s\u00e3o confirmadas na contrata\u00e7\u00e3o assistida, sempre antes da ativa\u00e7\u00e3o da assinatura.'),
    ('Preciso instalar algum programa?', 'N\u00e3o. A Estribo roda no navegador, com acesso por login e conex\u00e3o HTTPS.'),
    ('Funciona pelo celular?', 'As telas web s\u00e3o responsivas para consulta e opera\u00e7\u00e3o b\u00e1sica pelo celular. N\u00e3o h\u00e1 app nativo nesta fase.'),
    ('Como funciona a implanta\u00e7\u00e3o?', 'A implanta\u00e7\u00e3o inicial \u00e9 assistida, com apoio para organizar empresas, obras, usu\u00e1rios e primeiros lan\u00e7amentos.'),
    ('Posso controlar usu\u00e1rios e permiss\u00f5es?', 'Sim. O sistema possui usu\u00e1rios, grupos, v\u00ednculo por empresa e controle de administrador da empresa.'),
    ('Os dados da minha empresa ficam separados?', 'Sim. Cada empresa acessa somente as suas obras, medi\u00e7\u00f5es, documentos e informa\u00e7\u00f5es financeiras. Um cliente n\u00e3o visualiza os dados de outro.'),
    ('Consigo controlar medi\u00e7\u00f5es de empreiteiros?', 'Sim. A Estribo possui medi\u00e7\u00f5es de construtora e medi\u00e7\u00f5es de empreiteiros, incluindo relat\u00f3rios.'),
    ('Posso gerar relat\u00f3rios em PDF e Excel?', 'Sim. Os principais m\u00f3dulos possuem documentos e relat\u00f3rios padronizados em PDF e Excel.'),
    ('Meus documentos saem com a identidade da minha empresa?', 'Sim. Os documentos podem sair com os dados, logotipo e identidade visual da sua empresa, deixando relat\u00f3rios, medi\u00e7\u00f5es e registros com apresenta\u00e7\u00e3o mais profissional.'),
    ('O sistema funciona para empreiteiras tamb\u00e9m?', 'Sim. A Estribo se adapta muito bem a empreiteiras que precisam controlar obras, medi\u00e7\u00f5es, equipes, compras, documentos e financeiro de forma mais organizada.'),
    ('E se eu precisar de ajuda para cadastrar os dados iniciais?', 'Voc\u00ea conta com apoio na implanta\u00e7\u00e3o para organizar a base inicial, cadastrar empresas, obras, usu\u00e1rios e primeiros lan\u00e7amentos com mais seguran\u00e7a.'),
    ('Existe suporte?', 'Sim. A proposta comercial inicial considera implanta\u00e7\u00e3o assistida e suporte especializado.'),
    ('Posso cancelar?', 'Sim. Voc\u00ea pode cancelar em at\u00e9 7 dias ap\u00f3s a compra. Depois desse per\u00edodo, as condi\u00e7\u00f5es seguem o contrato definido na contrata\u00e7\u00e3o.'),
]


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _rate_limited(request):
    limit = int(getattr(settings, 'PUBLIC_LEAD_RATE_LIMIT', 5))
    window = int(getattr(settings, 'PUBLIC_LEAD_RATE_LIMIT_WINDOW', 3600))
    key = f'public_lead:{_client_ip(request)}'
    count = cache.get(key, 0)
    if count >= limit:
        return True
    if count:
        cache.incr(key)
    else:
        cache.set(key, 1, window)
    return False


def _initial_acquisition(request):
    initial = {field: request.GET.get(field, '') for field in ACQUISITION_FIELDS}
    if initial.get('billing_preference') not in PublicLead.BillingPreference.values:
        initial['billing_preference'] = ''
    return initial


def _whatsapp_url(message=None, phone=None):
    number = phone or getattr(settings, 'PUBLIC_WHATSAPP_NUMBER', '')
    digits = ''.join(ch for ch in number if ch.isdigit())
    if not digits:
        return ''
    text = message or getattr(
        settings,
        'PUBLIC_WHATSAPP_MESSAGE',
        'Ol\u00e1! Conheci a Estribo e gostaria de entender como a plataforma pode ajudar na gest\u00e3o da minha construtora.',
    )
    return f'https://wa.me/{digits}?text={quote(text)}'


def _notify_new_lead():
    destination = getattr(settings, 'PUBLIC_LEAD_NOTIFICATION_EMAIL', '')
    if not destination:
        return
    try:
        send_mail(
            'Novo lead Estribo',
            'Um novo lead foi recebido pela landing da Estribo. Acesse a plataforma para consultar os detalhes.',
            getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
            [destination],
            fail_silently=False,
        )
    except Exception:
        logger.warning('public_lead_notification_failed', exc_info=True)


def _base_context(request):
    return {
        'faqs': FAQS,
        'whatsapp_url': _whatsapp_url(),
        'public_ga4_id': getattr(settings, 'PUBLIC_GA4_ID', ''),
        'public_google_ads_id': getattr(settings, 'PUBLIC_GOOGLE_ADS_ID', ''),
        'public_meta_pixel_id': getattr(settings, 'PUBLIC_META_PIXEL_ID', ''),
    }


def home(request):
    lead_created = False
    bot_discarded = False
    if request.method == 'POST':
        form = PublicLeadForm(request.POST)
        if request.POST.get('website'):
            lead_created = True
            bot_discarded = True
        elif _rate_limited(request):
            form.add_error(None, 'Recebemos muitas solicita\u00e7\u00f5es deste acesso. Tente novamente mais tarde.')
        elif form.is_valid():
            lead = form.save(commit=False)
            lead.referrer = request.META.get('HTTP_REFERER', '')[:500]
            lead.landing_path = lead.landing_path or request.get_full_path()[:300]
            lead.save()
            _notify_new_lead()
            lead_created = True
            form = PublicLeadForm(initial=_initial_acquisition(request))
    else:
        form = PublicLeadForm(initial=_initial_acquisition(request))

    context = {
        **_base_context(request),
        'lead_form': form,
        'lead_created': lead_created,
        'bot_discarded': bot_discarded,
    }
    return render(request, 'site_publico/home.html', context)


def privacidade(request):
    context = {
        **_base_context(request),
        'page_title': 'Pol\u00edtica de Privacidade | Estribo',
        'meta_description': 'Pol\u00edtica de Privacidade inicial da Estribo.',
    }
    return render(request, 'site_publico/privacidade.html', context)


def termos(request):
    context = {
        **_base_context(request),
        'page_title': 'Termos de Uso | Estribo',
        'meta_description': 'Termos de Uso institucionais iniciais da Estribo.',
    }
    return render(request, 'site_publico/termos.html', context)


def _exigir_staff(request):
    if request.user.is_staff or request.user.is_superuser:
        return None
    return HttpResponseForbidden('Voc\u00ea n\u00e3o tem permiss\u00e3o para acessar esta \u00e1rea.')


@login_required
def leads_plataforma(request):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio

    leads = PublicLead.objects.all()
    busca = request.GET.get('busca', '').strip()
    status = request.GET.get('status', '').strip()
    utm_source = request.GET.get('utm_source', '').strip()
    utm_campaign = request.GET.get('utm_campaign', '').strip()
    data_inicio = parse_date(request.GET.get('data_inicio', ''))
    data_fim = parse_date(request.GET.get('data_fim', ''))

    if busca:
        leads = leads.filter(
            Q(nome__icontains=busca)
            | Q(empresa__icontains=busca)
            | Q(email__icontains=busca)
            | Q(telefone__icontains=busca)
        )
    if status:
        leads = leads.filter(status=status)
    if utm_source:
        leads = leads.filter(utm_source__icontains=utm_source)
    if utm_campaign:
        leads = leads.filter(utm_campaign__icontains=utm_campaign)
    if data_inicio:
        leads = leads.filter(created_at__date__gte=data_inicio)
    if data_fim:
        leads = leads.filter(created_at__date__lte=data_fim)

    paginator = Paginator(leads, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(
        request,
        'site_publico/plataforma/leads.html',
        {
            'page_obj': page_obj,
            'status_choices': PublicLead.Status.choices,
            'filtros': {
                'busca': busca,
                'status': status,
                'utm_source': utm_source,
                'utm_campaign': utm_campaign,
                'data_inicio': request.GET.get('data_inicio', ''),
                'data_fim': request.GET.get('data_fim', ''),
            },
        },
    )


@login_required
def detalhe_lead_plataforma(request, lead_id):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio

    lead = get_object_or_404(PublicLead, pk=lead_id)
    if request.method == 'POST':
        form = PublicLeadStatusForm(request.POST, instance=lead)
        if form.is_valid():
            form.save()
            messages.success(request, 'Lead atualizado com sucesso.')
            return redirect('detalhe_lead_plataforma', lead_id=lead.id)
    else:
        form = PublicLeadStatusForm(instance=lead)

    return render(
        request,
        'site_publico/plataforma/detalhe_lead.html',
        {
            'lead': lead,
            'form': form,
            'whatsapp_lead_url': _whatsapp_url(phone=lead.telefone_normalizado or lead.telefone),
        },
    )
