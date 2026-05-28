from django.urls import path

from . import views


urlpatterns = [
    path('', views.lista_diarios, name='lista_diarios'),
    path('novo/', views.novo_diario, name='novo_diario'),
    path('<int:diario_id>/', views.detalhe_diario, name='detalhe_diario'),
    path('<int:diario_id>/editar/', views.editar_diario, name='editar_diario'),
    path('<int:diario_id>/finalizar/', views.finalizar_diario, name='finalizar_diario'),
    path('<int:diario_id>/reabrir/', views.reabrir_diario, name='reabrir_diario'),
    path('<int:diario_id>/cancelar/', views.cancelar_diario, name='cancelar_diario'),
    path('<int:diario_id>/excluir/', views.excluir_diario, name='excluir_diario'),
    path('<int:diario_id>/pdf/', views.diario_pdf, name='diario_pdf'),
]
