from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib import messages
from django.http import Http404, HttpResponseForbidden
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import (
    GRUPOS_FUNCIONAIS,
    ClientePlataformaForm,
    IdentidadeVisualEmpresaForm,
    OnboardingClienteForm,
    UsuarioEmpresaCriacaoForm,
    UsuarioEmpresaVinculoForm,
)
from .emails import enviar_acesso_usuario_empresa, enviar_convite_usuario_empresa
from .models import Empresa, UsuarioEmpresa
from .services import criar_cliente_assistido, definir_empresa_na_sessao, empresas_do_usuario, usuario_administra_empresa


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


def _exigir_operador_plataforma(request):
    if request.user.is_superuser or request.user.is_staff:
        return None
    return HttpResponseForbidden('Voce nao tem permissao para acessar a area da plataforma.')


def _enviar_email_acesso_ou_convite(request, vinculo, usuario_criado=False):
    if not vinculo.usuario.email:
        return 'sem_email'
    if usuario_criado or not vinculo.usuario.has_usable_password():
        return 'enviado' if enviar_convite_usuario_empresa(request, vinculo) else 'falha'
    return 'enviado' if enviar_acesso_usuario_empresa(request, vinculo) else 'falha'


def _checklist_cliente(empresa):
    return {
        'empresa_criada': True,
        'primeiro_admin': UsuarioEmpresa.objects.filter(empresa=empresa, ativo=True, administrador_empresa=True).exists(),
        'identidade_configurada': bool(empresa.logo or empresa.cor_primaria or empresa.razao_social or empresa.cnpj),
        'primeira_obra': empresa.obras.exists(),
        'outros_usuarios': UsuarioEmpresa.objects.filter(empresa=empresa).count() > 1,
    }


@login_required
def clientes_plataforma(request):
    bloqueio = _exigir_operador_plataforma(request)
    if bloqueio:
        return bloqueio
    busca = request.GET.get('busca', '').strip()
    empresas = Empresa.objects.annotate(
        total_usuarios=Count('usuarios_vinculados', distinct=True),
        total_obras=Count('obras', distinct=True),
        convites_pendentes=Count(
            'usuarios_vinculados',
            filter=Q(usuarios_vinculados__ativo=True, usuarios_vinculados__usuario__password__startswith='!'),
            distinct=True,
        ),
    ).order_by('nome')
    if busca:
        empresas = empresas.filter(
            Q(nome__icontains=busca)
            | Q(razao_social__icontains=busca)
            | Q(cnpj__icontains=busca)
            | Q(email__icontains=busca)
        )
    return render(request, 'empresas/plataforma/clientes.html', {'empresas': empresas, 'busca': busca})


@login_required
def novo_cliente_plataforma(request):
    bloqueio = _exigir_operador_plataforma(request)
    if bloqueio:
        return bloqueio
    _garantir_grupos_funcionais()
    if request.method == 'POST':
        form = OnboardingClienteForm(request.POST)
        if form.is_valid():
            dados = form.cleaned_data.copy()
            dados['usuario_existente'] = form.usuario_existente
            resultado = criar_cliente_assistido(dados)
            status_convite = _enviar_email_acesso_ou_convite(
                request,
                resultado['vinculo'],
                usuario_criado=resultado['usuario_criado'],
            )
            if status_convite == 'enviado':
                messages.success(request, 'Cliente criado e convite enviado com sucesso.')
            elif status_convite == 'sem_email':
                messages.warning(request, 'Cliente criado, mas o administrador nao possui e-mail para convite.')
            else:
                messages.warning(request, 'Cliente criado, mas nao foi possivel enviar o convite.')
            return redirect(f"{reverse('detalhe_cliente_plataforma', args=[resultado['empresa'].id])}?convite={status_convite}")
    else:
        form = OnboardingClienteForm()
    return render(request, 'empresas/plataforma/form_cliente.html', {'form': form, 'titulo': 'Novo cliente'})


@login_required
def detalhe_cliente_plataforma(request, empresa_id):
    bloqueio = _exigir_operador_plataforma(request)
    if bloqueio:
        return bloqueio
    empresa = get_object_or_404(
        Empresa.objects.annotate(total_obras=Count('obras', distinct=True), total_usuarios=Count('usuarios_vinculados', distinct=True)),
        pk=empresa_id,
    )
    vinculos = (
        UsuarioEmpresa.objects.filter(empresa=empresa)
        .select_related('usuario', 'grupo')
        .prefetch_related('obras_permitidas')
        .order_by('-administrador_empresa', '-ativo', 'usuario__first_name', 'usuario__username')
    )
    return render(
        request,
        'empresas/plataforma/detalhe_cliente.html',
        {
            'empresa': empresa,
            'vinculos': vinculos,
            'checklist': _checklist_cliente(empresa),
            'status_convite': request.GET.get('convite', ''),
        },
    )


@login_required
def editar_cliente_plataforma(request, empresa_id):
    bloqueio = _exigir_operador_plataforma(request)
    if bloqueio:
        return bloqueio
    empresa = get_object_or_404(Empresa, pk=empresa_id)
    if request.method == 'POST':
        form = ClientePlataformaForm(request.POST, instance=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, 'Dados do cliente atualizados com sucesso.')
            return redirect('detalhe_cliente_plataforma', empresa_id=empresa.id)
    else:
        form = ClientePlataformaForm(instance=empresa)
    return render(request, 'empresas/plataforma/form_cliente.html', {'form': form, 'titulo': 'Editar cliente', 'empresa': empresa})


@login_required
@require_POST
def reenviar_convite_plataforma(request, vinculo_id):
    bloqueio = _exigir_operador_plataforma(request)
    if bloqueio:
        return bloqueio
    vinculo = get_object_or_404(UsuarioEmpresa.objects.select_related('usuario', 'empresa'), pk=vinculo_id)
    if not vinculo.ativo:
        messages.error(request, 'Nao e possivel reenviar convite para usuario inativo.')
        return redirect('detalhe_cliente_plataforma', empresa_id=vinculo.empresa_id)
    if not vinculo.usuario.email:
        messages.error(request, 'Este usuario nao possui e-mail cadastrado.')
        return redirect('detalhe_cliente_plataforma', empresa_id=vinculo.empresa_id)
    if vinculo.usuario.has_usable_password():
        messages.info(request, 'Este usuario ja possui senha definida.')
        return redirect('detalhe_cliente_plataforma', empresa_id=vinculo.empresa_id)
    if enviar_convite_usuario_empresa(request, vinculo):
        messages.success(request, 'Convite reenviado com sucesso.')
    else:
        messages.warning(request, 'Nao foi possivel reenviar o convite agora.')
    return redirect('detalhe_cliente_plataforma', empresa_id=vinculo.empresa_id)


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
            vinculo, usuario_criado = form.save()
            if not vinculo.usuario.email:
                messages.warning(request, 'Usuario vinculado, mas sem e-mail para envio de convite.')
            elif usuario_criado or not vinculo.usuario.has_usable_password():
                if enviar_convite_usuario_empresa(request, vinculo):
                    messages.success(request, f'Convite enviado para {vinculo.usuario.email}.')
                else:
                    messages.warning(request, 'Usuario vinculado, mas nao foi possivel enviar o convite agora. Tente reenviar depois.')
            else:
                if enviar_acesso_usuario_empresa(request, vinculo):
                    messages.success(request, f'Acesso liberado e comunicado para {vinculo.usuario.email}.')
                else:
                    messages.warning(request, 'Usuario vinculado, mas nao foi possivel enviar o aviso de acesso agora.')
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


@login_required
@require_POST
def reenviar_convite_usuario_empresa(request, vinculo_id):
    empresa, bloqueio = _exigir_admin_empresa(request)
    if bloqueio:
        return bloqueio
    vinculo = get_object_or_404(UsuarioEmpresa.objects.select_related('usuario', 'empresa'), pk=vinculo_id, empresa=empresa)
    if not vinculo.ativo:
        messages.error(request, 'Nao e possivel reenviar convite para usuario inativo nesta empresa.')
        return redirect('usuarios_empresa')
    if not vinculo.usuario.email:
        messages.error(request, 'Este usuario nao possui e-mail cadastrado para convite.')
        return redirect('usuarios_empresa')
    if vinculo.usuario.has_usable_password():
        messages.info(request, 'Este usuario ja possui senha definida. Use o fluxo de acesso normal.')
        return redirect('usuarios_empresa')
    if enviar_convite_usuario_empresa(request, vinculo):
        messages.success(request, 'Convite reenviado com sucesso.')
    else:
        messages.warning(request, 'Nao foi possivel reenviar o convite agora. Verifique a configuracao de e-mail.')
    return redirect('usuarios_empresa')
