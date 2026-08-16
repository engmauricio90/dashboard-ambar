from .services import empresa_ativa_do_request, empresas_do_usuario


class EmpresaAtivaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.empresas_disponiveis = list(empresas_do_usuario(request.user))
        request.empresa = empresa_ativa_do_request(request)
        request.usuario_multiempresa = len(request.empresas_disponiveis) > 1
        return self.get_response(request)
