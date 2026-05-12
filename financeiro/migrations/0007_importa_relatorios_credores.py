from pathlib import Path
import sys

from django.db import migrations


def importar_relatorios_credores(apps, schema_editor):
    if 'test' in sys.argv:
        return

    from financeiro.importadores import (
        importar_contas_pagar_credores_csv,
        importar_contas_pagas_credores_csv,
    )

    data_dir = Path(__file__).resolve().parents[1] / 'data'
    arquivos = [
        (data_dir / 'relatorio_credores_abertos.csv', importar_contas_pagar_credores_csv),
        (data_dir / 'relatorio_credores_pagos.csv', importar_contas_pagas_credores_csv),
    ]

    for caminho, importador in arquivos:
        if not caminho.exists():
            continue
        conteudo = None
        for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                conteudo = caminho.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if conteudo is None:
            conteudo = caminho.read_text(encoding='latin-1', errors='replace')
        importador(conteudo)


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0006_contapagar_codigo_externo_and_more'),
    ]

    operations = [
        migrations.RunPython(importar_relatorios_credores, migrations.RunPython.noop),
    ]
