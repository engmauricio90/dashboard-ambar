from django.urls import path

from . import views


app_name = 'billing'

urlpatterns = [
    path('assinatura-pendente/', views.assinatura_pendente, name='assinatura_pendente'),
    path('retorno/<uuid:public_id>/', views.checkout_retorno, name='checkout_retorno'),
    path('webhooks/mercadopago/', views.mercadopago_webhook, name='mercadopago_webhook'),
]


platform_urlpatterns = [
    path('assinar/', views.checkout_publico, name='checkout_publico'),
    path('plataforma/contratacoes/', views.contratacoes_plataforma, name='contratacoes_plataforma'),
    path('plataforma/contratacoes/<int:intent_id>/', views.detalhe_contratacao_plataforma, name='detalhe_contratacao_plataforma'),
    path('plataforma/leads/<int:lead_id>/preparar-contratacao/', views.preparar_contratacao, name='preparar_contratacao_lead'),
    path('plataforma/assinaturas/', views.assinaturas_plataforma, name='assinaturas_plataforma'),
    path('plataforma/assinaturas/<int:assinatura_id>/', views.detalhe_assinatura_plataforma, name='detalhe_assinatura_plataforma'),
    path('plataforma/assinaturas/<int:assinatura_id>/ativar/', views.ativar_assinatura_manual, name='ativar_assinatura_manual'),
    path('plataforma/assinaturas/<int:assinatura_id>/cancelar/', views.cancelar_assinatura, name='cancelar_assinatura_plataforma'),
]
