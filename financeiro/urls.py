from django.urls import path

from . import views


urlpatterns = [
    path('', views.financeiro_home, name='financeiro_home'),
    path('receber/', views.lista_contas_receber, name='lista_contas_receber'),
    path('receber/nova/', views.nova_conta_receber, name='nova_conta_receber'),
    path('receber/<int:conta_id>/editar/', views.editar_conta_receber, name='editar_conta_receber'),
    path('receber/<int:conta_id>/baixar/', views.baixar_conta_receber, name='baixar_conta_receber'),
    path('pagar/', views.lista_contas_pagar, name='lista_contas_pagar'),
    path('pagar/nova/', views.nova_conta_pagar, name='nova_conta_pagar'),
    path('pagar/<int:conta_id>/editar/', views.editar_conta_pagar, name='editar_conta_pagar'),
    path('pagar/<int:conta_id>/baixar/', views.baixar_conta_pagar, name='baixar_conta_pagar'),
    path('centros-custo/', views.lista_centros_custo, name='lista_centros_custo'),
    path('centros-custo/novo/', views.novo_centro_custo, name='novo_centro_custo'),
    path('centros-custo/<int:centro_id>/editar/', views.editar_centro_custo, name='editar_centro_custo'),
    path('relatorio/', views.relatorio_financeiro, name='relatorio_financeiro'),
    path('relatorio.pdf/', views.relatorio_financeiro_pdf, name='relatorio_financeiro_pdf'),
]
