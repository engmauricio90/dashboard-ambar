from django.contrib import admin

from .models import (
    ApontamentoMaquinaLocacao,
    BombonaCombustivel,
    ContratoConcretagem,
    EquipamentoLocadoCatalogo,
    FornecedorMaquinaLocacao,
    FaturamentoConcretagem,
    FaturamentoDireto,
    HistoricoLocacaoMaquina,
    LocacaoEquipamento,
    LocadoraEquipamento,
    HistoricoOrdemCombustivel,
    MaquinaLocacaoCatalogo,
    NotaFiscalCombustivel,
    NotaFiscalLocacaoMaquina,
    NotaFiscalOrdemCompraGeral,
    OrcamentoRadarObra,
    OrdemCompraCombustivel,
    OrdemCompraGeral,
    ItemOrdemCompraGeral,
    OrdemServicoLocacaoMaquina,
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


@admin.register(BombonaCombustivel)
class BombonaCombustivelAdmin(admin.ModelAdmin):
    list_display = ('identificacao', 'capacidade_litros', 'localizacao', 'status')
    search_fields = ('identificacao', 'localizacao')
    list_filter = ('status',)


class NotaFiscalCombustivelInline(admin.TabularInline):
    model = NotaFiscalCombustivel
    extra = 0


class HistoricoOrdemCombustivelInline(admin.TabularInline):
    model = HistoricoOrdemCombustivel
    extra = 0
    readonly_fields = ('data_hora', 'evento', 'descricao', 'status_anterior', 'status_novo')
    can_delete = False


@admin.register(OrdemCompraCombustivel)
class OrdemCompraCombustivelAdmin(admin.ModelAdmin):
    list_display = (
        'numero',
        'data_ordem',
        'fornecedor',
        'tipo_destino',
        'destino_display',
        'tipo_combustivel',
        'quantidade_litros',
        'valor_total_previsto',
        'status',
    )
    search_fields = (
        'numero',
        'fornecedor',
        'solicitante',
        'veiculo__placa',
        'veiculo__descricao',
        'bombona__identificacao',
    )
    list_filter = ('status', 'tipo_destino', 'tipo_combustivel', 'data_ordem')
    inlines = [NotaFiscalCombustivelInline, HistoricoOrdemCombustivelInline]


@admin.register(NotaFiscalCombustivel)
class NotaFiscalCombustivelAdmin(admin.ModelAdmin):
    list_display = ('numero', 'ordem', 'data_emissao', 'litros', 'valor_total', 'status')
    search_fields = ('numero', 'ordem__numero', 'ordem__fornecedor')
    list_filter = ('status', 'data_emissao')


@admin.register(HistoricoOrdemCombustivel)
class HistoricoOrdemCombustivelAdmin(admin.ModelAdmin):
    list_display = ('ordem', 'data_hora', 'evento', 'status_anterior', 'status_novo')
    search_fields = ('ordem__numero', 'evento', 'descricao')
    list_filter = ('evento', 'data_hora')


class ItemOrdemCompraGeralInline(admin.TabularInline):
    model = ItemOrdemCompraGeral
    extra = 0


class NotaFiscalOrdemCompraGeralInline(admin.TabularInline):
    model = NotaFiscalOrdemCompraGeral
    extra = 0


@admin.register(OrdemCompraGeral)
class OrdemCompraGeralAdmin(admin.ModelAdmin):
    list_display = ('numero', 'data_emissao', 'fornecedor', 'comprador', 'total', 'total_faturado', 'status')
    search_fields = ('numero', 'fornecedor', 'comprador', 'fornecedor_cpf_cnpj')
    list_filter = ('status', 'data_emissao')
    inlines = [ItemOrdemCompraGeralInline, NotaFiscalOrdemCompraGeralInline]


@admin.register(NotaFiscalOrdemCompraGeral)
class NotaFiscalOrdemCompraGeralAdmin(admin.ModelAdmin):
    list_display = ('numero', 'ordem', 'item', 'data_emissao', 'quantidade', 'valor_total', 'status')
    search_fields = ('numero', 'ordem__numero', 'ordem__fornecedor', 'item__descricao')
    list_filter = ('status', 'data_emissao')


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


@admin.register(MaquinaLocacaoCatalogo)
class MaquinaLocacaoCatalogoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'categoria', 'status')
    search_fields = ('nome', 'categoria')
    list_filter = ('status', 'categoria')


@admin.register(FornecedorMaquinaLocacao)
class FornecedorMaquinaLocacaoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'contato', 'telefone', 'email')
    search_fields = ('nome', 'contato', 'telefone', 'email')


class ApontamentoMaquinaLocacaoInline(admin.TabularInline):
    model = ApontamentoMaquinaLocacao
    extra = 0


class NotaFiscalLocacaoMaquinaInline(admin.TabularInline):
    model = NotaFiscalLocacaoMaquina
    extra = 0


class HistoricoLocacaoMaquinaInline(admin.TabularInline):
    model = HistoricoLocacaoMaquina
    extra = 0
    readonly_fields = ('data_hora', 'evento', 'descricao', 'status_anterior', 'status_novo')
    can_delete = False


@admin.register(OrdemServicoLocacaoMaquina)
class OrdemServicoLocacaoMaquinaAdmin(admin.ModelAdmin):
    list_display = (
        'numero',
        'data_solicitacao',
        'obra',
        'fornecedor',
        'maquina',
        'tipo_cobranca',
        'status',
        'total_horas_apontadas',
        'total_faturado',
    )
    search_fields = (
        'numero',
        'obra__nome_obra',
        'fornecedor__nome',
        'maquina__nome',
        'solicitante',
        'responsavel',
    )
    list_filter = ('status', 'tipo_cobranca', 'fornecedor', 'maquina', 'data_solicitacao')
    inlines = [ApontamentoMaquinaLocacaoInline, NotaFiscalLocacaoMaquinaInline, HistoricoLocacaoMaquinaInline]


@admin.register(ApontamentoMaquinaLocacao)
class ApontamentoMaquinaLocacaoAdmin(admin.ModelAdmin):
    list_display = ('ordem', 'data', 'horas_trabalhadas', 'horas_paradas', 'operador')
    search_fields = ('ordem__numero', 'operador', 'responsavel_apontamento', 'motivo_parada')
    list_filter = ('data',)


@admin.register(NotaFiscalLocacaoMaquina)
class NotaFiscalLocacaoMaquinaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'ordem', 'data_emissao', 'horas_faturadas', 'valor_total', 'status')
    search_fields = ('numero', 'ordem__numero', 'ordem__fornecedor__nome')
    list_filter = ('status', 'data_emissao')


@admin.register(HistoricoLocacaoMaquina)
class HistoricoLocacaoMaquinaAdmin(admin.ModelAdmin):
    list_display = ('ordem', 'data_hora', 'evento', 'status_anterior', 'status_novo')
    search_fields = ('ordem__numero', 'evento', 'descricao')
    list_filter = ('evento', 'data_hora')


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


@admin.register(FaturamentoDireto)
class FaturamentoDiretoAdmin(admin.ModelAdmin):
    list_display = ('obra', 'numero_nf', 'empresa_comprou', 'valor_nota', 'vencimento_boleto', 'medicao_desconto')
    search_fields = ('obra__nome_obra', 'numero_nf', 'empresa_comprou', 'descricao', 'medicao_desconto')
    list_filter = ('vencimento_boleto', 'obra')
