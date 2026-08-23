import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Envia um e-mail transacional de teste para validar SMTP em producao.'

    def add_arguments(self, parser):
        parser.add_argument('destinatario', help='E-mail que recebera a mensagem de teste.')

    def handle(self, *args, **options):
        destinatario = options['destinatario']
        subject = f'Teste de e-mail - {settings.PLATFORM_NAME}'
        body = (
            'Este e um teste automatico de SMTP do sistema.\n\n'
            'Se voce recebeu esta mensagem, o backend de e-mail respondeu corretamente.'
        )
        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[destinatario],
            reply_to=[settings.PLATFORM_SUPPORT_EMAIL] if settings.PLATFORM_SUPPORT_EMAIL else None,
        )
        try:
            sent = message.send(fail_silently=False)
        except Exception as exc:
            logger.exception('Falha no teste de SMTP.')
            raise CommandError('Falha ao enviar e-mail de teste. Verifique EMAIL_HOST, porta, TLS/SSL e credenciais.') from exc

        if sent != 1:
            raise CommandError('O backend de e-mail nao confirmou o envio da mensagem de teste.')

        self.stdout.write(self.style.SUCCESS(f'E-mail de teste enviado para {destinatario}.'))
