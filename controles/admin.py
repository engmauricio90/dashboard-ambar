from django.contrib import admin

from .models import (
    ContratoConcretagem,
    EquipamentoLocadoCatalogo,
    FaturamentoConcretagem,
    LocacaoEquipamento,
    LocadoraEquipamento,
    OrcamentoRadarObra,
    RegistroAbastecimento,
    SolicitanteConcretagem,
    VeiculoMaquina,
)


@admin.register(VeiculoMaquina)
class VeiculoMaquinaAdmin(admin.ModelAdmin):
    list_display = ('placa', 'descricao', 'tipo', 'status')
    search_fields = ('placa', 'descricao')
    list_filter = ('tipo', 'status')


@admin.register(RegistroAbastecimento)
class RegistroAbastecimentoAdmin(admin.ModelAdmin):
    list_display = ('data_abastecimento', 'veiculo', 'posto', 'responsavel', 'valor_total')
    search_fields = ('veiculo__placa', 'veiculo__descricao', 'posto', 'responsavel')
    list_filter = ('data_abastecimento', 'posto')


@admin.register(EquipamentoLocadoCatalogo)
class EquipamentoLocadoCatalogoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'categoria', 'status')
    search_fields = ('nome', 'categoria')
    list_filter = ('status', 'categoria')


@admin.register(LocadoraEquipamento)
class LocadoraEquipamentoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'contato', 'telefone', 'email')
    search_fields = ('nome', 'contato', 'telefone', 'email')


@admin.register(LocacaoEquipamento)
class LocacaoEquipamentoAdmin(admin.ModelAdmin):
    list_display = (
        'data_locacao',
        'solicitante',
        'locadora',
        'status',
        'equipamento',
        'obra',
        'numero_contrato',
        'quantidade',
        'data_retirada',
        'prazo',
        'valor_referencia',
    )
    search_fields = (
        'equipamento__nome',
        'locadora__nome',
        'obra__nome_obra',
        'solicitante',
        'numero_contrato',
    )
    list_filter = ('status', 'data_locacao', 'locadora')


@admin.register(OrcamentoRadarObra)
class OrcamentoRadarObraAdmin(admin.ModelAdmin):
    list_display = ('numero', 'cliente', 'data_orcamento', 'situacao', 'valor_estimado', 'responsavel')
    search_fields = ('numero', 'cliente', 'descricao', 'responsavel')
    list_filter = ('situacao', 'data_orcamento')


class FaturamentoConcretagemInline(admin.TabularInline):
    model = FaturamentoConcretagem
    extra = 0


@admin.register(SolicitanteConcretagem)
class SolicitanteConcretagemAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ativo')
    search_fields = ('nome',)
    list_filter = ('ativo',)


@admin.register(ContratoConcretagem)
class ContratoConcretagemAdmin(admin.ModelAdmin):
    list_display = ('numero_contrato', 'obra', 'fornecedor', 'descricao', 'data_inicio', 'status', 'total_previsto', 'total_faturado')
    search_fields = ('numero_contrato', 'obra__nome_obra', 'fornecedor', 'descricao')
    list_filter = ('status', 'fornecedor')
    inlines = [FaturamentoConcretagemInline]


@admin.register(FaturamentoConcretagem)
class FaturamentoConcretagemAdmin(admin.ModelAdmin):
    list_display = (
        'data_faturamento',
        'contrato',
        'responsavel_display',
        'status',
        'volume_m3',
        'valor_previsto',
        'valor_cobrado',
        'diferenca',
    )
    search_fields = (
        'contrato__obra__nome_obra',
        'contrato__fornecedor',
        'numero_documento',
        'responsavel_solicitacao',
        'solicitante__nome',
    )
    list_filter = ('status', 'data_faturamento', 'contrato__fornecedor')
