from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Group
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from config.permissions import user_in_groups

from .forms import MeuPerfilForm, PerfilUsuarioForm, UsuarioForm
from .models import PerfilUsuario


User = get_user_model()
GRUPOS_PADRAO = ['Administrador', 'Diretoria', 'Financeiro', 'Engenharia', 'Compras', 'Administrativo', 'Obras', 'Consulta']


def _pode_administrar_usuarios(user):
    return user.is_superuser or user_in_groups(user, ('Administrador',))


def _perfil(user):
    perfil, _created = PerfilUsuario.objects.get_or_create(user=user)
    return perfil


def _garantir_grupos_padrao():
    for nome in GRUPOS_PADRAO:
        Group.objects.get_or_create(name=nome)


@login_required
def minha_area(request):
    perfil = _perfil(request.user)
    return render(
        request,
        'usuarios/minha_area.html',
        {
            'perfil': perfil,
            'obras': perfil.obras.all(),
            'grupos': request.user.groups.order_by('name'),
            'pode_administrar_usuarios': _pode_administrar_usuarios(request.user),
        },
    )


@login_required
def editar_meu_perfil(request):
    perfil = _perfil(request.user)
    if request.method == 'POST':
        form = MeuPerfilForm(request.POST, request.FILES, instance=perfil)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil atualizado com sucesso.')
            return redirect('minha_area')
    else:
        form = MeuPerfilForm(instance=perfil)
    return render(request, 'usuarios/form_meu_perfil.html', {'form': form})


@login_required
def alterar_minha_senha(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Senha alterada com sucesso.')
            return redirect('minha_area')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'usuarios/form_alterar_senha.html', {'form': form})


@login_required
def lista_usuarios(request):
    if not _pode_administrar_usuarios(request.user):
        messages.error(request, 'Voce nao tem permissao para administrar usuarios.')
        return redirect('minha_area')
    _garantir_grupos_padrao()
    busca = request.GET.get('busca', '').strip()
    for usuario_sem_perfil in User.objects.filter(perfil__isnull=True):
        PerfilUsuario.objects.get_or_create(user=usuario_sem_perfil)
    usuarios = User.objects.select_related('perfil').prefetch_related('groups', 'perfil__obras').order_by('first_name', 'username')
    if busca:
        usuarios = usuarios.filter(
            Q(username__icontains=busca)
            | Q(first_name__icontains=busca)
            | Q(last_name__icontains=busca)
            | Q(email__icontains=busca)
        )
    return render(
        request,
        'usuarios/lista_usuarios.html',
        {
            'usuarios': usuarios,
            'busca': busca,
        },
    )


@login_required
def novo_usuario(request):
    if not _pode_administrar_usuarios(request.user):
        messages.error(request, 'Voce nao tem permissao para criar usuarios.')
        return redirect('minha_area')
    _garantir_grupos_padrao()
    if request.method == 'POST':
        user_form = UsuarioForm(request.POST)
        perfil_form = PerfilUsuarioForm(request.POST, request.FILES)
        if user_form.is_valid() and perfil_form.is_valid():
            user = user_form.save()
            perfil = perfil_form.save(commit=False)
            perfil.user = user
            perfil.save()
            perfil_form.save_m2m()
            messages.success(request, 'Usuario criado com sucesso.')
            return redirect('lista_usuarios')
    else:
        user_form = UsuarioForm()
        perfil_form = PerfilUsuarioForm()
    return render(
        request,
        'usuarios/form_usuario.html',
        {
            'titulo': 'Novo usuario',
            'user_form': user_form,
            'perfil_form': perfil_form,
        },
    )


@login_required
def editar_usuario(request, user_id):
    if not _pode_administrar_usuarios(request.user):
        messages.error(request, 'Voce nao tem permissao para editar usuarios.')
        return redirect('minha_area')
    _garantir_grupos_padrao()
    usuario = get_object_or_404(User, id=user_id)
    perfil = _perfil(usuario)
    if request.method == 'POST':
        user_form = UsuarioForm(request.POST, instance=usuario)
        perfil_form = PerfilUsuarioForm(request.POST, request.FILES, instance=perfil)
        if user_form.is_valid() and perfil_form.is_valid():
            user_form.save()
            perfil_form.save()
            messages.success(request, 'Usuario atualizado com sucesso.')
            return redirect('lista_usuarios')
    else:
        user_form = UsuarioForm(instance=usuario)
        perfil_form = PerfilUsuarioForm(instance=perfil)
    return render(
        request,
        'usuarios/form_usuario.html',
        {
            'titulo': 'Editar usuario',
            'usuario_editado': usuario,
            'user_form': user_form,
            'perfil_form': perfil_form,
        },
    )


@login_required
def alternar_status_usuario(request, user_id):
    if not _pode_administrar_usuarios(request.user):
        messages.error(request, 'Voce nao tem permissao para alterar usuarios.')
        return redirect('minha_area')
    usuario = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        if usuario == request.user:
            messages.error(request, 'Voce nao pode inativar o proprio usuario.')
        else:
            usuario.is_active = not usuario.is_active
            usuario.save(update_fields=['is_active'])
            messages.success(request, 'Status do usuario atualizado.')
    return redirect('lista_usuarios')
