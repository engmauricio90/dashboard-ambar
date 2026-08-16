from django.urls import path

from empresas.decorators import empresa_required

from . import views


urlpatterns = [
    path('', empresa_required(views.lista_propostas), name='lista_propostas'),
    path('nova/', empresa_required(views.nova_proposta), name='nova_proposta'),
    path('<int:proposta_id>/editar/', empresa_required(views.editar_proposta), name='editar_proposta'),
    path('<int:proposta_id>/visualizar/', empresa_required(views.visualizar_proposta), name='visualizar_proposta'),
]
