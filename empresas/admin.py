from django.contrib import admin

from .models import Empresa, UsuarioEmpresa


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'slug', 'cnpj', 'cidade', 'estado', 'ativa', 'criado_em']
    list_filter = ['ativa']
    search_fields = ['nome', 'razao_social', 'nome_fantasia', 'cnpj', 'slug']
    readonly_fields = ['criado_em', 'atualizado_em']
    fieldsets = (
        ('Identificacao', {
            'fields': ('nome', 'razao_social', 'nome_fantasia', 'cnpj', 'slug', 'ativa'),
            'description': 'Evite alterar o slug de empresas em uso sem revisar vinculos, sessoes e integracoes.',
        }),
        ('Dados institucionais', {
            'fields': ('endereco', 'cidade', 'estado', 'cep', 'telefone', 'email'),
        }),
        ('Branding', {
            'fields': ('logo', 'cabecalho_documentos', 'rodape_documentos', 'texto_rodape', 'cor_primaria', 'cor_secundaria'),
        }),
        ('Responsavel tecnico', {
            'fields': ('responsavel_tecnico', 'crea_responsavel'),
        }),
        ('Auditoria', {
            'fields': ('criado_em', 'atualizado_em'),
        }),
    )


@admin.register(UsuarioEmpresa)
class UsuarioEmpresaAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'empresa', 'ativo', 'administrador_empresa', 'criado_em']
    list_filter = ['empresa', 'ativo', 'administrador_empresa']
    search_fields = ['usuario__username', 'usuario__first_name', 'usuario__last_name', 'usuario__email', 'empresa__nome']
    readonly_fields = ['criado_em']
    autocomplete_fields = ['usuario', 'empresa']
