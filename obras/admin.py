from django.contrib import admin

from .models import (
    AditivoContrato,
    DespesaObra,
    ImpostoNotaFiscal,
    NotaFiscal,
    Obra,
    RetencaoTecnicaObra,
    RetencaoNotaFiscal,
)


class AditivoContratoInline(admin.TabularInline):
    model = AditivoContrato
    extra = 0


class DespesaObraInline(admin.TabularInline):
    model = DespesaObra
    extra = 0


class RetencaoTecnicaObraInline(admin.TabularInline):
    model = RetencaoTecnicaObra
    extra = 0


@admin.register(Obra)
class ObraAdmin(admin.ModelAdmin):
    list_display = (
        'nome_obra',
        'cliente',
        'status_obra',
        'valor_contrato',
        'total_aditivos',
        'total_supressoes',
        'total_notas_fiscais',
        'resultado_real',
    )
    search_fields = ('nome_obra', 'cliente', 'responsavel')
    list_filter = ('status_obra',)
    inlines = [AditivoContratoInline, DespesaObraInline, RetencaoTecnicaObraInline]


class RetencaoNotaFiscalInline(admin.TabularInline):
    model = RetencaoNotaFiscal
    extra = 0


class ImpostoNotaFiscalInline(admin.TabularInline):
    model = ImpostoNotaFiscal
    extra = 0


@admin.register(NotaFiscal)
class NotaFiscalAdmin(admin.ModelAdmin):
    list_display = (
        'numero',
        'obra',
        'data_emissao',
        'status',
        'valor_bruto',
        'valor_liquido',
    )
    search_fields = ('numero', 'obra__nome_obra', 'obra__cliente')
    list_filter = ('status', 'data_emissao')
    inlines = [RetencaoNotaFiscalInline, ImpostoNotaFiscalInline]


@admin.register(AditivoContrato)
class AditivoContratoAdmin(admin.ModelAdmin):
    list_display = ('obra', 'data_referencia', 'tipo', 'descricao', 'valor')
    search_fields = ('obra__nome_obra', 'descricao')
    list_filter = ('tipo', 'data_referencia')


@admin.register(DespesaObra)
class DespesaObraAdmin(admin.ModelAdmin):
    list_display = ('obra', 'data_referencia', 'categoria', 'descricao', 'valor')
    search_fields = ('obra__nome_obra', 'descricao')
    list_filter = ('categoria', 'data_referencia')


@admin.register(RetencaoTecnicaObra)
class RetencaoTecnicaObraAdmin(admin.ModelAdmin):
    list_display = ('obra', 'data_referencia', 'descricao', 'valor')
    search_fields = ('obra__nome_obra', 'descricao')
    list_filter = ('data_referencia',)
