from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='public_home'),
    path('privacidade/', views.privacidade, name='public_privacidade'),
    path('termos/', views.termos, name='public_termos'),
    path('plataforma/leads/', views.leads_plataforma, name='leads_plataforma'),
    path('plataforma/leads/<int:lead_id>/', views.detalhe_lead_plataforma, name='detalhe_lead_plataforma'),
]
