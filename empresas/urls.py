from django.urls import path

from . import views


urlpatterns = [
    path('selecionar/', views.selecionar_empresa, name='selecionar_empresa'),
    path('selecionar/<int:empresa_id>/', views.trocar_empresa, name='trocar_empresa'),
    path('identidade/', views.identidade_visual, name='identidade_visual_empresa'),
    path('usuarios/', views.usuarios_empresa, name='usuarios_empresa'),
    path('usuarios/novo/', views.novo_usuario_empresa, name='novo_usuario_empresa'),
    path('usuarios/<int:vinculo_id>/editar/', views.editar_usuario_empresa, name='editar_usuario_empresa'),
    path('usuarios/<int:vinculo_id>/status/', views.alternar_status_usuario_empresa, name='alternar_status_usuario_empresa'),
]
