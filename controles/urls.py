from django.urls import path

from empresas.decorators import empresa_required

from . import views


urlpatterns = [
    path('', empresa_required(views.home), name='controles_home'),
    path('cronogramas/', empresa_required(views.lista_cronogramas_obras), name='lista_cronogramas_obras'),
    path('cronogramas/novo/', empresa_required(views.novo_cronograma_obra), name='novo_cronograma_obra'),
    path('cronogramas/<int:cronograma_id>/editar/', empresa_required(views.editar_cronograma_obra), name='editar_cronograma_obra'),
    path('cronogramas/<int:cronograma_id>/pdf/', empresa_required(views.cronograma_obra_pdf), name='cronograma_obra_pdf'),
    path('faturamentos-diretos/', empresa_required(views.lista_faturamentos_diretos), name='lista_faturamentos_diretos'),
    path('faturamentos-diretos/novo/', empresa_required(views.novo_faturamento_direto), name='novo_faturamento_direto'),
    path(
        'faturamentos-diretos/<int:faturamento_id>/editar/',
        empresa_required(views.editar_faturamento_direto),
        name='editar_faturamento_direto',
    ),
    path(
        'faturamentos-diretos/<int:faturamento_id>/excluir/',
        empresa_required(views.excluir_faturamento_direto),
        name='excluir_faturamento_direto',
    ),
    path('abastecimentos/', empresa_required(views.lista_abastecimentos), name='lista_abastecimentos'),
    path('abastecimentos/novo/', empresa_required(views.novo_abastecimento), name='novo_abastecimento'),
    path('ordens-compra/', empresa_required(views.lista_ordens_compra_gerais), name='lista_ordens_compra_gerais'),
    path('ordens-compra/nova/', empresa_required(views.nova_ordem_compra_geral), name='nova_ordem_compra_geral'),
    path(
        'ordens-compra/<int:ordem_id>/',
        empresa_required(views.detalhe_ordem_compra_geral),
        name='detalhe_ordem_compra_geral',
    ),
    path(
        'ordens-compra/<int:ordem_id>/editar/',
        empresa_required(views.editar_ordem_compra_geral),
        name='editar_ordem_compra_geral',
    ),
    path(
        'ordens-compra/<int:ordem_id>/pdf/',
        empresa_required(views.ordem_compra_geral_pdf),
        name='ordem_compra_geral_pdf',
    ),
    path(
        'ordens-compra/<int:ordem_id>/notas/nova/',
        empresa_required(views.nova_nf_ordem_compra_geral),
        name='nova_nf_ordem_compra_geral',
    ),
    path(
        'ordens-compra/notas/<int:nota_id>/editar/',
        empresa_required(views.editar_nf_ordem_compra_geral),
        name='editar_nf_ordem_compra_geral',
    ),
    path(
        'ordens-compra/notas/<int:nota_id>/gerar-conta/',
        empresa_required(views.gerar_conta_pagar_nf_ordem_compra),
        name='gerar_conta_pagar_nf_ordem_compra',
    ),
    path('combustivel/ordens/', empresa_required(views.lista_ordens_combustivel), name='lista_ordens_combustivel'),
    path('combustivel/ordens/nova/', empresa_required(views.nova_ordem_combustivel), name='nova_ordem_combustivel'),
    path(
        'combustivel/ordens/<int:ordem_id>/',
        empresa_required(views.detalhe_ordem_combustivel),
        name='detalhe_ordem_combustivel',
    ),
    path(
        'combustivel/ordens/<int:ordem_id>/pdf/',
        empresa_required(views.ordem_combustivel_pdf),
        name='ordem_combustivel_pdf',
    ),
    path(
        'combustivel/ordens/<int:ordem_id>/editar/',
        empresa_required(views.editar_ordem_combustivel),
        name='editar_ordem_combustivel',
    ),
    path(
        'combustivel/ordens/<int:ordem_id>/notas/nova/',
        empresa_required(views.nova_nf_combustivel),
        name='nova_nf_combustivel',
    ),
    path(
        'combustivel/notas/<int:nota_id>/editar/',
        empresa_required(views.editar_nf_combustivel),
        name='editar_nf_combustivel',
    ),
    path('combustivel/bombonas/', empresa_required(views.lista_bombonas_combustivel), name='lista_bombonas_combustivel'),
    path('combustivel/bombonas/nova/', empresa_required(views.nova_bombona_combustivel), name='nova_bombona_combustivel'),
    path(
        'combustivel/bombonas/<int:bombona_id>/editar/',
        empresa_required(views.editar_bombona_combustivel),
        name='editar_bombona_combustivel',
    ),
    path('veiculos/', empresa_required(views.lista_veiculos), name='lista_veiculos'),
    path('veiculos/novo/', empresa_required(views.novo_veiculo), name='novo_veiculo'),
    path('veiculos/<int:veiculo_id>/editar/', empresa_required(views.editar_veiculo), name='editar_veiculo'),
    path('maquinas-locadas/', empresa_required(views.lista_ordens_locacao_maquinas), name='lista_ordens_locacao_maquinas'),
    path('maquinas-locadas/nova/', empresa_required(views.nova_ordem_locacao_maquina), name='nova_ordem_locacao_maquina'),
    path(
        'maquinas-locadas/<int:ordem_id>/',
        empresa_required(views.detalhe_ordem_locacao_maquina),
        name='detalhe_ordem_locacao_maquina',
    ),
    path(
        'maquinas-locadas/<int:ordem_id>/pdf/',
        empresa_required(views.ordem_locacao_maquina_pdf),
        name='ordem_locacao_maquina_pdf',
    ),
    path(
        'maquinas-locadas/<int:ordem_id>/editar/',
        empresa_required(views.editar_ordem_locacao_maquina),
        name='editar_ordem_locacao_maquina',
    ),
    path(
        'maquinas-locadas/<int:ordem_id>/apontamentos/novo/',
        empresa_required(views.novo_apontamento_maquina),
        name='novo_apontamento_maquina',
    ),
    path(
        'maquinas-locadas/apontamentos/<int:apontamento_id>/editar/',
        empresa_required(views.editar_apontamento_maquina),
        name='editar_apontamento_maquina',
    ),
    path(
        'maquinas-locadas/<int:ordem_id>/notas/nova/',
        empresa_required(views.nova_nf_locacao_maquina),
        name='nova_nf_locacao_maquina',
    ),
    path(
        'maquinas-locadas/notas/<int:nota_id>/editar/',
        empresa_required(views.editar_nf_locacao_maquina),
        name='editar_nf_locacao_maquina',
    ),
    path('maquinas-locadas/catalogo/', empresa_required(views.lista_catalogo_maquinas_locacao), name='lista_catalogo_maquinas_locacao'),
    path('maquinas-locadas/catalogo/nova/', empresa_required(views.nova_maquina_locacao), name='nova_maquina_locacao'),
    path(
        'maquinas-locadas/catalogo/<int:maquina_id>/editar/',
        empresa_required(views.editar_maquina_locacao),
        name='editar_maquina_locacao',
    ),
    path('maquinas-locadas/fornecedores/', empresa_required(views.lista_fornecedores_maquinas), name='lista_fornecedores_maquinas'),
    path('maquinas-locadas/fornecedores/novo/', empresa_required(views.novo_fornecedor_maquina), name='novo_fornecedor_maquina'),
    path(
        'maquinas-locadas/fornecedores/<int:fornecedor_id>/editar/',
        empresa_required(views.editar_fornecedor_maquina),
        name='editar_fornecedor_maquina',
    ),
    path('equipamentos-locados/', empresa_required(views.lista_equipamentos_locados), name='lista_equipamentos_locados'),
    path(
        'equipamentos-locados/relatorio.pdf/',
        empresa_required(views.relatorio_locacoes_equipamentos_pdf),
        name='relatorio_locacoes_equipamentos_pdf',
    ),
    path('equipamentos-locados/nova/', empresa_required(views.nova_locacao_equipamento), name='nova_locacao_equipamento'),
    path(
        'equipamentos-locados/<int:locacao_id>/editar/',
        empresa_required(views.editar_locacao_equipamento),
        name='editar_locacao_equipamento',
    ),
    path(
        'equipamentos-locados/<int:locacao_id>/solicitar-retirada/',
        empresa_required(views.solicitar_retirada_equipamento),
        name='solicitar_retirada_equipamento',
    ),
    path(
        'equipamentos-locados/<int:locacao_id>/baixar/',
        empresa_required(views.baixar_locacao_equipamento),
        name='baixar_locacao_equipamento',
    ),
    path('catalogo-equipamentos/', empresa_required(views.lista_catalogo_equipamentos), name='lista_catalogo_equipamentos'),
    path('catalogo-equipamentos/novo/', empresa_required(views.novo_catalogo_equipamento), name='novo_catalogo_equipamento'),
    path('locadoras/', empresa_required(views.lista_locadoras), name='lista_locadoras'),
    path('locadoras/nova/', empresa_required(views.nova_locadora), name='nova_locadora'),
    path('radar-obras/', empresa_required(views.lista_radar_obras), name='lista_radar_obras'),
    path('radar-obras/pdf/', empresa_required(views.radar_obras_pdf), name='radar_obras_pdf'),
    path('radar-obras/novo/', empresa_required(views.novo_radar_obra), name='novo_radar_obra'),
    path('radar-obras/atualizar-lote/', empresa_required(views.atualizar_radar_obras_em_lote), name='atualizar_radar_obras_em_lote'),
    path('radar-obras/<int:orcamento_id>/atualizar/', empresa_required(views.atualizar_radar_obra), name='atualizar_radar_obra'),
    path('radar-obras/<int:orcamento_id>/arquivar/', empresa_required(views.arquivar_radar_obra), name='arquivar_radar_obra'),
    path('radar-obras/<int:orcamento_id>/editar/', empresa_required(views.editar_radar_obra), name='editar_radar_obra'),
    path('concretagens/', empresa_required(views.lista_concretagens), name='lista_concretagens'),
    path(
        'concretagens/solicitantes/',
        empresa_required(views.lista_solicitantes_concretagem),
        name='lista_solicitantes_concretagem',
    ),
    path(
        'concretagens/solicitantes/novo/',
        empresa_required(views.novo_solicitante_concretagem),
        name='novo_solicitante_concretagem',
    ),
    path(
        'concretagens/solicitantes/<int:solicitante_id>/editar/',
        empresa_required(views.editar_solicitante_concretagem),
        name='editar_solicitante_concretagem',
    ),
    path('concretagens/novo/', empresa_required(views.novo_contrato_concretagem), name='novo_contrato_concretagem'),
    path(
        'concretagens/<int:contrato_id>/',
        empresa_required(views.detalhe_contrato_concretagem),
        name='detalhe_contrato_concretagem',
    ),
    path(
        'concretagens/<int:contrato_id>/editar/',
        empresa_required(views.editar_contrato_concretagem),
        name='editar_contrato_concretagem',
    ),
    path(
        'concretagens/<int:contrato_id>/faturamentos/novo/',
        empresa_required(views.novo_faturamento_concretagem),
        name='novo_faturamento_concretagem',
    ),
    path(
        'concretagens/faturamentos/<int:faturamento_id>/editar/',
        empresa_required(views.editar_faturamento_concretagem),
        name='editar_faturamento_concretagem',
    ),
]
