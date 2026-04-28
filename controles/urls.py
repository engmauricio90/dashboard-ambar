from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='controles_home'),
    path('abastecimentos/', views.lista_abastecimentos, name='lista_abastecimentos'),
    path('abastecimentos/novo/', views.novo_abastecimento, name='novo_abastecimento'),
    path('veiculos/', views.lista_veiculos, name='lista_veiculos'),
    path('veiculos/novo/', views.novo_veiculo, name='novo_veiculo'),
    path('veiculos/<int:veiculo_id>/editar/', views.editar_veiculo, name='editar_veiculo'),
    path('equipamentos-locados/', views.lista_equipamentos_locados, name='lista_equipamentos_locados'),
    path(
        'equipamentos-locados/relatorio.pdf/',
        views.relatorio_locacoes_equipamentos_pdf,
        name='relatorio_locacoes_equipamentos_pdf',
    ),
    path('equipamentos-locados/nova/', views.nova_locacao_equipamento, name='nova_locacao_equipamento'),
    path(
        'equipamentos-locados/<int:locacao_id>/editar/',
        views.editar_locacao_equipamento,
        name='editar_locacao_equipamento',
    ),
    path(
        'equipamentos-locados/<int:locacao_id>/solicitar-retirada/',
        views.solicitar_retirada_equipamento,
        name='solicitar_retirada_equipamento',
    ),
    path(
        'equipamentos-locados/<int:locacao_id>/baixar/',
        views.baixar_locacao_equipamento,
        name='baixar_locacao_equipamento',
    ),
    path('catalogo-equipamentos/', views.lista_catalogo_equipamentos, name='lista_catalogo_equipamentos'),
    path('catalogo-equipamentos/novo/', views.novo_catalogo_equipamento, name='novo_catalogo_equipamento'),
    path('locadoras/', views.lista_locadoras, name='lista_locadoras'),
    path('locadoras/nova/', views.nova_locadora, name='nova_locadora'),
    path('radar-obras/', views.lista_radar_obras, name='lista_radar_obras'),
    path('radar-obras/novo/', views.novo_radar_obra, name='novo_radar_obra'),
    path('radar-obras/<int:orcamento_id>/editar/', views.editar_radar_obra, name='editar_radar_obra'),
    path('concretagens/', views.lista_concretagens, name='lista_concretagens'),
    path(
        'concretagens/solicitantes/',
        views.lista_solicitantes_concretagem,
        name='lista_solicitantes_concretagem',
    ),
    path(
        'concretagens/solicitantes/novo/',
        views.novo_solicitante_concretagem,
        name='novo_solicitante_concretagem',
    ),
    path(
        'concretagens/solicitantes/<int:solicitante_id>/editar/',
        views.editar_solicitante_concretagem,
        name='editar_solicitante_concretagem',
    ),
    path('concretagens/novo/', views.novo_contrato_concretagem, name='novo_contrato_concretagem'),
    path(
        'concretagens/<int:contrato_id>/',
        views.detalhe_contrato_concretagem,
        name='detalhe_contrato_concretagem',
    ),
    path(
        'concretagens/<int:contrato_id>/editar/',
        views.editar_contrato_concretagem,
        name='editar_contrato_concretagem',
    ),
    path(
        'concretagens/<int:contrato_id>/faturamentos/novo/',
        views.novo_faturamento_concretagem,
        name='novo_faturamento_concretagem',
    ),
    path(
        'concretagens/faturamentos/<int:faturamento_id>/editar/',
        views.editar_faturamento_concretagem,
        name='editar_faturamento_concretagem',
    ),
]
