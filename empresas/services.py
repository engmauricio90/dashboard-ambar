from django.contrib.auth import get_user_model

from .models import Empresa, UsuarioEmpresa


EMPRESA_PADRAO_NOME = 'Ambar Engenharia'
EMPRESA_PADRAO_SLUG = 'ambar'


def obter_ou_criar_empresa_padrao():
    empresa, _created = Empresa.objects.get_or_create(
        slug=EMPRESA_PADRAO_SLUG,
        defaults={
            'nome': EMPRESA_PADRAO_NOME,
            'ativa': True,
        },
    )
    return empresa


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
