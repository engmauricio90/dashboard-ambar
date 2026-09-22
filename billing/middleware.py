from django.shortcuts import redirect
from django.urls import reverse

from .services.entitlements import empresa_tem_acesso


class BillingAccessMiddleware:
    EXEMPT_PREFIXES = (
        '/admin/',
        '/billing/',
        '/empresas/selecionar/',
        '/login/',
        '/logout/',
        '/media/',
        '/plataforma/',
        '/privacidade/',
        '/senha/',
        '/social-media/',
        '/static/',
        '/termos/',
        '/healthz/',
        '/internal/social-automation/tick/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._deve_bloquear(request):
            return redirect(reverse('billing:assinatura_pendente'))
        return self.get_response(request)

    def _deve_bloquear(self, request):
        user = getattr(request, 'user', None)
        if not getattr(user, 'is_authenticated', False):
            return False
        if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
            return False
        path = request.path or ''
        if path == '/':
            return False
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return False
        empresa = getattr(request, 'empresa', None)
        if empresa is None:
            return False
        return not empresa_tem_acesso(empresa)
