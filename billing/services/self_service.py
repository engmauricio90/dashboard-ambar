import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from billing.models import Assinatura, CheckoutIntent
from billing.services.comercial import periodo_inicial, valor_periodicidade
from empresas.emails import enviar_convite_usuario_empresa
from empresas.services import criar_cliente_assistido


def external_reference_checkout(public_id):
    return f'estribo_checkout_{public_id.hex}'


def criar_checkout_intent(dados, referrer=''):
    public_id = uuid.uuid4()
    return CheckoutIntent.objects.create(
        public_id=public_id,
        external_reference=external_reference_checkout(public_id),
        nome_empresa=dados['nome_empresa'].strip(),
        nome_responsavel=dados['nome_responsavel'].strip(),
        email=dados['email'].strip().lower(),
        telefone=dados['telefone'].strip(),
        periodicidade=dados['periodicidade'],
        utm_source=dados.get('utm_source', '')[:120],
        utm_medium=dados.get('utm_medium', '')[:120],
        utm_campaign=dados.get('utm_campaign', '')[:160],
        utm_content=dados.get('utm_content', '')[:160],
        utm_term=dados.get('utm_term', '')[:160],
        gclid=dados.get('gclid', '')[:200],
        fbclid=dados.get('fbclid', '')[:200],
        referrer=(referrer or '')[:500],
        consent_at=timezone.now(),
        expires_at=timezone.now() + timezone.timedelta(days=7),
    )


def _separar_nome(nome):
    partes = nome.strip().split(maxsplit=1)
    return partes[0], partes[1] if len(partes) > 1 else ''


def converter_checkout_intent(intent_id):
    convite = None
    with transaction.atomic():
        intent = CheckoutIntent.objects.select_for_update().select_related('empresa', 'assinatura').get(pk=intent_id)
        if intent.status == CheckoutIntent.Status.CONVERTIDO:
            return intent
        if intent.status != CheckoutIntent.Status.PAGO:
            return intent
        if get_user_model().objects.filter(email__iexact=intent.email).exists():
            intent.status = CheckoutIntent.Status.FALHOU
            intent.save(update_fields=['status', 'updated_at'])
            return intent

        first_name, last_name = _separar_nome(intent.nome_responsavel)
        grupo = Group.objects.filter(name='Diretoria').first()
        onboarding = criar_cliente_assistido({
            'nome': intent.nome_empresa,
            'email': intent.email,
            'telefone': intent.telefone,
            'admin_email': intent.email,
            'admin_first_name': first_name,
            'admin_last_name': last_name,
            'admin_grupo': grupo,
        })
        inicio, fim, proxima = periodo_inicial(intent.periodicidade)
        assinatura = Assinatura.objects.create(
            empresa=onboarding['empresa'],
            periodicidade=intent.periodicidade,
            valor_contratado=valor_periodicidade(intent.periodicidade),
            moeda='BRL',
            status=Assinatura.Status.ATIVA,
            data_inicio=inicio,
            data_fim_periodo=fim,
            proxima_cobranca=proxima,
            gateway=Assinatura.Gateway.MERCADOPAGO,
            gateway_subscription_id=intent.gateway_subscription_id,
            checkout_url=intent.gateway_checkout_url,
        )
        intent.empresa = onboarding['empresa']
        intent.assinatura = assinatura
        intent.status = CheckoutIntent.Status.CONVERTIDO
        intent.converted_at = timezone.now()
        intent.save(update_fields=['empresa', 'assinatura', 'status', 'converted_at', 'updated_at'])
        convite = onboarding['vinculo']

    if convite:
        enviar_convite_usuario_empresa(None, convite)
    return CheckoutIntent.objects.select_related('empresa', 'assinatura').get(pk=intent_id)


def processar_checkout_gateway(data):
    reference = str(data.get('external_reference') or '')
    intent = CheckoutIntent.objects.filter(external_reference=reference).first()
    if not intent:
        preapproval_id = str(data.get('preapproval_id') or data.get('preapproval') or '')
        if preapproval_id:
            intent = CheckoutIntent.objects.filter(gateway_subscription_id=preapproval_id).first()
    if not intent:
        return None

    if intent.status == CheckoutIntent.Status.CONVERTIDO:
        return intent

    raw_status = str(data.get('status') or '').lower()
    if raw_status in {'approved', 'authorized'}:
        intent.status = CheckoutIntent.Status.PAGO
        intent.save(update_fields=['status', 'updated_at'])
        return converter_checkout_intent(intent.id)
    if raw_status in {'rejected', 'cancelled', 'canceled'}:
        intent.status = CheckoutIntent.Status.FALHOU if raw_status == 'rejected' else CheckoutIntent.Status.CANCELADO
        intent.save(update_fields=['status', 'updated_at'])
    elif intent.status == CheckoutIntent.Status.CHECKOUT_CRIADO:
        intent.status = CheckoutIntent.Status.AGUARDANDO_PAGAMENTO
        intent.save(update_fields=['status', 'updated_at'])
    return intent
