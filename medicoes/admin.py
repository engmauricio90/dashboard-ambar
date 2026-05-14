from django.contrib import admin

from .models import (
    FaturamentoDiretoMedicao,
    ItemMedicaoConstrutora,
    ItemMedicaoEmpreiteiro,
    ItemOrcamentoMedicao,
    MedicaoConstrutora,
    MedicaoEmpreiteiro,
    OrcamentoMedicao,
)


class ItemOrcamentoMedicaoInline(admin.TabularInline):
    model = ItemOrcamentoMedicao
    extra = 0


@admin.register(OrcamentoMedicao)
class OrcamentoMedicaoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'obra', 'tipo', 'created_at']
    list_filter = ['tipo', 'obra']
    search_fields = ['nome', 'obra__nome_obra']
    inlines = [ItemOrcamentoMedicaoInline]


class ItemMedicaoConstrutoraInline(admin.TabularInline):
    model = ItemMedicaoConstrutora
    extra = 0


class FaturamentoDiretoMedicaoInline(admin.TabularInline):
    model = FaturamentoDiretoMedicao
    extra = 0


@admin.register(MedicaoConstrutora)
class MedicaoConstrutoraAdmin(admin.ModelAdmin):
    list_display = ['numero', 'orcamento', 'periodo_inicio', 'periodo_fim', 'total_liquido']
    list_filter = ['orcamento__obra']
    inlines = [ItemMedicaoConstrutoraInline, FaturamentoDiretoMedicaoInline]


class ItemMedicaoEmpreiteiroInline(admin.TabularInline):
    model = ItemMedicaoEmpreiteiro
    extra = 0


@admin.register(MedicaoEmpreiteiro)
class MedicaoEmpreiteiroAdmin(admin.ModelAdmin):
    list_display = ['numero', 'tipo', 'empreiteiro', 'obra', 'periodo_inicio', 'periodo_fim', 'total_liquido']
    list_filter = ['tipo', 'obra']
    search_fields = ['empreiteiro', 'cpf_cnpj']
    inlines = [ItemMedicaoEmpreiteiroInline]
