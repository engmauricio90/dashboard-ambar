from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def user_in_groups(user, group_names):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


def group_required(*group_names):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if user_in_groups(request.user, group_names):
                return view_func(request, *args, **kwargs)
            messages.error(request, 'Voce nao tem permissao para acessar este modulo.')
            return redirect('home')

        return wrapped

    return decorator
