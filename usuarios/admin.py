from django.contrib import admin

from .models import PerfilUsuario


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ['user', 'cargo', 'setor', 'telefone', 'updated_at']
    list_filter = ['setor']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'user__email', 'cargo', 'telefone']
    filter_horizontal = ['obras']
