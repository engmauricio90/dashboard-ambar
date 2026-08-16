from django.urls import path

from . import views


urlpatterns = [
    path('selecionar/', views.selecionar_empresa, name='selecionar_empresa'),
    path('selecionar/<int:empresa_id>/', views.trocar_empresa, name='trocar_empresa'),
    path('identidade/', views.identidade_visual, name='identidade_visual_empresa'),
]
