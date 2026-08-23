from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.contrib.auth import views as auth_views

from empresas import views as empresas_views
from usuarios.forms import PlataformaPasswordResetForm

from .views import protected_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('media/<path:path>', protected_media, name='protected_media'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('plataforma/clientes/', empresas_views.clientes_plataforma, name='clientes_plataforma'),
    path('plataforma/clientes/novo/', empresas_views.novo_cliente_plataforma, name='novo_cliente_plataforma'),
    path('plataforma/clientes/<int:empresa_id>/', empresas_views.detalhe_cliente_plataforma, name='detalhe_cliente_plataforma'),
    path('plataforma/clientes/<int:empresa_id>/editar/', empresas_views.editar_cliente_plataforma, name='editar_cliente_plataforma'),
    path('plataforma/clientes/convites/<int:vinculo_id>/reenviar/', empresas_views.reenviar_convite_plataforma, name='reenviar_convite_plataforma'),
    path(
        'senha/redefinir/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.txt',
            html_email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
            form_class=PlataformaPasswordResetForm,
        ),
        name='password_reset',
    ),
    path(
        'senha/redefinir/enviado/',
        auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'),
        name='password_reset_done',
    ),
    path(
        'senha/redefinir/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'),
        name='password_reset_confirm',
    ),
    path(
        'senha/redefinir/concluido/',
        auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'),
        name='password_reset_complete',
    ),
    path('', include('dashboard.urls')),
    path('obras/', include('obras.urls')),
    path('controles/', include('controles.urls')),
    path('financeiro/', include('financeiro.urls')),
    path('medicoes/', include('medicoes.urls')),
    path('diarios/', include('diarios.urls')),
    path('usuarios/', include('usuarios.urls')),
    path('empresas/', include('empresas.urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
