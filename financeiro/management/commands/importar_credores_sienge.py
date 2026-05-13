from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from financeiro.importadores import importar_contas_pagar_credores_csv, importar_contas_pagas_credores_csv


class Command(BaseCommand):
    help = 'Importa relatorio de credores do Sienge para contas a pagar.'

    def add_arguments(self, parser):
        parser.add_argument('arquivo', type=str)
        parser.add_argument(
            '--tipo',
            choices=['aberto', 'pago'],
            default='aberto',
            help='Tipo de relatorio: aberto ou pago.',
        )

    def handle(self, *args, **options):
        caminho = Path(options['arquivo'])
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

        importador = importar_contas_pagas_credores_csv if options['tipo'] == 'pago' else importar_contas_pagar_credores_csv
        resultado = importador(conteudo)
        self.stdout.write(
            self.style.SUCCESS(
                f'Importacao concluida: {resultado.criadas} criada(s), '
                f'{resultado.atualizadas} atualizada(s), {resultado.ignoradas} ignorada(s).'
            )
        )
