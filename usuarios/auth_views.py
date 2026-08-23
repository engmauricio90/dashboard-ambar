from django.conf import settings
from django.contrib.auth.views import LoginView, PasswordResetView

from config.rate_limit import check_rate_limit, client_ip, normalized, too_many_requests

from .forms import PlataformaPasswordResetForm


class RateLimitedLoginView(LoginView):
    template_name = 'registration/login.html'

    def post(self, request, *args, **kwargs):
        username = normalized(request.POST.get('username'))
        blocked, _count = check_rate_limit(
            'login',
            [client_ip(request), username],
            settings.LOGIN_RATE_LIMIT,
            settings.LOGIN_RATE_LIMIT_WINDOW,
        )
        if blocked:
            return too_many_requests('Muitas tentativas de login. Aguarde alguns minutos e tente novamente.')
        return super().post(request, *args, **kwargs)


class RateLimitedPasswordResetView(PasswordResetView):
    template_name = 'registration/password_reset_form.html'
    email_template_name = 'registration/password_reset_email.txt'
    html_email_template_name = 'registration/password_reset_email.html'
    subject_template_name = 'registration/password_reset_subject.txt'
    form_class = PlataformaPasswordResetForm

    def post(self, request, *args, **kwargs):
        email = normalized(request.POST.get('email'))
        blocked, _count = check_rate_limit(
            'password-reset',
            [client_ip(request), email],
            settings.PASSWORD_RESET_RATE_LIMIT,
            settings.PASSWORD_RESET_RATE_LIMIT_WINDOW,
        )
        if blocked:
            return too_many_requests('Muitas solicitacoes de redefinicao. Aguarde e tente novamente.')
        return super().post(request, *args, **kwargs)
