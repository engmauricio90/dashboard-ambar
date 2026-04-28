import os

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.crypto import get_random_string


class Command(BaseCommand):
    help = 'Cria ou atualiza um superusuario a partir de variaveis de ambiente.'

    def get_config(self, key):
        return getattr(settings, key, None) or os.environ.get(key, '')

    def handle(self, *args, **options):
        username = self.get_config('DJANGO_SUPERUSER_USERNAME').strip()
        email = self.get_config('DJANGO_SUPERUSER_EMAIL').strip()
        password = self.get_config('DJANGO_SUPERUSER_PASSWORD').strip()

        if not username:
            self.stdout.write(
                self.style.WARNING('DJANGO_SUPERUSER_USERNAME nao definido. Nenhum superusuario automatico foi criado.')
            )
            return

        user_model = get_user_model()
        user = user_model.objects.filter(username=username).first()

        generated_password = False
        if not password:
            password = get_random_string(24)
            generated_password = True

        if user:
            updated_fields = []
            if email and getattr(user, 'email', '') != email:
                user.email = email
                updated_fields.append('email')
            if not user.is_staff:
                user.is_staff = True
                updated_fields.append('is_staff')
            if not user.is_superuser:
                user.is_superuser = True
                updated_fields.append('is_superuser')
            if updated_fields:
                user.save(update_fields=updated_fields)
            user.set_password(password)
            user.save(update_fields=['password'])
            self.stdout.write(self.style.SUCCESS(f'Superusuario "{username}" atualizado com sucesso.'))
        else:
            user_model.objects.create_superuser(
                username=username,
                email=email,
                password=password,
            )
            self.stdout.write(self.style.SUCCESS(f'Superusuario "{username}" criado com sucesso.'))

        if generated_password:
            self.stdout.write(
                self.style.WARNING(
                    'DJANGO_SUPERUSER_PASSWORD nao definido. Uma senha aleatoria foi gerada; defina essa variavel no ambiente para acessar o sistema.'
                )
            )
