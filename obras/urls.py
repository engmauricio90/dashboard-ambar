from django.urls import path

from . import views

urlpatterns = [
    path('', views.lista_obras, name='lista_obras'),
    path('nova/', views.nova_obra, name='nova_obra'),
    path('<int:obra_id>/', views.detalhe_obra, name='detalhe_obra'),
    path('<int:obra_id>/relatorio/', views.relatorio_obra, name='relatorio_obra'),
    path('<int:obra_id>/notas/', views.lista_notas_obra, name='lista_notas_obra'),
    path('<int:obra_id>/despesas/', views.lista_despesas_obra, name='lista_despesas_obra'),
    path(
        '<int:obra_id>/faturamentos-diretos/',
        views.lista_faturamentos_diretos_obra,
        name='lista_faturamentos_diretos_obra',
    ),
    path('<int:obra_id>/aditivos/', views.lista_aditivos_obra, name='lista_aditivos_obra'),
    path(
        '<int:obra_id>/retencoes-tecnicas/',
        views.lista_retencoes_tecnicas_obra,
        name='lista_retencoes_tecnicas_obra',
    ),
    path('<int:obra_id>/editar/', views.editar_obra, name='editar_obra'),
    path('<int:obra_id>/excluir/', views.excluir_obra, name='excluir_obra'),
    path('<int:obra_id>/financeiro/', views.historico_financeiro, name='historico_financeiro'),
    path('<int:obra_id>/notas/nova/', views.nova_nota_fiscal, name='nova_nota_fiscal'),
    path(
        '<int:obra_id>/notas/<int:nota_id>/editar/',
        views.editar_nota_fiscal,
        name='editar_nota_fiscal',
    ),
    path(
        '<int:obra_id>/notas/<int:nota_id>/',
        views.detalhe_nota_fiscal,
        name='detalhe_nota_fiscal',
    ),
    path(
        '<int:obra_id>/notas/<int:nota_id>/excluir/',
        views.excluir_nota_fiscal,
        name='excluir_nota_fiscal',
    ),
    path(
        '<int:obra_id>/notas/<int:nota_id>/retencoes/<int:retencao_id>/excluir/',
        views.excluir_retencao,
        name='excluir_retencao',
    ),
    path(
        '<int:obra_id>/notas/<int:nota_id>/impostos/<int:imposto_id>/excluir/',
        views.excluir_imposto,
        name='excluir_imposto',
    ),
    path('<int:obra_id>/despesas/nova/', views.nova_despesa, name='nova_despesa'),
    path(
        '<int:obra_id>/retencoes-tecnicas/nova/',
        views.nova_retencao_tecnica,
        name='nova_retencao_tecnica',
    ),
    path(
        '<int:obra_id>/retencoes-tecnicas/<int:retencao_id>/devolver/',
        views.devolver_retencao_tecnica,
        name='devolver_retencao_tecnica',
    ),
    path(
        '<int:obra_id>/despesas/<int:despesa_id>/excluir/',
        views.excluir_despesa,
        name='excluir_despesa',
    ),
    path(
        '<int:obra_id>/retencoes-tecnicas/<int:retencao_id>/excluir/',
        views.excluir_retencao_tecnica,
        name='excluir_retencao_tecnica',
    ),
    path('<int:obra_id>/aditivos/novo/', views.novo_aditivo, name='novo_aditivo'),
    path(
        '<int:obra_id>/aditivos/<int:aditivo_id>/excluir/',
        views.excluir_aditivo,
        name='excluir_aditivo',
    ),
]
