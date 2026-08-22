import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
from django.test import RequestFactory
from django.test.runner import DiscoverRunner
from pypdf import PdfReader


def write_response(response, path):
    path.write_bytes(response.content)
    return len(PdfReader(str(path)).pages)


def save_previews(pdf_path, previews_dir):
    previews_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    reader = PdfReader(str(pdf_path))
    for index, page in enumerate(reader.pages, start=1):
        if not page.images:
            continue
        image = page.images[0]
        suffix = Path(image.name).suffix or '.jpg'
        preview_path = previews_dir / f'{pdf_path.stem}_p{index}{suffix}'
        preview_path.write_bytes(image.data)
        saved.append(preview_path)
    return saved


def request_for(user, empresa):
    request = RequestFactory().get('/')
    request.user = user
    request.empresa = empresa
    return request


def build():
    django.setup()

    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from empresas.models import Empresa, UsuarioEmpresa
    from obras.models import Obra
    from controles.models import CronogramaObra, LinhaCronogramaObra
    from controles.views import cronograma_obra_pdf

    output_dir = Path('tmp/document_design_review/operacionais')
    previews_dir = output_dir / 'previews'
    output_dir.mkdir(parents=True, exist_ok=True)

    user = get_user_model().objects.create_user(username='operacionais-review', password='x')
    engenharia = Group.objects.get_or_create(name='Engenharia')[0]
    user.groups.add(engenharia)

    empresa_a = Empresa.objects.create(
        nome='Empresa Demonstração Engenharia',
        razao_social='EMPRESA DEMONSTRAÇÃO ENGENHARIA LTDA',
        cnpj='00.000.000/0001-00',
        endereco='Rua Demonstração, 100',
        cidade='Porto Alegre',
        estado='RS',
        slug='empresa-demonstracao-operacionais',
        cor_primaria='#0f4c5c',
        cor_secundaria='#64748b',
        texto_rodape='Documento sintético de validação dos PDFs operacionais.',
    )
    empresa_b = Empresa.objects.create(
        nome='Empresa B Operacional',
        razao_social='EMPRESA B OPERACIONAL LTDA',
        cnpj='22.222.222/0001-22',
        endereco='Rua B, 200',
        cidade='São José',
        estado='RS',
        slug='empresa-b-operacional',
        cor_primaria='#7c2d12',
    )
    empresa_incompleta = Empresa.objects.create(nome='Empresa Operacional Sem Branding', slug='empresa-operacional-sem-branding')
    for empresa in [empresa_a, empresa_b, empresa_incompleta]:
        UsuarioEmpresa.objects.create(usuario=user, empresa=empresa, grupo=engenharia)

    obra_a = Obra.objects.create(empresa=empresa_a, nome_obra='Obra Demonstração - São José', cliente='Cliente Fictício')
    obra_b = Obra.objects.create(empresa=empresa_b, nome_obra='Obra Empresa B', cliente='Cliente B')
    obra_incompleta = Obra.objects.create(empresa=empresa_incompleta, nome_obra='Obra Sem Branding')

    def cronograma(empresa, obra, nome, fim, linhas):
        item = CronogramaObra.objects.create(
            empresa=empresa,
            obra=obra,
            nome=nome,
            data_inicio=date(2026, 1, 1),
            data_fim=fim,
            formato=CronogramaObra.FORMATO_SEMANA,
        )
        for index in range(linhas):
            LinhaCronogramaObra.objects.create(
                cronograma=item,
                tipo=LinhaCronogramaObra.TIPO_GERAL if index % 8 == 0 else LinhaCronogramaObra.TIPO_SERVICO,
                servico=(
                    f'Execução de serviço operacional de demonstração {index + 1} '
                    'com descrição extensa para validação de quebra de texto, programação, medição e período.'
                ),
                periodos=[str(index % 24), str((index + 1) % 24), str((index + 2) % 24)],
                ordem=index,
            )
        return item

    samples = [
        ('cronograma_curto.pdf', empresa_a, cronograma(empresa_a, obra_a, 'Cronograma curto', date(2026, 2, 28), 7)),
        ('cronograma_longo.pdf', empresa_a, cronograma(empresa_a, obra_a, 'Cronograma longo multipágina', date(2026, 8, 31), 45)),
        ('cronograma_empresa_b.pdf', empresa_b, cronograma(empresa_b, obra_b, 'Cronograma Empresa B', date(2026, 4, 30), 15)),
        (
            'cronograma_empresa_incompleta.pdf',
            empresa_incompleta,
            cronograma(empresa_incompleta, obra_incompleta, 'Cronograma sem branding', date(2026, 3, 31), 9),
        ),
    ]
    for name, empresa, cron in samples:
        path = output_dir / name
        response = cronograma_obra_pdf(request_for(user, empresa), cron.id)
        pages = write_response(response, path)
        previews = save_previews(path, previews_dir)
        print(f'{name};pages={pages};previews={len(previews)};path={path}')


if __name__ == '__main__':
    django.setup()
    runner = DiscoverRunner(verbosity=0)
    old_config = runner.setup_databases()
    try:
        build()
    finally:
        runner.teardown_databases(old_config)
