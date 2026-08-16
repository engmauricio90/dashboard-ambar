from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from empresas.models import Empresa, UsuarioEmpresa


class Command(BaseCommand):
    help = 'Vincula um usuario existente a uma empresa existente.'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', required=True, help='Username do usuario existente.')
        parser.add_argument('--empresa', required=True, help='Slug da empresa existente.')
        parser.add_argument('--administrador', action='store_true', help='Marca o usuario como administrador da empresa.')
        parser.add_argument('--inativo', action='store_true', help='Cria/atualiza o vinculo como inativo.')

    def handle(self, *args, **options):
        user_model = get_user_model()
        usuario = user_model.objects.filter(username=options['usuario']).first()
        if not usuario:
            raise CommandError(f'Usuario "{options["usuario"]}" nao encontrado.')

        empresa = Empresa.objects.filter(slug=options['empresa']).first()
        if not empresa:
            raise CommandError(f'Empresa "{options["empresa"]}" nao encontrada.')

        vinculo, created = UsuarioEmpresa.objects.get_or_create(
            usuario=usuario,
            empresa=empresa,
            defaults={
                'ativo': not options['inativo'],
                'administrador_empresa': options['administrador'],
            },
        )
        updates = []
        ativo = not options['inativo']
        if vinculo.ativo != ativo:
            vinculo.ativo = ativo
            updates.append('ativo')
        if options['administrador'] and not vinculo.administrador_empresa:
            vinculo.administrador_empresa = True
            updates.append('administrador_empresa')
        if updates:
            vinculo.save(update_fields=updates)

        acao = 'criado' if created else 'atualizado'
        self.stdout.write(
            self.style.SUCCESS(f'Vinculo {acao}: {usuario.username} -> {empresa.nome}.')
        )
