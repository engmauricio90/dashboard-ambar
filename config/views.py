from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.static import serve


@login_required
def protected_media(request, path):
    return serve(request, path, document_root=settings.MEDIA_ROOT)
