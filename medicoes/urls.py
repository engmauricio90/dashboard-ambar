from django.urls import path

from . import views


urlpatterns = [
    path('', views.medicoes_home, name='medicoes_home'),
    path('orcamentos/', views.lista_orcamentos, name='lista_orcamentos_medicao'),
    path('orcamentos/importar/', views.importar_orcamento, name='importar_orcamento_medicao'),
    path('orcamentos/<int:orcamento_id>/', views.detalhe_orcamento, name='detalhe_orcamento_medicao'),
    path(
        'orcamentos/<int:orcamento_id>/construtora/nova/',
        views.nova_medicao_construtora,
        name='nova_medicao_construtora',
    ),
    path('construtora/<int:medicao_id>/editar/', views.editar_medicao_construtora, name='editar_medicao_construtora'),
    path('construtora/<int:medicao_id>/excluir/', views.excluir_medicao_construtora, name='excluir_medicao_construtora'),
    path('construtora/<int:medicao_id>/pdf/', views.medicao_construtora_pdf, name='medicao_construtora_pdf'),
    path('construtora/<int:medicao_id>/excel/', views.medicao_construtora_excel, name='medicao_construtora_excel'),
    path('empreiteiros/simples/nova/', views.nova_medicao_empreiteiro_simples, name='nova_medicao_empreiteiro_simples'),
    path(
        'orcamentos/<int:orcamento_id>/empreiteiro/cumulativa/nova/',
        views.nova_medicao_empreiteiro_cumulativa,
        name='nova_medicao_empreiteiro_cumulativa',
    ),
    path('empreiteiros/<int:medicao_id>/editar/', views.editar_medicao_empreiteiro, name='editar_medicao_empreiteiro'),
    path('empreiteiros/<int:medicao_id>/excluir/', views.excluir_medicao_empreiteiro, name='excluir_medicao_empreiteiro'),
    path('empreiteiros/<int:medicao_id>/pdf/', views.medicao_empreiteiro_pdf, name='medicao_empreiteiro_pdf'),
    path('empreiteiros/<int:medicao_id>/excel/', views.medicao_empreiteiro_excel, name='medicao_empreiteiro_excel'),
]
