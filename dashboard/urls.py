from django.urls import path
from . import views

urlpatterns = [
    path('healthz/', views.healthz, name='healthz'),
    path('dashboard/', views.home, name='home'),
    path('relatorios/geral/', views.relatorio_geral, name='relatorio_geral'),
]
