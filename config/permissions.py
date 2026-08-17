from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def user_in_groups(user, group_names):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


def user_in_groups_for_empresa(user, group_names, empresa):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if empresa is not None:
        from empresas.models import UsuarioEmpresa

        vinculo = (
            UsuarioEmpresa.objects.filter(usuario=user, empresa=empresa, ativo=True, empresa__ativa=True)
            .select_related('grupo')
            .first()
        )
        if vinculo and vinculo.grupo_id:
            return vinculo.grupo.name in group_names
    return user_in_groups(user, group_names)


def group_required(*group_names):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if user_in_groups_for_empresa(request.user, group_names, getattr(request, 'empresa', None)):
                return view_func(request, *args, **kwargs)
            messages.error(request, 'Voce nao tem permissao para acessar este modulo.')
            return redirect('home')

        return wrapped

    return decorator
