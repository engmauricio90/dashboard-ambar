from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import IdentidadeVisualEmpresaForm
from .models import Empresa
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
