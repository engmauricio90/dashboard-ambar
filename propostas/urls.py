from django.urls import path

from . import views


urlpatterns = [
    path('', views.lista_propostas, name='lista_propostas'),
    path('nova/', views.nova_proposta, name='nova_proposta'),
    path('<int:proposta_id>/editar/', views.editar_proposta, name='editar_proposta'),
    path('<int:proposta_id>/visualizar/', views.visualizar_proposta, name='visualizar_proposta'),
]
