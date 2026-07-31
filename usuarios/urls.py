from django.urls import path

from . import views


urlpatterns = [
    path('minha-area/', views.minha_area, name='minha_area'),
    path('minha-area/editar/', views.editar_meu_perfil, name='editar_meu_perfil'),
    path('', views.lista_usuarios, name='lista_usuarios'),
    path('novo/', views.novo_usuario, name='novo_usuario'),
    path('<int:user_id>/editar/', views.editar_usuario, name='editar_usuario'),
    path('<int:user_id>/status/', views.alternar_status_usuario, name='alternar_status_usuario'),
]
