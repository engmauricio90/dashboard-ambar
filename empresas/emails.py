import logging
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


logger = logging.getLogger(__name__)


def _absolute_url(request, path):
    if settings.PLATFORM_BASE_URL:
        return urljoin(settings.PLATFORM_BASE_URL.rstrip('/') + '/', path.lstrip('/'))
    return request.build_absolute_uri(path)


def _send_transactional_email(subject_template, text_template, html_template, context, recipient):
    subject = ''.join(render_to_string(subject_template, context).splitlines()).strip()
    text_body = render_to_string(text_template, context)
    html_body = render_to_string(html_template, context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        reply_to=[settings.PLATFORM_SUPPORT_EMAIL] if settings.PLATFORM_SUPPORT_EMAIL else None,
    )
    message.attach_alternative(html_body, 'text/html')
    message.send()


def enviar_convite_usuario_empresa(request, vinculo):
    usuario = vinculo.usuario
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    reset_path = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
    context = {
        'platform_name': settings.PLATFORM_NAME,
        'support_email': settings.PLATFORM_SUPPORT_EMAIL,
        'empresa': vinculo.empresa,
        'usuario': usuario,
        'reset_url': _absolute_url(request, reset_path),
        'login_url': _absolute_url(request, reverse('login')),
    }
    try:
        _send_transactional_email(
            'empresas/emails/convite_usuario_subject.txt',
            'empresas/emails/convite_usuario.txt',
            'empresas/emails/convite_usuario.html',
            context,
            usuario.email,
        )
        return True
    except Exception:
        logger.exception('Falha ao enviar convite de usuario da empresa.')
        return False


def enviar_acesso_usuario_empresa(request, vinculo):
    usuario = vinculo.usuario
    context = {
        'platform_name': settings.PLATFORM_NAME,
        'support_email': settings.PLATFORM_SUPPORT_EMAIL,
        'empresa': vinculo.empresa,
        'usuario': usuario,
        'login_url': _absolute_url(request, reverse('login')),
    }
    try:
        _send_transactional_email(
            'empresas/emails/acesso_usuario_subject.txt',
            'empresas/emails/acesso_usuario.txt',
            'empresas/emails/acesso_usuario.html',
            context,
            usuario.email,
        )
        return True
    except Exception:
        logger.exception('Falha ao enviar comunicacao de acesso de usuario da empresa.')
        return False
