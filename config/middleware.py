from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not self._is_exempt_path(request.path):
            login_url = reverse(settings.LOGIN_URL)
            return redirect(f'{login_url}?next={request.get_full_path()}')
        return self.get_response(request)

    def _is_exempt_path(self, path):
        exempt_prefixes = (
            reverse(settings.LOGIN_URL),
            reverse('logout'),
            reverse('healthz'),
            '/admin/',
            settings.STATIC_URL,
            settings.MEDIA_URL,
        )
        return any(path.startswith(prefix) for prefix in exempt_prefixes)
