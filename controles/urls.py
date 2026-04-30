from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='controles_home'),
    path('abastecimentos/', views.lista_abastecimentos, name='lista_abastecimentos'),
    path('abastecimentos/novo/', views.novo_abastecimento, name='novo_abastecimento'),
    path('ordens-compra/', views.lista_ordens_compra_gerais, name='lista_ordens_compra_gerais'),
    path('ordens-compra/nova/', views.nova_ordem_compra_geral, name='nova_ordem_compra_geral'),
    path(
        'ordens-compra/<int:ordem_id>/',
        views.detalhe_ordem_compra_geral,
        name='detalhe_ordem_compra_geral',
    ),
    path(
        'ordens-compra/<int:ordem_id>/editar/',
        views.editar_ordem_compra_geral,
        name='editar_ordem_compra_geral',
    ),
    path(
        'ordens-compra/<int:ordem_id>/pdf/',
        views.ordem_compra_geral_pdf,
        name='ordem_compra_geral_pdf',
    ),
    path('combustivel/ordens/', views.lista_ordens_combustivel, name='lista_ordens_combustivel'),
    path('combustivel/ordens/nova/', views.nova_ordem_combustivel, name='nova_ordem_combustivel'),
    path(
        'combustivel/ordens/<int:ordem_id>/',
        views.detalhe_ordem_combustivel,
        name='detalhe_ordem_combustivel',
    ),
    path(
        'combustivel/ordens/<int:ordem_id>/pdf/',
        views.ordem_combustivel_pdf,
        name='ordem_combustivel_pdf',
    ),
    path(
        'combustivel/ordens/<int:ordem_id>/editar/',
        views.editar_ordem_combustivel,
        name='editar_ordem_combustivel',
    ),
    path(
        'combustivel/ordens/<int:ordem_id>/notas/nova/',
        views.nova_nf_combustivel,
        name='nova_nf_combustivel',
    ),
    path(
        'combustivel/notas/<int:nota_id>/editar/',
        views.editar_nf_combustivel,
        name='editar_nf_combustivel',
    ),
    path('combustivel/bombonas/', views.lista_bombonas_combustivel, name='lista_bombonas_combustivel'),
    path('combustivel/bombonas/nova/', views.nova_bombona_combustivel, name='nova_bombona_combustivel'),
    path(
        'combustivel/bombonas/<int:bombona_id>/editar/',
        views.editar_bombona_combustivel,
        name='editar_bombona_combustivel',
    ),
    path('veiculos/', views.lista_veiculos, name='lista_veiculos'),
    path('veiculos/novo/', views.novo_veiculo, name='novo_veiculo'),
    path('veiculos/<int:veiculo_id>/editar/', views.editar_veiculo, name='editar_veiculo'),
    path('maquinas-locadas/', views.lista_ordens_locacao_maquinas, name='lista_ordens_locacao_maquinas'),
    path('maquinas-locadas/nova/', views.nova_ordem_locacao_maquina, name='nova_ordem_locacao_maquina'),
    path(
        'maquinas-locadas/<int:ordem_id>/',
        views.detalhe_ordem_locacao_maquina,
        name='detalhe_ordem_locacao_maquina',
    ),
    path(
        'maquinas-locadas/<int:ordem_id>/pdf/',
        views.ordem_locacao_maquina_pdf,
        name='ordem_locacao_maquina_pdf',
    ),
    path(
        'maquinas-locadas/<int:ordem_id>/editar/',
        views.editar_ordem_locacao_maquina,
        name='editar_ordem_locacao_maquina',
    ),
    path(
        'maquinas-locadas/<int:ordem_id>/apontamentos/novo/',
        views.novo_apontamento_maquina,
        name='novo_apontamento_maquina',
    ),
    path(
        'maquinas-locadas/apontamentos/<int:apontamento_id>/editar/',
        views.editar_apontamento_maquina,
        name='editar_apontamento_maquina',
    ),
    path(
        'maquinas-locadas/<int:ordem_id>/notas/nova/',
        views.nova_nf_locacao_maquina,
        name='nova_nf_locacao_maquina',
    ),
    path(
        'maquinas-locadas/notas/<int:nota_id>/editar/',
        views.editar_nf_locacao_maquina,
        name='editar_nf_locacao_maquina',
    ),
    path('maquinas-locadas/catalogo/', views.lista_catalogo_maquinas_locacao, name='lista_catalogo_maquinas_locacao'),
    path('maquinas-locadas/catalogo/nova/', views.nova_maquina_locacao, name='nova_maquina_locacao'),
    path(
        'maquinas-locadas/catalogo/<int:maquina_id>/editar/',
        views.editar_maquina_locacao,
        name='editar_maquina_locacao',
    ),
    path('maquinas-locadas/fornecedores/', views.lista_fornecedores_maquinas, name='lista_fornecedores_maquinas'),
    path('maquinas-locadas/fornecedores/novo/', views.novo_fornecedor_maquina, name='novo_fornecedor_maquina'),
    path(
        'maquinas-locadas/fornecedores/<int:fornecedor_id>/editar/',
        views.editar_fornecedor_maquina,
        name='editar_fornecedor_maquina',
    ),
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
