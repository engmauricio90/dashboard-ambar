from django.contrib import admin

from .models import PublicLead


@admin.register(PublicLead)
class PublicLeadAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'nome', 'empresa', 'billing_preference', 'status', 'utm_source', 'utm_campaign')
    list_filter = ('billing_preference', 'status', 'utm_source', 'utm_campaign', 'created_at')
    search_fields = ('nome', 'empresa', 'email', 'telefone')
    readonly_fields = ('created_at', 'updated_at', 'consent_at', 'telefone_normalizado')
