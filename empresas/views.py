from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import Empresa
from .services import definir_empresa_na_sessao, empresas_do_usuario


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
