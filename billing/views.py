import json
from urllib.parse import urljoin

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from empresas.models import Empresa
from site_publico.models import PublicLead

from config.rate_limit import check_rate_limit, client_ip

from .forms import AssinaturaFiltroForm, CheckoutIntentFiltroForm, CheckoutIntentForm, PrepararContratacaoForm
from .models import Assinatura, CheckoutIntent
from .services.comercial import PERIODICIDADE_CONFIG, periodo_inicial, valor_periodicidade
from .services.entitlements import assinatura_atual, motivo_bloqueio
from .services.mercadopago import (
    MercadoPagoError,
    MercadoPagoUnavailable,
    criar_checkout_intent_recorrente,
    criar_assinatura_recorrente,
    mercadopago_configurado,
    registrar_webhook,
    validar_assinatura_webhook,
)
from .services.self_service import criar_checkout_intent


def _exigir_staff(request):
    if request.user.is_staff or request.user.is_superuser:
        return None
    return HttpResponseForbidden('Voce nao tem permissao para acessar esta area.')


def _public_context():
    return {
        'public_ga4_id': getattr(settings, 'PUBLIC_GA4_ID', ''),
        'public_google_ads_id': getattr(settings, 'PUBLIC_GOOGLE_ADS_ID', ''),
        'public_meta_pixel_id': getattr(settings, 'PUBLIC_META_PIXEL_ID', ''),
    }


def _periodicidade_query(value):
    mapping = {
        'mensal': Assinatura.Periodicidade.MENSAL,
        'semestral': Assinatura.Periodicidade.SEMESTRAL,
        'anual': Assinatura.Periodicidade.ANUAL,
    }
    return mapping.get(str(value or '').lower(), Assinatura.Periodicidade.ANUAL)


def _payer_email(intent):
    if str(getattr(settings, 'MERCADOPAGO_ENVIRONMENT', '')).lower() == 'test':
        return getattr(settings, 'MERCADOPAGO_TEST_PAYER_EMAIL', '') or 'test@testuser.com'
    return intent.email


def checkout_publico(request):
    initial = {'periodicidade': _periodicidade_query(request.GET.get('periodo'))}
    for field in ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'fbclid'):
        initial[field] = request.GET.get(field, '')
    form = CheckoutIntentForm(request.POST or None, initial=initial)
    if request.method == 'POST':
        blocked, _count = check_rate_limit(
            'public_checkout', [client_ip(request)],
            getattr(settings, 'PUBLIC_CHECKOUT_RATE_LIMIT', 5),
            getattr(settings, 'PUBLIC_CHECKOUT_RATE_LIMIT_WINDOW', 3600),
        )
        if blocked:
            return HttpResponse('Muitas tentativas em pouco tempo. Aguarde e tente novamente.', status=429)
        if request.POST.get('website'):
            return redirect('public_home')
        if form.is_valid():
            public_base_url = getattr(settings, 'PUBLIC_BASE_URL', '').rstrip('/')
            if not public_base_url or not public_base_url.startswith('https://'):
                form.add_error(None, 'O checkout ainda não está disponível. Fale com nosso time para contratar.')
            elif not mercadopago_configurado():
                form.add_error(None, 'O checkout ainda não está disponível. Fale com nosso time para contratar.')
            else:
                intent = criar_checkout_intent(
                    form.cleaned_data,
                    referrer=request.META.get('HTTP_REFERER', ''),
                )
                back_path = reverse('billing:checkout_retorno', args=[intent.public_id])
                try:
                    gateway = criar_checkout_intent_recorrente(
                        intent,
                        payer_email=_payer_email(intent),
                        back_url=urljoin(public_base_url + '/', back_path.lstrip('/')),
                        idempotency_key=f'checkout-{intent.public_id}',
                    )
                except MercadoPagoError:
                    intent.status = CheckoutIntent.Status.FALHOU
                    intent.save(update_fields=['status', 'updated_at'])
                    form.add_error(None, 'Não foi possível abrir o pagamento agora. Tente novamente mais tarde.')
                else:
                    intent.gateway_subscription_id = str(gateway.get('id') or '')
                    intent.gateway_checkout_url = gateway.get('init_point') or gateway.get('sandbox_init_point') or ''
                    intent.status = (
                        CheckoutIntent.Status.CHECKOUT_CRIADO
                        if intent.gateway_checkout_url
                        else CheckoutIntent.Status.FALHOU
                    )
                    intent.save(update_fields=['gateway_subscription_id', 'gateway_checkout_url', 'status', 'updated_at'])
                    if intent.gateway_checkout_url:
                        return redirect(intent.gateway_checkout_url)
                    form.add_error(None, 'O Mercado Pago não retornou uma URL de pagamento válida.')
    return render(request, 'billing/checkout_publico.html', {
        **_public_context(), 'form': form, 'periodicidades': PERIODICIDADE_CONFIG,
    })


def checkout_retorno(request, public_id):
    intent = get_object_or_404(
        CheckoutIntent.objects.select_related('empresa', 'assinatura'), public_id=public_id,
    )
    return render(request, 'billing/checkout_retorno.html', {
        **_public_context(), 'intent': intent,
    })


@login_required
def contratacoes_plataforma(request):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio
    form = CheckoutIntentFiltroForm(request.GET)
    intents = CheckoutIntent.objects.select_related('empresa', 'assinatura')
    if form.is_valid():
        filtros = form.cleaned_data
        if filtros.get('status'):
            intents = intents.filter(status=filtros['status'])
        if filtros.get('periodicidade'):
            intents = intents.filter(periodicidade=filtros['periodicidade'])
        if filtros.get('data_inicio'):
            intents = intents.filter(created_at__date__gte=filtros['data_inicio'])
        if filtros.get('data_fim'):
            intents = intents.filter(created_at__date__lte=filtros['data_fim'])
        if filtros.get('utm_source'):
            intents = intents.filter(utm_source__icontains=filtros['utm_source'])
        busca = (filtros.get('busca') or '').strip()
        if busca:
            intents = intents.filter(
                Q(nome_empresa__icontains=busca) | Q(nome_responsavel__icontains=busca) | Q(email__icontains=busca)
            )
    page_obj = Paginator(intents, 25).get_page(request.GET.get('page'))
    return render(request, 'billing/contratacoes.html', {'form': form, 'page_obj': page_obj})


@login_required
def detalhe_contratacao_plataforma(request, intent_id):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio
    intent = get_object_or_404(CheckoutIntent.objects.select_related('empresa', 'assinatura'), pk=intent_id)
    return render(request, 'billing/detalhe_contratacao.html', {'intent': intent})


@login_required
def assinatura_pendente(request):
    empresa = getattr(request, 'empresa', None)
    assinatura = assinatura_atual(empresa)
    return render(
        request,
        'billing/assinatura_pendente.html',
        {
            'empresa': empresa,
            'assinatura': assinatura,
            'motivo': motivo_bloqueio(empresa),
        },
        status=402,
    )


@login_required
def preparar_contratacao(request, lead_id):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio
    lead = get_object_or_404(PublicLead, pk=lead_id)
    initial_periodicidade = lead.billing_preference or Assinatura.Periodicidade.ANUAL

    if request.method == 'POST':
        form = PrepararContratacaoForm(request.POST, initial_periodicidade=initial_periodicidade)
        if form.is_valid():
            empresa = form.cleaned_data['empresa']
            periodicidade = form.cleaned_data['periodicidade']
            assinatura, created = Assinatura.objects.get_or_create(
                empresa=empresa,
                lead_origem=lead,
                status=Assinatura.Status.PENDENTE,
                defaults={
                    'periodicidade': periodicidade,
                    'valor_contratado': valor_periodicidade(periodicidade),
                    'moeda': 'BRL',
                },
            )
            if not created:
                assinatura.periodicidade = periodicidade
                assinatura.valor_contratado = valor_periodicidade(periodicidade)
                assinatura.save(update_fields=['periodicidade', 'valor_contratado', 'atualizado_em'])
            if mercadopago_configurado():
                try:
                    criar_assinatura_recorrente(
                        assinatura,
                        payer_email=lead.email,
                        back_url=request.build_absolute_uri(reverse('detalhe_assinatura_plataforma', args=[assinatura.id])),
                        idempotency_key=f'assinatura-{assinatura.id}-preapproval',
                    )
                    messages.success(request, 'Contratacao preparada com checkout Mercado Pago.')
                except MercadoPagoError:
                    messages.warning(request, 'Assinatura criada, mas nao foi possivel preparar o checkout agora.')
            else:
                messages.info(request, 'Assinatura preparada sem chamar o Mercado Pago porque as credenciais nao estao configuradas.')
            return redirect('detalhe_assinatura_plataforma', assinatura_id=assinatura.id)
    else:
        form = PrepararContratacaoForm(initial_periodicidade=initial_periodicidade)

    return render(
        request,
        'billing/preparar_contratacao.html',
        {
            'lead': lead,
            'form': form,
            'periodicidades': PERIODICIDADE_CONFIG,
        },
    )


@login_required
def assinaturas_plataforma(request):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio
    form = AssinaturaFiltroForm(request.GET)
    assinaturas = Assinatura.objects.select_related('empresa', 'lead_origem').order_by('-criado_em')
    if form.is_valid():
        status = form.cleaned_data.get('status')
        periodicidade = form.cleaned_data.get('periodicidade')
        busca = form.cleaned_data.get('busca', '').strip()
        if status:
            assinaturas = assinaturas.filter(status=status)
        if periodicidade:
            assinaturas = assinaturas.filter(periodicidade=periodicidade)
        if busca:
            assinaturas = assinaturas.filter(
                Q(empresa__nome__icontains=busca)
                | Q(empresa__razao_social__icontains=busca)
                | Q(empresa__cnpj__icontains=busca)
            )
    paginator = Paginator(assinaturas, 25)
    return render(
        request,
        'billing/assinaturas.html',
        {
            'form': form,
            'page_obj': paginator.get_page(request.GET.get('page')),
        },
    )


@login_required
def detalhe_assinatura_plataforma(request, assinatura_id):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio
    assinatura = get_object_or_404(
        Assinatura.objects.select_related('empresa', 'lead_origem').prefetch_related('pagamentos'),
        pk=assinatura_id,
    )
    return render(
        request,
        'billing/detalhe_assinatura.html',
        {
            'assinatura': assinatura,
            'pagamentos': assinatura.pagamentos.all(),
        },
    )


@login_required
@require_POST
def ativar_assinatura_manual(request, assinatura_id):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio
    assinatura = get_object_or_404(Assinatura, pk=assinatura_id)
    inicio, fim, proxima = periodo_inicial(assinatura.periodicidade)
    assinatura.marcar_ativa(inicio=inicio, fim_periodo=fim, proxima_cobranca=proxima)
    messages.success(request, 'Assinatura ativada manualmente.')
    return redirect('detalhe_assinatura_plataforma', assinatura_id=assinatura.id)


@login_required
@require_POST
def cancelar_assinatura(request, assinatura_id):
    bloqueio = _exigir_staff(request)
    if bloqueio:
        return bloqueio
    assinatura = get_object_or_404(Assinatura, pk=assinatura_id)
    assinatura.cancel_at_period_end = True
    assinatura.canceled_at = None
    assinatura.save(update_fields=['cancel_at_period_end', 'canceled_at', 'atualizado_em'])
    messages.success(request, 'Cancelamento agendado para o fim do periodo. O acesso permanece ativo ate essa data.')
    return redirect('detalhe_assinatura_plataforma', assinatura_id=assinatura.id)


@csrf_exempt
@require_POST
def mercadopago_webhook(request):
    body = request.body
    try:
        payload = json.loads(body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Payload invalido.')
    data_id = ''
    if isinstance(payload.get('data'), dict):
        data_id = payload['data'].get('id') or ''
    data_id = request.GET.get('data.id') or request.GET.get('data_id') or data_id
    if not validar_assinatura_webhook(body, request.headers, data_id=data_id):
        return HttpResponseForbidden('Assinatura invalida.')
    try:
        evento, created = registrar_webhook(payload, headers=request.headers, body=body)
    except MercadoPagoUnavailable:
        return JsonResponse({'status': 'received_gateway_unavailable'})
    except Exception:
        return JsonResponse({'status': 'error'}, status=500)
    return JsonResponse({'status': 'processed' if created else 'ignored', 'event_id': evento.event_id})
