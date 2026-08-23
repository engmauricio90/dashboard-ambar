from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from .models import Empresa, UsuarioEmpresa


EMPRESA_PADRAO_NOME = 'Ambar Engenharia'
EMPRESA_PADRAO_SLUG = 'ambar'


def obter_ou_criar_empresa_padrao():
    """Compatibilidade temporaria monoempresa ate a Fase 3 usar empresa ativa no request."""
    empresa, _created = Empresa.objects.get_or_create(
        slug=EMPRESA_PADRAO_SLUG,
        defaults={
            'nome': EMPRESA_PADRAO_NOME,
            'ativa': True,
        },
    )
    return empresa


def empresas_do_usuario(user):
    if not getattr(user, 'is_authenticated', False):
        return Empresa.objects.none()
    return Empresa.objects.filter(
        usuarios_vinculados__usuario=user,
        usuarios_vinculados__ativo=True,
        ativa=True,
    ).distinct().order_by('nome')


def usuario_tem_acesso_empresa(user, empresa):
    if not getattr(user, 'is_authenticated', False) or empresa is None:
        return False
    return empresas_do_usuario(user).filter(pk=empresa.pk).exists()


def usuario_administra_empresa(user, empresa):
    if getattr(user, 'is_superuser', False):
        return True
    if not getattr(user, 'is_authenticated', False) or empresa is None:
        return False
    return UsuarioEmpresa.objects.filter(
        usuario=user,
        empresa=empresa,
        ativo=True,
        administrador_empresa=True,
        empresa__ativa=True,
    ).exists()


def definir_empresa_na_sessao(request, empresa):
    if not usuario_tem_acesso_empresa(request.user, empresa):
        request.session.pop('empresa_id', None)
        return None
    request.session['empresa_id'] = empresa.id
    return empresa


def empresa_ativa_do_request(request):
    if not getattr(request.user, 'is_authenticated', False):
        request.session.pop('empresa_id', None)
        return None

    empresas = list(empresas_do_usuario(request.user))
    if not empresas:
        request.session.pop('empresa_id', None)
        return None

    empresa_id = request.session.get('empresa_id')
    if empresa_id:
        for empresa in empresas:
            if str(empresa.id) == str(empresa_id):
                return empresa
        request.session.pop('empresa_id', None)

    if len(empresas) == 1:
        empresa = empresas[0]
        request.session['empresa_id'] = empresa.id
        return empresa

    return None


def vincular_usuarios_existentes_a_empresa_padrao():
    empresa = obter_ou_criar_empresa_padrao()
    user_model = get_user_model()
    for usuario in user_model.objects.all():
        UsuarioEmpresa.objects.get_or_create(
            usuario=usuario,
            empresa=empresa,
            defaults={
                'ativo': True,
                'administrador_empresa': usuario.is_superuser,
            },
        )
    return empresa


def vincular_usuario_as_empresas_do_criador(usuario, criador):
    vinculos = UsuarioEmpresa.objects.filter(usuario=criador, ativo=True).select_related('empresa')
    criados = []
    for vinculo in vinculos:
        novo_vinculo, created = UsuarioEmpresa.objects.get_or_create(
            usuario=usuario,
            empresa=vinculo.empresa,
            defaults={
                'ativo': True,
                'administrador_empresa': usuario.is_superuser,
            },
        )
        if created:
            criados.append(novo_vinculo)
    return criados


def gerar_slug_empresa(nome):
    base = slugify(nome) or 'empresa'
    slug = base[:70]
    contador = 2
    while Empresa.objects.filter(slug__iexact=slug).exists():
        sufixo = f'-{contador}'
        slug = f'{base[:80 - len(sufixo)]}{sufixo}'
        contador += 1
    return slug


def gerar_username_por_email(email):
    user_model = get_user_model()
    base = slugify(email.split('@')[0]) or 'usuario'
    base = base[:120]
    username = base
    contador = 2
    while user_model.objects.filter(username__iexact=username).exists():
        sufixo = f'-{contador}'
        username = f'{base[:150 - len(sufixo)]}{sufixo}'
        contador += 1
    return username


def criar_cliente_assistido(dados):
    user_model = get_user_model()
    with transaction.atomic():
        empresa = Empresa.objects.create(
            nome=dados['nome'],
            razao_social=dados.get('razao_social', ''),
            cnpj=dados.get('cnpj', ''),
            email=dados.get('email', ''),
            telefone=dados.get('telefone', ''),
            cidade=dados.get('cidade', ''),
            estado=dados.get('estado', ''),
            cep=dados.get('cep', ''),
            slug=gerar_slug_empresa(dados['nome']),
            ativa=True,
        )
        usuario = dados.get('usuario_existente')
        usuario_criado = False
        if usuario is None:
            usuario = user_model(
                username=gerar_username_por_email(dados['admin_email']),
                first_name=dados.get('admin_first_name', ''),
                last_name=dados.get('admin_last_name', ''),
                email=dados['admin_email'],
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            usuario.set_unusable_password()
            usuario.save()
            usuario_criado = True

        vinculo = UsuarioEmpresa.objects.create(
            usuario=usuario,
            empresa=empresa,
            grupo=dados.get('admin_grupo'),
            ativo=True,
            administrador_empresa=True,
        )
    return {
        'empresa': empresa,
        'usuario': usuario,
        'vinculo': vinculo,
        'usuario_criado': usuario_criado,
    }
