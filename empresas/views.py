from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib import messages
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import GRUPOS_FUNCIONAIS, IdentidadeVisualEmpresaForm, UsuarioEmpresaCriacaoForm, UsuarioEmpresaVinculoForm
from .models import Empresa, UsuarioEmpresa
from .services import definir_empresa_na_sessao, empresas_do_usuario, usuario_administra_empresa


@login_required
def selecionar_empresa(request):
    empresas = list(empresas_do_usuario(request.user))
    if len(empresas) == 1:
        definir_empresa_na_sessao(request, empresas[0])
        return redirect('home')
    return render(request, 'empresas/selecionar.html', {'empresas': empresas})


@login_required
@require_POST
def trocar_empresa(request, empresa_id):
    empresa = Empresa.objects.filter(
        id=empresa_id,
        ativa=True,
        usuarios_vinculados__usuario=request.user,
        usuarios_vinculados__ativo=True,
    ).first()
    if not empresa:
        raise Http404
    if not definir_empresa_na_sessao(request, empresa):
        raise Http404
    return redirect('home')


@login_required
def identidade_visual(request):
    empresa = getattr(request, 'empresa', None)
    if not empresa:
        return redirect('selecionar_empresa')
    if not usuario_administra_empresa(request.user, empresa):
        return HttpResponseForbidden('Voce nao tem permissao para editar a identidade visual desta empresa.')

    if request.method == 'POST':
        form = IdentidadeVisualEmpresaForm(request.POST, request.FILES, instance=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Identidade visual atualizada com sucesso.')
            return redirect('identidade_visual_empresa')
    else:
        form = IdentidadeVisualEmpresaForm(instance=empresa)

    return render(request, 'empresas/identidade_visual.html', {'form': form, 'empresa': empresa})


def _exigir_admin_empresa(request):
    empresa = getattr(request, 'empresa', None)
    if not empresa:
        return None, redirect('selecionar_empresa')
    if not usuario_administra_empresa(request.user, empresa):
        return empresa, HttpResponseForbidden('Voce nao tem permissao para administrar esta empresa.')
    return empresa, None


def _garantir_grupos_funcionais():
    for nome in GRUPOS_FUNCIONAIS:
        Group.objects.get_or_create(name=nome)


def _deixaria_sem_admin(vinculo, novo_ativo=None, novo_admin=None):
    ativo = vinculo.ativo if novo_ativo is None else novo_ativo
    admin = vinculo.administrador_empresa if novo_admin is None else novo_admin
    if ativo and admin:
        return False
    return not UsuarioEmpresa.objects.filter(
        empresa=vinculo.empresa,
        ativo=True,
        administrador_empresa=True,
    ).exclude(pk=vinculo.pk).exists()


@login_required
def usuarios_empresa(request):
    empresa, bloqueio = _exigir_admin_empresa(request)
    if bloqueio:
        return bloqueio
    vinculos = (
        UsuarioEmpresa.objects.filter(empresa=empresa)
        .select_related('usuario', 'grupo')
        .prefetch_related('obras_permitidas')
        .order_by('-ativo', 'usuario__first_name', 'usuario__username')
    )
    return render(request, 'empresas/usuarios_empresa.html', {'empresa': empresa, 'vinculos': vinculos})


@login_required
def novo_usuario_empresa(request):
    empresa, bloqueio = _exigir_admin_empresa(request)
    if bloqueio:
        return bloqueio
    _garantir_grupos_funcionais()
    if request.method == 'POST':
        form = UsuarioEmpresaCriacaoForm(request.POST, empresa=empresa)
        if form.is_valid():
            vinculo = form.save()
            messages.success(request, f'Usuario {vinculo.usuario.username} criado para {empresa.nome}.')
            return redirect('usuarios_empresa')
    else:
        form = UsuarioEmpresaCriacaoForm(empresa=empresa)
    return render(
        request,
        'empresas/form_usuario_empresa.html',
        {
            'empresa': empresa,
            'form': form,
            'titulo': 'Novo usuario',
            'modo': 'novo',
        },
    )


@login_required
def editar_usuario_empresa(request, vinculo_id):
    empresa, bloqueio = _exigir_admin_empresa(request)
    if bloqueio:
        return bloqueio
    _garantir_grupos_funcionais()
    vinculo = get_object_or_404(
        UsuarioEmpresa.objects.select_related('usuario', 'grupo').prefetch_related('obras_permitidas'),
        pk=vinculo_id,
        empresa=empresa,
    )
    if request.method == 'POST':
        form = UsuarioEmpresaVinculoForm(request.POST, instance=vinculo, empresa=empresa)
        if form.is_valid():
            if _deixaria_sem_admin(
                vinculo,
                novo_ativo=form.cleaned_data.get('ativo'),
                novo_admin=form.cleaned_data.get('administrador_empresa'),
            ):
                form.add_error(None, 'A empresa precisa manter pelo menos um administrador ativo.')
            else:
                form.save()
                messages.success(request, 'Vinculo do usuario atualizado com sucesso.')
                return redirect('usuarios_empresa')
    else:
        form = UsuarioEmpresaVinculoForm(instance=vinculo, empresa=empresa)
    return render(
        request,
        'empresas/form_usuario_empresa.html',
        {
            'empresa': empresa,
            'form': form,
            'titulo': 'Editar usuario',
            'modo': 'editar',
            'vinculo': vinculo,
        },
    )


@login_required
@require_POST
def alternar_status_usuario_empresa(request, vinculo_id):
    empresa, bloqueio = _exigir_admin_empresa(request)
    if bloqueio:
        return bloqueio
    vinculo = get_object_or_404(UsuarioEmpresa, pk=vinculo_id, empresa=empresa)
    novo_status = not vinculo.ativo
    if _deixaria_sem_admin(vinculo, novo_ativo=novo_status):
        messages.error(request, 'A empresa precisa manter pelo menos um administrador ativo.')
        return redirect('usuarios_empresa')
    vinculo.ativo = novo_status
    vinculo.save(update_fields=['ativo'])
    messages.success(request, 'Status do usuario nesta empresa atualizado.')
    return redirect('usuarios_empresa')
