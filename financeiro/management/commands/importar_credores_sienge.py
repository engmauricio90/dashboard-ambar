from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from financeiro.importadores import importar_contas_pagar_credores_csv, importar_contas_pagas_credores_csv


class Command(BaseCommand):
    help = 'Importa o relatorio de credores do Sienge como contas a pagar.'

    def add_arguments(self, parser):
        parser.add_argument('arquivo_csv', type=str)
        parser.add_argument('--pagas', action='store_true', help='Importa como contas ja pagas.')

    def handle(self, *args, **options):
        caminho = Path(options['arquivo_csv'])
        if not caminho.exists():
            raise CommandError(f'Arquivo nao encontrado: {caminho}')

        conteudo = None
        for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                conteudo = caminho.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if conteudo is None:
            conteudo = caminho.read_text(encoding='latin-1', errors='replace')

        if options['pagas']:
            resultado = importar_contas_pagas_credores_csv(conteudo)
        else:
            resultado = importar_contas_pagar_credores_csv(conteudo)
        self.stdout.write(
            self.style.SUCCESS(
                f'{resultado.criadas} criada(s), {resultado.atualizadas} atualizada(s), '
                f'{resultado.ignoradas} ignorada(s). Obras criadas: {resultado.obras_criadas}. '
                f'Centros criados: {resultado.centros_criados}.'
            )
        )
