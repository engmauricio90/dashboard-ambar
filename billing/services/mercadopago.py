import hashlib
import hmac
import json
import logging
from decimal import Decimal
from urllib import error, request

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from billing.models import Assinatura, EventoWebhook, Pagamento
from billing.services.comercial import meses_periodicidade, periodo_inicial, valor_periodicidade


logger = logging.getLogger(__name__)


class MercadoPagoError(Exception):
    pass


class MercadoPagoUnavailable(MercadoPagoError):
    pass


def _api_base_url():
    return 'https://api.mercadopago.com'


def _setting(name, default=''):
    return getattr(settings, name, default)


def mercadopago_configurado():
    return bool(_setting('MERCADOPAGO_ACCESS_TOKEN'))


def _request_json(method, path, payload=None, idempotency_key=''):
    token = _setting('MERCADOPAGO_ACCESS_TOKEN')
    if not token:
        raise MercadoPagoUnavailable('MERCADOPAGO_ACCESS_TOKEN nao configurado.')
    data = None
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if idempotency_key:
        headers['X-Idempotency-Key'] = idempotency_key
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    req = request.Request(f'{_api_base_url()}{path}', data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=20) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')[:400]
        logger.warning('mercadopago_http_error status=%s body=%s', exc.code, body)
        raise MercadoPagoError(f'Erro Mercado Pago HTTP {exc.code}.') from exc
    except error.URLError as exc:
        logger.warning('mercadopago_unavailable reason=%s', exc.reason)
        raise MercadoPagoUnavailable('Mercado Pago indisponivel.') from exc


def criar_assinatura_recorrente(assinatura, payer_email='', back_url='', idempotency_key=''):
    payload = {
        'reason': 'Estribo - Plano unico',
        'external_reference': f'assinatura:{assinatura.id}',
        'auto_recurring': {
            'frequency': meses_periodicidade(assinatura.periodicidade),
            'frequency_type': 'months',
            'transaction_amount': str(Decimal(assinatura.valor_contratado)),
            'currency_id': assinatura.moeda,
        },
    }
    if payer_email:
        payload['payer_email'] = payer_email
    if back_url:
        payload['back_url'] = back_url

    data = _request_json('POST', '/preapproval', payload=payload, idempotency_key=idempotency_key)
    assinatura.gateway_subscription_id = str(data.get('id') or '')
    assinatura.gateway_plan_id = str(data.get('preapproval_plan_id') or '')
    assinatura.checkout_url = data.get('init_point') or data.get('sandbox_init_point') or ''
    assinatura.save(update_fields=['gateway_subscription_id', 'gateway_plan_id', 'checkout_url', 'atualizado_em'])
    return data


def criar_checkout_intent_recorrente(intent, payer_email='', back_url='', idempotency_key=''):
    payload = {
        'reason': 'Estribo - Plano unico',
        'external_reference': intent.external_reference,
        'auto_recurring': {
            'frequency': meses_periodicidade(intent.periodicidade),
            'frequency_type': 'months',
            'transaction_amount': str(Decimal(valor_periodicidade(intent.periodicidade))),
            'currency_id': 'BRL',
        },
        'status': 'pending',
    }
    if payer_email:
        payload['payer_email'] = payer_email
    if back_url:
        payload['back_url'] = back_url
    return _request_json('POST', '/preapproval', payload=payload, idempotency_key=idempotency_key)


def consultar_assinatura_gateway(gateway_subscription_id):
    if not gateway_subscription_id:
        raise MercadoPagoError('Assinatura sem identificador Mercado Pago.')
    return _request_json('GET', f'/preapproval/{gateway_subscription_id}')


def consultar_pagamento_gateway(payment_id):
    if not payment_id:
        raise MercadoPagoError('Pagamento sem identificador Mercado Pago.')
    return _request_json('GET', f'/v1/payments/{payment_id}')


def consultar_pagamento_autorizado_gateway(authorized_payment_id):
    if not authorized_payment_id:
        raise MercadoPagoError('Pagamento autorizado sem identificador Mercado Pago.')
    return _request_json('GET', f'/authorized_payments/{authorized_payment_id}')


def cancelar_assinatura_gateway(assinatura):
    if not assinatura.gateway_subscription_id:
        return {}
    return _request_json('PUT', f'/preapproval/{assinatura.gateway_subscription_id}', payload={'status': 'canceled'})


def webhook_payload_hash(body):
    return hashlib.sha256(body).hexdigest()


def _signature_parts(signature):
    parts = {}
    for item in signature.split(','):
        if '=' not in item:
            continue
        key, value = item.split('=', 1)
        parts[key.strip()] = value.strip()
    return parts


def validar_assinatura_webhook(body, headers, data_id=''):
    secret = _setting('MERCADOPAGO_WEBHOOK_SECRET')
    environment = _setting('MERCADOPAGO_ENVIRONMENT', 'sandbox')
    if not secret:
        return environment != 'production'
    signature = headers.get('x-signature') or headers.get('X-Signature') or ''
    request_id = headers.get('x-request-id') or headers.get('X-Request-Id') or ''
    if not signature:
        return False
    parts = _signature_parts(signature)
    received = parts.get('v1') or signature
    candidates = [body]
    if parts.get('ts') and request_id and data_id:
        candidates.insert(0, f'id:{data_id};request-id:{request_id};ts:{parts["ts"]};'.encode('utf-8'))
    return any(
        hmac.compare_digest(hmac.new(secret.encode('utf-8'), candidate, hashlib.sha256).hexdigest(), received)
        for candidate in candidates
    )


def _event_id(payload, headers, payload_hash):
    explicit = payload.get('id') or payload.get('event_id')
    if explicit:
        return str(explicit)
    request_id = headers.get('x-request-id') or headers.get('X-Request-Id')
    if request_id:
        return str(request_id)
    return payload_hash


def _resource_id(payload):
    data = payload.get('data')
    if isinstance(data, dict) and data.get('id'):
        return str(data['id'])
    resource = payload.get('resource')
    if resource:
        return str(resource).rstrip('/').split('/')[-1]
    return ''


def _event_type(payload):
    return str(payload.get('type') or payload.get('action') or payload.get('topic') or '')


def normalizar_status_pagamento(raw_status):
    status = str(raw_status or '').lower()
    if status in {'approved', 'authorized'}:
        return Pagamento.Status.APROVADO
    if status in {'rejected', 'cancelled', 'refunded', 'charged_back'}:
        if status == 'refunded':
            return Pagamento.Status.ESTORNADO
        if status == 'cancelled':
            return Pagamento.Status.CANCELADO
        return Pagamento.Status.RECUSADO
    if status in {'in_process', 'pending'}:
        return Pagamento.Status.EM_PROCESSAMENTO if status == 'in_process' else Pagamento.Status.PENDENTE
    return Pagamento.Status.PENDENTE


def normalizar_pagamento_autorizado(data):
    payment = data.get('payment') if isinstance(data.get('payment'), dict) else {}
    return {
        'id': payment.get('id') or '',
        'invoice_id': data.get('id') or '',
        'status': payment.get('status') or data.get('summarized') or data.get('status') or '',
        'transaction_amount': data.get('transaction_amount') or data.get('amount'),
        'currency_id': data.get('currency_id'),
        'external_reference': data.get('external_reference'),
        'preapproval_id': data.get('preapproval_id'),
        'payment_method_id': payment.get('payment_method_id') or '',
        'date_created': data.get('date_created'),
    }


def _assinatura_por_referencia(data):
    reference = str(data.get('external_reference') or '')
    if reference.startswith('assinatura:'):
        assinatura_id = reference.split(':', 1)[1]
        return Assinatura.objects.filter(pk=assinatura_id).first()
    if reference.startswith('estribo_checkout_'):
        from billing.models import CheckoutIntent

        intent = CheckoutIntent.objects.select_related('assinatura').filter(external_reference=reference).first()
        return intent.assinatura if intent else None
    preapproval_id = str(data.get('preapproval_id') or data.get('preapproval') or '')
    if preapproval_id:
        return Assinatura.objects.filter(gateway_subscription_id=preapproval_id).first()
    return None


def aplicar_pagamento_gateway(data):
    from billing.services.self_service import processar_checkout_gateway

    processar_checkout_gateway(data)
    assinatura = _assinatura_por_referencia(data)
    if not assinatura:
        return None
    valor = Decimal(str(data.get('transaction_amount') or data.get('amount') or assinatura.valor_contratado))
    raw_status = str(data.get('status') or '')[:80]
    status = normalizar_status_pagamento(raw_status)
    gateway_payment_id = str(data.get('id') or '')
    gateway_invoice_id = str(data.get('invoice_id') or '')
    pagamento = None
    if gateway_payment_id:
        pagamento = Pagamento.objects.filter(
            assinatura=assinatura,
            gateway=Assinatura.Gateway.MERCADOPAGO,
            gateway_payment_id=gateway_payment_id,
        ).first()
    if pagamento is None and gateway_invoice_id:
        pagamento = Pagamento.objects.filter(
            assinatura=assinatura,
            gateway=Assinatura.Gateway.MERCADOPAGO,
            gateway_invoice_id=gateway_invoice_id,
        ).first()
    if pagamento is None:
        pagamento = Pagamento(
            assinatura=assinatura,
            gateway=Assinatura.Gateway.MERCADOPAGO,
        )
    pagamento.gateway_payment_id = gateway_payment_id or pagamento.gateway_payment_id
    pagamento.gateway_invoice_id = gateway_invoice_id or pagamento.gateway_invoice_id
    pagamento.valor = valor
    pagamento.moeda = str(data.get('currency_id') or assinatura.moeda)[:3]
    pagamento.status = status
    pagamento.forma_pagamento = str(data.get('payment_method_id') or data.get('payment_type_id') or '')[:80]
    pagamento.parcelas = data.get('installments') or None
    pagamento.raw_status = raw_status
    pagamento.paid_at = timezone.now() if status == Pagamento.Status.APROVADO else pagamento.paid_at
    pagamento.failed_at = timezone.now() if status == Pagamento.Status.RECUSADO else pagamento.failed_at
    pagamento.save()
    if status == Pagamento.Status.APROVADO:
        inicio, fim, proxima = periodo_inicial(assinatura.periodicidade, timezone.now())
        assinatura.marcar_ativa(inicio=inicio, fim_periodo=fim, proxima_cobranca=proxima)
    elif status == Pagamento.Status.RECUSADO:
        assinatura.registrar_falha_pagamento()
    return pagamento


def aplicar_assinatura_gateway(data):
    from billing.services.self_service import processar_checkout_gateway

    processar_checkout_gateway(data)
    assinatura = _assinatura_por_referencia(data)
    if not assinatura:
        gateway_id = str(data.get('id') or '')
        assinatura = Assinatura.objects.filter(gateway_subscription_id=gateway_id).first()
    if not assinatura:
        return None
    gateway_status = str(data.get('status') or '').lower()
    agora = timezone.now()
    if gateway_status in {'authorized', 'active'}:
        if not (assinatura.cancel_at_period_end and assinatura.data_fim_periodo and assinatura.data_fim_periodo <= agora):
            assinatura.marcar_ativa()
    elif gateway_status == 'paused':
        assinatura.registrar_falha_pagamento()
    elif gateway_status in {'cancelled', 'canceled'}:
        if assinatura.cancel_at_period_end and assinatura.data_fim_periodo and assinatura.data_fim_periodo > agora:
            assinatura.status = Assinatura.Status.ATIVA
            assinatura.canceled_at = assinatura.canceled_at or agora
            assinatura.save(update_fields=['status', 'canceled_at', 'atualizado_em'])
        else:
            assinatura.status = Assinatura.Status.CANCELADA
            assinatura.canceled_at = assinatura.canceled_at or agora
            assinatura.save(update_fields=['status', 'canceled_at', 'atualizado_em'])
    return assinatura


@transaction.atomic
def registrar_webhook(
    payload,
    headers=None,
    body=None,
    service_consultar_pagamento=None,
    service_consultar_pagamento_autorizado=None,
    service_consultar_assinatura=None,
):
    headers = headers or {}
    body = body if body is not None else json.dumps(payload, sort_keys=True).encode('utf-8')
    payload_hash = webhook_payload_hash(body)
    evento, created = EventoWebhook.objects.get_or_create(
        gateway=Assinatura.Gateway.MERCADOPAGO,
        event_id=_event_id(payload, headers, payload_hash),
        defaults={
            'event_type': _event_type(payload),
            'resource_id': _resource_id(payload),
            'payload_hash': payload_hash,
        },
    )
    if not created:
        return evento, False

    try:
        resource_id = evento.resource_id
        event_type = evento.event_type
        data = None
        if resource_id and event_type == 'subscription_authorized_payment':
            consultar = service_consultar_pagamento_autorizado or consultar_pagamento_autorizado_gateway
            data = normalizar_pagamento_autorizado(consultar(resource_id))
            aplicar_pagamento_gateway(data)
        elif resource_id and event_type == 'subscription_preapproval':
            consultar = service_consultar_assinatura or consultar_assinatura_gateway
            data = consultar(resource_id)
            aplicar_assinatura_gateway(data)
        elif resource_id and (event_type == 'payment' or event_type.startswith('payment.') or payload.get('topic') == 'payment'):
            consultar = service_consultar_pagamento or consultar_pagamento_gateway
            data = consultar(resource_id)
            aplicar_pagamento_gateway(data)
        evento.status_processamento = EventoWebhook.StatusProcessamento.PROCESSADO
        evento.processed_at = timezone.now()
        evento.save(update_fields=['status_processamento', 'processed_at'])
    except MercadoPagoUnavailable:
        evento.status_processamento = EventoWebhook.StatusProcessamento.RECEBIDO
        evento.save(update_fields=['status_processamento'])
        return evento, True
    except Exception:
        evento.status_processamento = EventoWebhook.StatusProcessamento.ERRO
        evento.processed_at = timezone.now()
        evento.save(update_fields=['status_processamento', 'processed_at'])
        raise
    return evento, True
