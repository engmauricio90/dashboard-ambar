from django.urls import path

from . import views


app_name = 'social_automation'

urlpatterns = [
    path('', views.home, name='home'),
    path('perfis/', views.profile_list, name='profile_list'),
    path('perfis/novo/', views.profile_create, name='profile_create'),
    path('perfis/<int:profile_id>/', views.profile_detail, name='profile_detail'),
    path('perfis/<int:profile_id>/instagram/testar/', views.instagram_health, name='instagram_health'),
    path('perfis/<int:profile_id>/automacao/executar/', views.automation_run_now, name='automation_run_now'),
    path('perfis/<int:profile_id>/editar/', views.profile_update, name='profile_update'),
    path('perfis/<int:profile_id>/toggle/', views.profile_toggle, name='profile_toggle'),
    path('perfis/<int:profile_id>/gerar/', views.profile_generate, name='profile_generate'),
    path('perfis/<int:profile_id>/imagens/', views.image_list, name='image_list'),
    path('perfis/<int:profile_id>/imagens/nova/', views.image_create, name='image_create'),
    path('imagens/<int:image_id>/editar/', views.image_update, name='image_update'),
    path('imagens/<int:image_id>/toggle/', views.image_toggle, name='image_toggle'),
    path('conteudos/', views.content_list, name='content_list'),
    path('perfis/<int:profile_id>/conteudos/', views.content_list, name='profile_content_list'),
    path('conteudos/novo/', views.content_create, name='content_create'),
    path('perfis/<int:profile_id>/conteudos/novo/', views.content_create, name='profile_content_create'),
    path('conteudos/<int:content_id>/', views.content_detail, name='content_detail'),
    path('conteudos/<int:content_id>/editar/', views.content_update, name='content_update'),
    path('conteudos/<int:content_id>/renderizar/', views.content_render, name='content_render'),
    path('conteudos/<int:content_id>/publicar-instagram/', views.content_publish_instagram, name='content_publish_instagram'),
    path('conteudos/<int:content_id>/aprovar/', views.content_approve, name='content_approve'),
    path('conteudos/<int:content_id>/rejeitar/', views.content_reject, name='content_reject'),
    path('conteudos/<int:content_id>/restaurar/', views.content_restore, name='content_restore'),
    path('conteudos/<int:content_id>/agendar/', views.content_schedule, name='content_schedule'),
    path('conteudos/<int:content_id>/desagendar/', views.content_unschedule, name='content_unschedule'),
    path('conteudos/<int:content_id>/excluir/', views.content_delete, name='content_delete'),
    path('conteudos/aprovar-lote/', views.content_bulk_approve, name='content_bulk_approve'),
    path('public/<path:token>/', views.public_final_image, name='public_final_image'),
]
