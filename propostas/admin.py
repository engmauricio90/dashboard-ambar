from django.contrib import admin

from .models import Proposta, PropostaPlanilhaItem, PropostaResumoItem


class PropostaResumoItemInline(admin.TabularInline):
    model = PropostaResumoItem
    extra = 0


class PropostaPlanilhaItemInline(admin.TabularInline):
    model = PropostaPlanilhaItem
    extra = 0


@admin.register(Proposta)
class PropostaAdmin(admin.ModelAdmin):
    list_display = ('numero_formatado', 'empresa', 'cliente', 'tipo_execucao', 'data_proposta', 'situacao', 'total_final')
    search_fields = ('cliente', 'tipo_execucao', 'engenheiro_nome', 'empresa__nome')
    list_filter = ('empresa', 'situacao', 'ano', 'data_proposta')
    inlines = [PropostaResumoItemInline, PropostaPlanilhaItemInline]
