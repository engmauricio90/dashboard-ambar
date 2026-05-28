from django.contrib import admin

from .models import (
    ChecklistDiario,
    DiarioObra,
    EfetivoDiario,
    EquipamentoDiario,
    FotoDiario,
    FrenteServicoDiario,
    HistoricoDiario,
    MaterialDiario,
    OcorrenciaDiario,
)


class FrenteServicoInline(admin.TabularInline):
    model = FrenteServicoDiario
    extra = 0


class EfetivoInline(admin.TabularInline):
    model = EfetivoDiario
    extra = 0


class EquipamentoInline(admin.TabularInline):
    model = EquipamentoDiario
    extra = 0


class MaterialInline(admin.TabularInline):
    model = MaterialDiario
    extra = 0


class OcorrenciaInline(admin.TabularInline):
    model = OcorrenciaDiario
    extra = 0


class ChecklistInline(admin.TabularInline):
    model = ChecklistDiario
    extra = 0


class FotoInline(admin.TabularInline):
    model = FotoDiario
    extra = 0
    readonly_fields = ['uploaded_at']


class HistoricoInline(admin.TabularInline):
    model = HistoricoDiario
    extra = 0
    readonly_fields = ['usuario', 'acao', 'descricao', 'created_at']
    can_delete = False


@admin.register(DiarioObra)
class DiarioObraAdmin(admin.ModelAdmin):
    list_display = ['obra', 'data', 'responsavel_preenchimento', 'situacao_obra', 'condicao_climatica', 'status']
    list_filter = ['status', 'condicao_climatica', 'situacao_obra', 'data']
    search_fields = ['obra__nome_obra', 'responsavel_preenchimento', 'responsavel_tecnico']
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']
    inlines = [
        FrenteServicoInline,
        EfetivoInline,
        EquipamentoInline,
        MaterialInline,
        OcorrenciaInline,
        ChecklistInline,
        FotoInline,
        HistoricoInline,
    ]


admin.site.register(FrenteServicoDiario)
admin.site.register(EfetivoDiario)
admin.site.register(EquipamentoDiario)
admin.site.register(MaterialDiario)
admin.site.register(OcorrenciaDiario)
admin.site.register(ChecklistDiario)
admin.site.register(FotoDiario)
admin.site.register(HistoricoDiario)
