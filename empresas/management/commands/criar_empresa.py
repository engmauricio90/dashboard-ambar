from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from empresas.models import Empresa


class Command(BaseCommand):
    help = 'Cria ou atualiza uma empresa de forma idempotente.'

    def add_arguments(self, parser):
        parser.add_argument('--nome', required=True, help='Nome da empresa.')
        parser.add_argument('--slug', required=True, help='Slug unico da empresa.')
        parser.add_argument('--inativa', action='store_true', help='Cria/atualiza a empresa como inativa.')

    def handle(self, *args, **options):
        nome = options['nome'].strip()
        slug = slugify(options['slug'].strip())
        if not nome:
            raise CommandError('Informe um nome valido para a empresa.')
        if not slug:
            raise CommandError('Informe um slug valido para a empresa.')

        empresa, created = Empresa.objects.get_or_create(
            slug=slug,
            defaults={
                'nome': nome,
                'ativa': not options['inativa'],
            },
        )
        updates = []
        if empresa.nome != nome:
            empresa.nome = nome
            updates.append('nome')
        ativa = not options['inativa']
        if empresa.ativa != ativa:
            empresa.ativa = ativa
            updates.append('ativa')
        if updates:
            empresa.save(update_fields=updates + ['atualizado_em'])

        acao = 'criada' if created else 'atualizada'
        self.stdout.write(self.style.SUCCESS(f'Empresa "{empresa.nome}" ({empresa.slug}) {acao} com sucesso.'))
