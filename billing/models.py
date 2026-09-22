import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Assinatura(models.Model):
    class Periodicidade(models.TextChoices):
        MENSAL = 'MENSAL', 'Mensal'
        SEMESTRAL = 'SEMESTRAL', 'Semestral'
        ANUAL = 'ANUAL', 'Anual'

    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        ATIVA = 'ATIVA', 'Ativa'
        EM_ATRASO = 'EM_ATRASO', 'Em atraso'
        SUSPENSA = 'SUSPENSA', 'Suspensa'
        CANCELADA = 'CANCELADA', 'Cancelada'
        EXPIRADA = 'EXPIRADA', 'Expirada'

    class Gateway(models.TextChoices):
        MERCADOPAGO = 'MERCADOPAGO', 'Mercado Pago'
        INTERNO = 'INTERNO', 'Interno'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='assinaturas')
    lead_origem = models.ForeignKey(
        'site_publico.PublicLead',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='assinaturas',
    )
    periodicidade = models.CharField(max_length=16, choices=Periodicidade.choices)
    valor_contratado = models.DecimalField(max_digits=10, decimal_places=2)
    moeda = models.CharField(max_length=3, default='BRL')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDENTE)
    data_inicio = models.DateTimeField(blank=True, null=True)
    data_fim_periodo = models.DateTimeField(blank=True, null=True)
    proxima_cobranca = models.DateTimeField(blank=True, null=True)
    grace_until = models.DateTimeField(blank=True, null=True)
    gateway = models.CharField(max_length=24, choices=Gateway.choices, default=Gateway.MERCADOPAGO)
    gateway_subscription_id = models.CharField(max_length=120, blank=True, db_index=True)
    gateway_plan_id = models.CharField(max_length=120, blank=True)
    checkout_url = models.URLField(max_length=700, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['empresa', 'status']),
            models.Index(fields=['gateway', 'gateway_subscription_id']),
            models.Index(fields=['status', 'proxima_cobranca']),
        ]

    def __str__(self):
        return f'{self.empresa} - {self.get_periodicidade_display()} - {self.get_status_display()}'

    def em_tolerancia(self, agora=None):
        agora = agora or timezone.now()
        return self.status == self.Status.EM_ATRASO and self.grace_until and self.grace_until >= agora

    def permite_acesso(self, agora=None):
        if self.status == self.Status.ATIVA:
            return True
        return bool(self.em_tolerancia(agora=agora))

    def registrar_falha_pagamento(self, quando=None):
        quando = quando or timezone.now()
        self.status = self.Status.EM_ATRASO
        self.grace_until = quando + timezone.timedelta(days=getattr(settings, 'BILLING_GRACE_DAYS', 5))
        self.save(update_fields=['status', 'grace_until', 'atualizado_em'])

    def avaliar_suspensao(self, agora=None):
        agora = agora or timezone.now()
        if self.status == self.Status.EM_ATRASO and self.grace_until and self.grace_until < agora:
            self.status = self.Status.SUSPENSA
            self.save(update_fields=['status', 'atualizado_em'])
            return True
        return False

    def marcar_ativa(self, inicio=None, fim_periodo=None, proxima_cobranca=None):
        inicio = inicio or timezone.now()
        self.status = self.Status.ATIVA
        self.data_inicio = self.data_inicio or inicio
        self.data_fim_periodo = fim_periodo or self.data_fim_periodo
        self.proxima_cobranca = proxima_cobranca or self.proxima_cobranca
        self.grace_until = None
        self.save(update_fields=['status', 'data_inicio', 'data_fim_periodo', 'proxima_cobranca', 'grace_until', 'atualizado_em'])

    @property
    def valor_decimal(self):
        return Decimal(self.valor_contratado)


class Pagamento(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        APROVADO = 'APROVADO', 'Aprovado'
        RECUSADO = 'RECUSADO', 'Recusado'
        CANCELADO = 'CANCELADO', 'Cancelado'
        ESTORNADO = 'ESTORNADO', 'Estornado'
        EM_PROCESSAMENTO = 'EM_PROCESSAMENTO', 'Em processamento'

    assinatura = models.ForeignKey(Assinatura, on_delete=models.PROTECT, related_name='pagamentos')
    gateway = models.CharField(max_length=24, choices=Assinatura.Gateway.choices, default=Assinatura.Gateway.MERCADOPAGO)
    gateway_payment_id = models.CharField(max_length=120, blank=True, db_index=True)
    gateway_invoice_id = models.CharField(max_length=120, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    moeda = models.CharField(max_length=3, default='BRL')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)
    forma_pagamento = models.CharField(max_length=80, blank=True)
    parcelas = models.PositiveSmallIntegerField(blank=True, null=True)
    data_vencimento = models.DateTimeField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    failed_at = models.DateTimeField(blank=True, null=True)
    raw_status = models.CharField(max_length=80, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['assinatura', 'status']),
            models.Index(fields=['gateway', 'gateway_payment_id']),
        ]

    def __str__(self):
        return f'{self.assinatura_id} - {self.get_status_display()} - {self.valor}'


class EventoWebhook(models.Model):
    class StatusProcessamento(models.TextChoices):
        RECEBIDO = 'RECEBIDO', 'Recebido'
        PROCESSADO = 'PROCESSADO', 'Processado'
        IGNORADO = 'IGNORADO', 'Ignorado'
        ERRO = 'ERRO', 'Erro'

    gateway = models.CharField(max_length=24, choices=Assinatura.Gateway.choices, default=Assinatura.Gateway.MERCADOPAGO)
    event_id = models.CharField(max_length=160)
    event_type = models.CharField(max_length=120, blank=True)
    resource_id = models.CharField(max_length=160, blank=True)
    payload_hash = models.CharField(max_length=64)
    status_processamento = models.CharField(
        max_length=16,
        choices=StatusProcessamento.choices,
        default=StatusProcessamento.RECEBIDO,
    )
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-received_at']
        constraints = [
            models.UniqueConstraint(fields=['gateway', 'event_id'], name='unique_billing_webhook_event'),
        ]
        indexes = [
            models.Index(fields=['gateway', 'resource_id']),
            models.Index(fields=['status_processamento', 'received_at']),
        ]

    def __str__(self):
        return f'{self.gateway} - {self.event_type or "-"} - {self.event_id}'


class CheckoutIntent(models.Model):
    class Status(models.TextChoices):
        INICIADO = 'INICIADO', 'Iniciado'
        CHECKOUT_CRIADO = 'CHECKOUT_CRIADO', 'Checkout criado'
        AGUARDANDO_PAGAMENTO = 'AGUARDANDO_PAGAMENTO', 'Aguardando pagamento'
        PAGO = 'PAGO', 'Pago'
        CONVERTIDO = 'CONVERTIDO', 'Convertido'
        FALHOU = 'FALHOU', 'Falhou'
        CANCELADO = 'CANCELADO', 'Cancelado'
        EXPIRADO = 'EXPIRADO', 'Expirado'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    nome_empresa = models.CharField(max_length=160)
    nome_responsavel = models.CharField(max_length=160)
    email = models.EmailField()
    telefone = models.CharField(max_length=40)
    periodicidade = models.CharField(max_length=16, choices=Assinatura.Periodicidade.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.INICIADO, db_index=True)
    external_reference = models.CharField(max_length=80, unique=True, db_index=True)
    gateway_subscription_id = models.CharField(max_length=120, blank=True, db_index=True)
    gateway_checkout_url = models.URLField(max_length=700, blank=True)
    utm_source = models.CharField(max_length=120, blank=True)
    utm_medium = models.CharField(max_length=120, blank=True)
    utm_campaign = models.CharField(max_length=160, blank=True)
    utm_content = models.CharField(max_length=160, blank=True)
    utm_term = models.CharField(max_length=160, blank=True)
    gclid = models.CharField(max_length=200, blank=True)
    fbclid = models.CharField(max_length=200, blank=True)
    referrer = models.URLField(max_length=500, blank=True)
    consent_at = models.DateTimeField()
    converted_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    empresa = models.OneToOneField(
        'empresas.Empresa', on_delete=models.PROTECT, related_name='checkout_origem', blank=True, null=True,
    )
    assinatura = models.OneToOneField(
        Assinatura, on_delete=models.PROTECT, related_name='checkout_origem', blank=True, null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['periodicidade', '-created_at']),
            models.Index(fields=['utm_source', '-created_at']),
        ]

    def __str__(self):
        return f'{self.nome_empresa} - {self.get_status_display()}'
