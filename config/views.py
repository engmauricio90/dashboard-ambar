from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.static import serve


def _normalized_media_path(path):
    return str(path or '').replace('\\', '/').lstrip('/')


def _usuario_pode_acessar_media(request, path):
    normalized_path = _normalized_media_path(path)
    empresa = getattr(request, 'empresa', None)

    if not normalized_path:
        return False

    if empresa:
        for field_name in ['logo', 'cabecalho_documentos', 'rodape_documentos']:
            field = getattr(empresa, field_name, None)
            if field and _normalized_media_path(field.name) == normalized_path:
                return True

    if getattr(request.user, 'is_authenticated', False):
        perfil = getattr(request.user, 'perfil', None)
        if perfil and perfil.avatar and _normalized_media_path(perfil.avatar.name) == normalized_path:
            return True

    if not empresa:
        return False

    from diarios.models import FotoDiario
    from propostas.models import Proposta

    if FotoDiario.objects.filter(imagem=normalized_path, diario__obra__empresa=empresa).exists():
        return True

    if Proposta.objects.filter(planilha_imagem=normalized_path, empresa=empresa).exists():
        return True

    return False


@login_required
def protected_media(request, path):
    if not _usuario_pode_acessar_media(request, path):
        raise Http404
    return serve(request, path, document_root=settings.MEDIA_ROOT)
