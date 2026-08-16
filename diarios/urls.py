from django.urls import path

from empresas.decorators import empresa_required

from . import views


urlpatterns = [
    path('', empresa_required(views.lista_diarios), name='lista_diarios'),
    path('novo/', empresa_required(views.novo_diario), name='novo_diario'),
    path('<int:diario_id>/', empresa_required(views.detalhe_diario), name='detalhe_diario'),
    path('<int:diario_id>/editar/', empresa_required(views.editar_diario), name='editar_diario'),
    path('<int:diario_id>/finalizar/', empresa_required(views.finalizar_diario), name='finalizar_diario'),
    path('<int:diario_id>/reabrir/', empresa_required(views.reabrir_diario), name='reabrir_diario'),
    path('<int:diario_id>/cancelar/', empresa_required(views.cancelar_diario), name='cancelar_diario'),
    path('<int:diario_id>/excluir/', empresa_required(views.excluir_diario), name='excluir_diario'),
    path('<int:diario_id>/pdf/', empresa_required(views.diario_pdf), name='diario_pdf'),
]
