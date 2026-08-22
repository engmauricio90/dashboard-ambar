import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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


def request_for(empresa):
    request = RequestFactory().get('/')
    request.empresa = empresa
    request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
    return request


def build():
    django.setup()

    from controles.models import (
        BombonaCombustivel,
        ItemOrdemCompraGeral,
        MaquinaLocacaoCatalogo,
        OrdemCompraCombustivel,
        OrdemCompraGeral,
        OrdemServicoLocacaoMaquina,
        FornecedorMaquinaLocacao,
        VeiculoMaquina,
    )
    from controles.views import ordem_combustivel_pdf, ordem_compra_geral_pdf, ordem_locacao_maquina_pdf
    from empresas.models import Empresa
    from financeiro.models import CentroCusto, Fornecedor
    from obras.models import Obra

    output_dir = Path('tmp/document_design_review/transacional')
    output_dir.mkdir(parents=True, exist_ok=True)
    previews_dir = output_dir / 'previews'

    empresa_a = Empresa.objects.create(
        nome='Empresa Demonstracao Engenharia',
        razao_social='EMPRESA DEMONSTRACAO ENGENHARIA LTDA',
        cnpj='00.000.000/0001-00',
        endereco='Rua Demonstracao, 100',
        cidade='Porto Alegre',
        estado='RS',
        telefone='(51) 3000-0000',
        email='contato@demonstracao.test',
        slug='empresa-demonstracao-transacional',
        cor_primaria='#0f4c5c',
        cor_secundaria='#64748b',
        texto_rodape='Documento gerado para validacao visual sintetica.',
    )
    empresa_b = Empresa.objects.create(
        nome='Empresa B Validacao',
        razao_social='EMPRESA B VALIDACAO LTDA',
        cnpj='11.111.111/0001-11',
        endereco='Rua B, 200',
        cidade='Sao Jose',
        estado='RS',
        slug='empresa-b-transacional',
        cor_primaria='#7c2d12',
        cor_secundaria='#0f766e',
    )
    empresa_incompleta = Empresa.objects.create(
        nome='Empresa Somente Nome',
        slug='empresa-somente-nome-transacional',
    )
    obra = Obra.objects.create(
        empresa=empresa_a,
        nome_obra='OBRA DEMONSTRACAO - Sao Jose',
        cliente='Cliente Demonstracao',
        responsavel='Joao Validacao',
    )
    centro = CentroCusto.objects.create(empresa=empresa_a, nome='Centro Demonstracao')
    fornecedor = Fornecedor.objects.create(
        empresa=empresa_a,
        nome='FORNECEDOR DEMONSTRACAO LTDA',
        cpf_cnpj='22.222.222/0001-22',
        endereco='Avenida Execucao, 123',
        bairro='Centro',
        cidade='Sao Jose',
        uf='RS',
        cep='93000-000',
        telefone='(51) 3555-0000',
    )
    long_desc = (
        'Fornecimento e execução de serviço de demonstração com descrição propositalmente extensa '
        'para validação da quebra automática de linhas, ajuste de altura da célula e comportamento '
        'da tabela durante a paginação do documento.'
    )

    def create_oc(numero, quantidade_itens, empresa=empresa_a, obra_ref=obra):
        oc = OrdemCompraGeral.objects.create(
            empresa=empresa,
            numero=numero,
            comprador='Responsavel Demonstracao',
            obra=obra_ref if empresa == empresa_a else None,
            centro_custo=centro if empresa == empresa_a else None,
            fornecedor_cadastro=fornecedor if empresa == empresa_a else None,
            fornecedor='FORNECEDOR DEMONSTRACAO LTDA',
            fornecedor_cpf_cnpj='22.222.222/0001-22',
            fornecedor_endereco='Avenida Execucao, 123',
            fornecedor_bairro='Centro',
            fornecedor_cidade='Sao Jose',
            fornecedor_uf='RS',
            fornecedor_cep='93000-000',
            fornecedor_fone='(51) 3555-0000',
            condicoes_pagamento='Condição de pagamento: 30 dias após emissão da nota fiscal.',
            observacoes='Observações sintéticas com acentuação: Construção, Medição, Execução, Serviço e Mão de obra.',
        )
        values = [Decimal('12.35'), Decimal('1234.56'), Decimal('123456.78'), Decimal('1234567.89')]
        for index in range(1, quantidade_itens + 1):
            unit = values[(index - 1) % len(values)]
            ItemOrdemCompraGeral.objects.create(
                ordem=oc,
                item=index,
                descricao=long_desc if index in {2, 17, 33} else f'Item sintetico de compra {index}',
                quantidade=Decimal('1.0000'),
                unidade='un',
                valor_unitario=unit,
            )
        return oc

    oc_curta = create_oc('OC-SINT-001/2026', 4)
    oc_longa = create_oc('OC-SINT-999/2026', 120)
    oc_b = create_oc('OC-B-001/2026', 3, empresa=empresa_b, obra_ref=None)
    oc_incompleta = create_oc('OC-INC-001/2026', 2, empresa=empresa_incompleta, obra_ref=None)

    veiculo = VeiculoMaquina.objects.create(
        empresa=empresa_a,
        placa='ABC1D23',
        descricao='Caminhao demonstracao',
    )
    bombona = BombonaCombustivel.objects.create(
        empresa=empresa_a,
        identificacao='BOMBONA-TESTE',
        capacidade_litros=Decimal('200.00'),
    )
    ordem_comb = OrdemCompraCombustivel.objects.create(
        empresa=empresa_a,
        numero='OC-COMB-SINT-001',
        fornecedor='POSTO DEMONSTRACAO',
        solicitante='Equipe Demonstracao',
        tipo_combustivel='diesel',
        tipo_destino='veiculo',
        veiculo=veiculo,
        quantidade_litros=Decimal('123.45'),
        valor_litro_previsto=Decimal('6.789'),
        observacoes='Observacoes de combustivel sinteticas.',
    )
    OrdemCompraCombustivel.objects.create(
        empresa=empresa_a,
        numero='OC-COMB-BOMBONA-SINT-001',
        fornecedor='POSTO BOMBONA',
        tipo_combustivel='diesel',
        tipo_destino='bombona',
        bombona=bombona,
        quantidade_litros=Decimal('50.00'),
        valor_litro_previsto=Decimal('6.50'),
    )

    fornecedor_maquina = FornecedorMaquinaLocacao.objects.create(
        empresa=empresa_a,
        nome='LOCADORA DEMONSTRACAO LTDA',
        telefone='(51) 3666-0000',
    )
    maquina = MaquinaLocacaoCatalogo.objects.create(
        nome='Escavadeira hidraulica demonstracao',
        categoria='Linha amarela',
    )
    os_maquina = OrdemServicoLocacaoMaquina.objects.create(
        obra=obra,
        fornecedor=fornecedor_maquina,
        maquina=maquina,
        numero='OS-MAQ-SINT-001',
        solicitante='Equipe Demonstracao',
        responsavel='Responsavel Tecnico',
        tipo_cobranca='por_hora',
        valor_hora=Decimal('345.67'),
        valor_mobilizacao=Decimal('1234.56'),
        valor_desmobilizacao=Decimal('987.65'),
        operador_incluso=True,
        observacoes='Locacao sintetica para validacao visual da ordem de servico.',
    )

    samples = [
        ('ordem_compra.pdf', ordem_compra_geral_pdf(request_for(empresa_a), oc_curta.id)),
        ('ordem_compra_multipagina.pdf', ordem_compra_geral_pdf(request_for(empresa_a), oc_longa.id)),
        ('ordem_combustivel.pdf', ordem_combustivel_pdf(request_for(empresa_a), ordem_comb.id)),
        ('os_locacao_maquina.pdf', ordem_locacao_maquina_pdf(request_for(empresa_a), os_maquina.id)),
        ('ordem_compra_empresa_b.pdf', ordem_compra_geral_pdf(request_for(empresa_b), oc_b.id)),
        ('ordem_compra_empresa_incompleta.pdf', ordem_compra_geral_pdf(request_for(empresa_incompleta), oc_incompleta.id)),
    ]
    for name, response in samples:
        pdf_path = output_dir / name
        pages = write_response(response, pdf_path)
        previews = save_previews(pdf_path, previews_dir)
        print(f'{name};pages={pages};previews={len(previews)};path={pdf_path}')


if __name__ == '__main__':
    django.setup()
    runner = DiscoverRunner(verbosity=0)
    old_config = runner.setup_databases()
    try:
        build()
    finally:
        runner.teardown_databases(old_config)
