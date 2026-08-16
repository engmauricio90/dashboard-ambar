from django.urls import path

from empresas.decorators import empresa_required

from . import views


urlpatterns = [
    path('', empresa_required(views.medicoes_home), name='medicoes_home'),
    path('relatorio/', empresa_required(views.relatorio_medicoes), name='relatorio_medicoes'),
    path('construtora/', empresa_required(views.medicoes_construtora_home), name='medicoes_construtora_home'),
    path('empreiteiros/', empresa_required(views.medicoes_empreiteiros_home), name='medicoes_empreiteiros_home'),
    path('empreiteiros/cadastro/', empresa_required(views.lista_empreiteiros), name='lista_empreiteiros_medicao'),
    path('empreiteiros/cadastro/novo/', empresa_required(views.novo_empreiteiro), name='novo_empreiteiro_medicao'),
    path('empreiteiros/cadastro/<int:empreiteiro_id>/editar/', empresa_required(views.editar_empreiteiro), name='editar_empreiteiro_medicao'),
    path('obras/<int:obra_id>/', empresa_required(views.medicoes_obra), name='medicoes_obra'),
    path('orcamentos/', empresa_required(views.lista_orcamentos), name='lista_orcamentos_medicao'),
    path('orcamentos/importar/', empresa_required(views.importar_orcamento), name='importar_orcamento_medicao'),
    path('orcamentos/manual/novo/', empresa_required(views.novo_orcamento_manual), name='novo_orcamento_manual_medicao'),
    path('orcamentos/<int:orcamento_id>/', empresa_required(views.detalhe_orcamento), name='detalhe_orcamento_medicao'),
    path('orcamentos/<int:orcamento_id>/itens/editar/', empresa_required(views.editar_itens_orcamento), name='editar_itens_orcamento_medicao'),
    path(
        'orcamentos/<int:orcamento_id>/saldo-contratual/',
        empresa_required(views.saldo_contratual_construtora),
        name='saldo_contratual_construtora',
    ),
    path(
        'orcamentos/<int:orcamento_id>/saldo-contratual/pdf/',
        empresa_required(views.saldo_contratual_construtora_pdf),
        name='saldo_contratual_construtora_pdf',
    ),
    path(
        'orcamentos/<int:orcamento_id>/saldo-contratual/excel/',
        empresa_required(views.saldo_contratual_construtora_excel),
        name='saldo_contratual_construtora_excel',
    ),
    path('orcamentos/<int:orcamento_id>/excluir/', empresa_required(views.excluir_orcamento), name='excluir_orcamento_medicao'),
    path(
        'orcamentos/<int:orcamento_id>/construtora/nova/',
        empresa_required(views.nova_medicao_construtora),
        name='nova_medicao_construtora',
    ),
    path('construtora/<int:medicao_id>/editar/', empresa_required(views.editar_medicao_construtora), name='editar_medicao_construtora'),
    path('construtora/<int:medicao_id>/excluir/', empresa_required(views.excluir_medicao_construtora), name='excluir_medicao_construtora'),
    path('construtora/<int:medicao_id>/pdf/', empresa_required(views.medicao_construtora_pdf), name='medicao_construtora_pdf'),
    path('construtora/<int:medicao_id>/excel/', empresa_required(views.medicao_construtora_excel), name='medicao_construtora_excel'),
    path('empreiteiros/simples/nova/', empresa_required(views.nova_medicao_empreiteiro_simples), name='nova_medicao_empreiteiro_simples'),
    path(
        'orcamentos/<int:orcamento_id>/empreiteiro/cumulativa/nova/',
        empresa_required(views.nova_medicao_empreiteiro_cumulativa),
        name='nova_medicao_empreiteiro_cumulativa',
    ),
    path('empreiteiros/<int:medicao_id>/editar/', empresa_required(views.editar_medicao_empreiteiro), name='editar_medicao_empreiteiro'),
    path('empreiteiros/<int:medicao_id>/excluir/', empresa_required(views.excluir_medicao_empreiteiro), name='excluir_medicao_empreiteiro'),
    path('empreiteiros/<int:medicao_id>/pdf/', empresa_required(views.medicao_empreiteiro_pdf), name='medicao_empreiteiro_pdf'),
    path('empreiteiros/<int:medicao_id>/excel/', empresa_required(views.medicao_empreiteiro_excel), name='medicao_empreiteiro_excel'),
]
