from django.contrib import admin

from .models import Assinatura, CheckoutIntent, EventoWebhook, Pagamento


@admin.register(Assinatura)
class AssinaturaAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'periodicidade', 'valor_contratado', 'status', 'gateway', 'proxima_cobranca', 'cancel_at_period_end')
    list_filter = ('status', 'periodicidade', 'gateway', 'cancel_at_period_end')
    search_fields = ('empresa__nome', 'empresa__razao_social', 'gateway_subscription_id')
    readonly_fields = ('criado_em', 'atualizado_em')


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ('assinatura', 'valor', 'status', 'gateway', 'gateway_payment_id', 'paid_at', 'failed_at')
    list_filter = ('status', 'gateway', 'forma_pagamento')
    search_fields = ('assinatura__empresa__nome', 'gateway_payment_id', 'gateway_invoice_id')
    readonly_fields = ('criado_em', 'atualizado_em')


@admin.register(EventoWebhook)
class EventoWebhookAdmin(admin.ModelAdmin):
    list_display = ('gateway', 'event_type', 'resource_id', 'status_processamento', 'received_at', 'processed_at')
    list_filter = ('gateway', 'status_processamento', 'event_type')
    search_fields = ('event_id', 'resource_id', 'payload_hash')
    readonly_fields = ('received_at', 'processed_at')


@admin.register(CheckoutIntent)
class CheckoutIntentAdmin(admin.ModelAdmin):
    list_display = ('nome_empresa', 'email', 'periodicidade', 'status', 'empresa', 'created_at')
    list_filter = ('status', 'periodicidade', 'utm_source')
    search_fields = ('nome_empresa', 'nome_responsavel', 'email', 'external_reference', 'gateway_subscription_id')
    readonly_fields = ('public_id', 'external_reference', 'consent_at', 'converted_at', 'created_at', 'updated_at')
