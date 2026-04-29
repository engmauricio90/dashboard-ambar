from django.contrib import admin

from .models import CentroCusto, ContaPagar, ContaReceber


@admin.register(CentroCusto)
class CentroCustoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ativo')
    search_fields = ('nome',)
    list_filter = ('ativo',)


@admin.register(ContaReceber)
class ContaReceberAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'obra', 'numero_nf', 'data_vencimento', 'valor_bruto', 'valor_liquido', 'status')
    search_fields = ('cliente', 'descricao', 'numero_nf', 'obra__nome_obra')
    list_filter = ('status', 'data_vencimento', 'centro_custo')


@admin.register(ContaPagar)
class ContaPagarAdmin(admin.ModelAdmin):
    list_display = ('fornecedor', 'obra', 'centro_custo', 'data_vencimento', 'valor', 'status')
    search_fields = ('fornecedor', 'descricao', 'obra__nome_obra')
    list_filter = ('status', 'data_vencimento', 'centro_custo', 'categoria')
