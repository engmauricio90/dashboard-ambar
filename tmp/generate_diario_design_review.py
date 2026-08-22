import os
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
from django.core.files.base import ContentFile
from django.test import RequestFactory
from django.test.runner import DiscoverRunner
from PIL import Image, ImageDraw
from pypdf import PdfReader


def image_file(label, size, color):
    image = Image.new('RGB', size, color)
    draw = ImageDraw.Draw(image)
    draw.text((28, 28), label, fill='white')
    buffer = BytesIO()
    image.save(buffer, format='JPEG', quality=82)
    return ContentFile(buffer.getvalue(), name=f'{label.lower().replace(" ", "-")}.jpg')


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
    from diarios.models import DiarioObra, EfetivoDiario, EquipamentoDiario, FotoDiario, OcorrenciaDiario, ChecklistDiario
    from diarios.views import diario_pdf

    output_dir = Path('tmp/document_design_review/diario')
    previews_dir = output_dir / 'previews'
    output_dir.mkdir(parents=True, exist_ok=True)

    user_model = get_user_model()
    user = user_model.objects.create_user(username='diario-review', password='x')
    engenharia = Group.objects.get_or_create(name='Engenharia')[0]
    user.groups.add(engenharia)

    empresa_a = Empresa.objects.create(
        nome='Empresa Demonstração Engenharia',
        razao_social='EMPRESA DEMONSTRAÇÃO ENGENHARIA LTDA',
        cnpj='00.000.000/0001-00',
        endereco='Rua Demonstração, 100',
        cidade='Porto Alegre',
        estado='RS',
        slug='empresa-demonstracao-diario',
        cor_primaria='#0f4c5c',
        cor_secundaria='#64748b',
        texto_rodape='Documento sintético de validação do Diário de Obra.',
    )
    empresa_b = Empresa.objects.create(
        nome='Empresa B Diário',
        razao_social='EMPRESA B DIÁRIO LTDA',
        cnpj='11.111.111/0001-11',
        endereco='Rua B, 200',
        cidade='São José',
        estado='RS',
        slug='empresa-b-diario',
        cor_primaria='#7c2d12',
    )
    empresa_incompleta = Empresa.objects.create(nome='Empresa Diário Sem Branding', slug='empresa-diario-sem-branding')
    UsuarioEmpresa.objects.create(usuario=user, empresa=empresa_a, grupo=engenharia)
    UsuarioEmpresa.objects.create(usuario=user, empresa=empresa_b, grupo=engenharia)
    UsuarioEmpresa.objects.create(usuario=user, empresa=empresa_incompleta, grupo=engenharia)

    obra_a = Obra.objects.create(empresa=empresa_a, nome_obra='Obra Demonstração - São José', cliente='Cliente Fictício')
    obra_b = Obra.objects.create(empresa=empresa_b, nome_obra='Obra Empresa B', cliente='Cliente B')
    obra_incompleta = Obra.objects.create(empresa=empresa_incompleta, nome_obra='Obra Sem Branding')

    texto_longo = (
        'Execução de serviços de demonstração no setor norte da obra, contemplando preparação da área, '
        'conferência de níveis, posicionamento dos elementos e acompanhamento das atividades executadas durante o período. '
        'Foram verificadas condições de segurança, tubulação, concretagem e mão de obra em São José. '
    )

    def create_diario(obra, completo=False, fotos=0, day=22):
        diario = DiarioObra.objects.create(
            obra=obra,
            data=date(2026, 8, day),
            responsavel_preenchimento='Eng. Campo Demonstração',
            responsavel_tecnico='Responsável Técnico',
            condicao_climatica=DiarioObra.CLIMA_PARCIALMENTE_NUBLADO,
            turno=DiarioObra.TURNO_INTEGRAL,
            situacao_obra=DiarioObra.SITUACAO_ANDAMENTO,
            descricao_servicos=(texto_longo * 4 if completo else texto_longo),
            observacoes='Observações do diário com Execução, Construção, Medição, Tubulação e Condições do dia.',
            ocorrencias_interferencias=(texto_longo * 3 if completo else ''),
            pendencias=(texto_longo * 2 if completo else ''),
            orientacoes=(texto_longo * 2 if completo else ''),
            houve_visita=True,
            visitante_nome='Fiscalização Demonstração',
            status=DiarioObra.STATUS_FINALIZADO,
        )
        if completo:
            for funcao, qtd in [('servente', 8), ('pedreiro', 3), ('operador_maquina', 2)]:
                EfetivoDiario.objects.create(diario=diario, funcao=funcao, quantidade=qtd, observacoes='Equipe sintética')
            for tipo, qtd in [('escavadeira_hidraulica', 1), ('caminhao_cacamba', 2), ('rolo_compactador', 1)]:
                EquipamentoDiario.objects.create(diario=diario, tipo=tipo, quantidade=qtd, situacao='operando', observacoes='Operação normal')
            OcorrenciaDiario.objects.create(diario=diario, tipo='chuva', descricao=texto_longo * 2, impacto_prazo='parcial', status='em_andamento')
            ChecklistDiario.objects.create(diario=diario, item=ChecklistDiario.ITEM_EPI, resultado='conforme', observacoes='Conforme verificação visual.')
        sizes = [(1000, 600), (600, 1000), (720, 720), (1100, 520), (520, 1100), (900, 650), (650, 900), (800, 800)]
        for index in range(fotos):
            FotoDiario.objects.create(
                diario=diario,
                imagem=image_file(f'Foto {index + 1}', sizes[index % len(sizes)], (25 + index * 18, 90, 135)),
                legenda=f'Foto {index + 1}: legenda sintética longa com execução, construção, medição e conferência de níveis.',
                uploaded_by=user,
            )
        return diario

    diario_curto = create_diario(obra_a, completo=False, fotos=0, day=22)
    diario_completo = create_diario(obra_a, completo=True, fotos=8, day=23)
    diario_b = create_diario(obra_b, completo=True, fotos=3, day=22)
    diario_incompleto = create_diario(obra_incompleta, completo=False, fotos=1, day=22)

    samples = [
        ('diario_curto.pdf', diario_pdf(request_for(user, empresa_a), diario_curto.id), diario_curto.fotos.count()),
        ('diario_completo.pdf', diario_pdf(request_for(user, empresa_a), diario_completo.id), diario_completo.fotos.count()),
        ('diario_fotografico.pdf', diario_pdf(request_for(user, empresa_a), diario_completo.id), diario_completo.fotos.count()),
        ('diario_empresa_b.pdf', diario_pdf(request_for(user, empresa_b), diario_b.id), diario_b.fotos.count()),
        ('diario_empresa_incompleta.pdf', diario_pdf(request_for(user, empresa_incompleta), diario_incompleto.id), diario_incompleto.fotos.count()),
    ]
    for name, response, photos in samples:
        path = output_dir / name
        pages = write_response(response, path)
        previews = save_previews(path, previews_dir)
        print(f'{name};pages={pages};photos={photos};previews={len(previews)};path={path}')


if __name__ == '__main__':
    django.setup()
    runner = DiscoverRunner(verbosity=0)
    old_config = runner.setup_databases()
    try:
        build()
    finally:
        runner.teardown_databases(old_config)
