from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def empresa_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not getattr(request.user, 'is_authenticated', False):
            return HttpResponseForbidden('Empresa ativa indisponivel.')
        if getattr(request, 'empresa', None) is None:
            if len(getattr(request, 'empresas_disponiveis', [])) > 1:
                return redirect('selecionar_empresa')
            return HttpResponseForbidden('Empresa ativa indisponivel.')
        return view_func(request, *args, **kwargs)

    return wrapper
