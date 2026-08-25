import logging
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .ai import OpenAINotConfigured, OpenAIUnavailable
from .automation import automacao_status_profile, executar_tick_social
from .forms import SocialBaseImageForm, SocialContentForm, SocialGenerateForm, SocialProfileForm, SocialScheduleForm
from .generation import gerar_lote_conteudos
from .instagram import (
    InstagramAPIError,
    InstagramConfigurationError,
    InstagramContainerPending,
    InstagramPublishError,
    obter_conta_instagram,
    publicar_conteudo_instagram,
    validar_assinatura_midia_meta,
    validar_assinatura_video_meta,
    validar_token_midia_temporaria,
)
from .models import SocialBaseImage, SocialContent, SocialProfile
from .rendering import SocialRenderError, renderizar_midia_social
from .services import (
    agendar_conteudo,
    aprovar_conteudo,
    criar_evento_criacao,
    desagendar_conteudo,
    registrar_edicao,
    rejeitar_conteudo,
    restaurar_rascunho,
)


logger = logging.getLogger(__name__)


def staff_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.is_staff or request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        return HttpResponseForbidden('Voce nao tem permissao para acessar a area de automacao social.')

    return wrapped


def _paginate(request, queryset, per_page=25):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get('page'))


def _content_queryset():
    return SocialContent.objects.select_related('profile', 'base_image')


def _profile_or_404(profile_id):
    return get_object_or_404(SocialProfile, pk=profile_id)


def _handle_validation_error(request, exc):
    messages.error(request, '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc))


@staff_required
def home(request):
    contexto = {
        'perfis_ativos': SocialProfile.objects.filter(ativo=True).count(),
        'rascunhos': SocialContent.objects.filter(status=SocialContent.Status.RASCUNHO).count(),
        'agendados': SocialContent.objects.filter(status=SocialContent.Status.AGENDADO).count(),
        'erros': SocialContent.objects.filter(status=SocialContent.Status.ERRO).count(),
        'perfis': SocialProfile.objects.annotate(total_fila=Count('contents')).order_by('nome')[:6],
    }
    return render(request, 'social_automation/home.html', contexto)


@staff_required
def profile_list(request):
    profiles = SocialProfile.objects.annotate(total_fila=Count('contents')).order_by('nome')
    return render(request, 'social_automation/profile_list.html', {'profiles': profiles})


@staff_required
def profile_create(request):
    if request.method == 'POST':
        form = SocialProfileForm(request.POST)
        if form.is_valid():
            profile = form.save()
            messages.success(request, 'Perfil social criado com sucesso.')
            return redirect('social_automation:profile_detail', profile_id=profile.id)
    else:
        form = SocialProfileForm()
    return render(request, 'social_automation/profile_form.html', {'form': form, 'titulo': 'Novo perfil social'})


@staff_required
def profile_update(request, profile_id):
    profile = _profile_or_404(profile_id)
    if request.method == 'POST':
        form = SocialProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil social atualizado com sucesso.')
            return redirect('social_automation:profile_detail', profile_id=profile.id)
    else:
        form = SocialProfileForm(instance=profile)
    return render(request, 'social_automation/profile_form.html', {'form': form, 'profile': profile, 'titulo': 'Editar perfil social'})


@staff_required
def profile_detail(request, profile_id):
    profile = _profile_or_404(profile_id)
    contents = profile.contents.select_related('base_image').order_by('-created_at')[:8]
    contexto = {
        'profile': profile,
        'total_imagens': profile.base_images.count(),
        'total_conteudos': profile.contents.count(),
        'rascunhos': profile.contents.filter(status=SocialContent.Status.RASCUNHO).count(),
        'agendados': profile.contents.filter(status=SocialContent.Status.AGENDADO).count(),
        'erros': profile.contents.filter(status=SocialContent.Status.ERRO).count(),
        'contents': contents,
        'instagram_configurado': bool(settings.INSTAGRAM_ACCESS_TOKEN and settings.INSTAGRAM_USER_ID),
        'automacao': automacao_status_profile(profile),
    }
    return render(request, 'social_automation/profile_detail.html', contexto)


@staff_required
@require_POST
def automation_run_now(request, profile_id=None):
    summary = executar_tick_social()
    if summary.get('status') == 'already_running':
        messages.warning(request, 'A automacao social ja esta em execucao.')
    else:
        total_publicados = sum(item.get('published', 0) for item in summary.get('profiles', []))
        total_agendados = sum(item.get('scheduled', 0) for item in summary.get('profiles', []))
        total_gerados = sum(item.get('generated', 0) for item in summary.get('profiles', []))
        messages.success(request, f'Automacao executada. Publicados: {total_publicados}. Agendados: {total_agendados}. Gerados: {total_gerados}.')
    if profile_id:
        return redirect('social_automation:profile_detail', profile_id=profile_id)
    return redirect('social_automation:home')


@csrf_exempt
@require_POST
def automation_tick_endpoint(request):
    secret = settings.SOCIAL_AUTOMATION_CRON_SECRET
    if not secret:
        return JsonResponse({'status': 'unavailable'}, status=503)
    authorization = request.headers.get('Authorization', '')
    expected = f'Bearer {secret}'
    if not secrets.compare_digest(authorization, expected):
        return JsonResponse({'status': 'forbidden'}, status=403)
    return JsonResponse(executar_tick_social())


@staff_required
@require_POST
def profile_toggle(request, profile_id):
    profile = _profile_or_404(profile_id)
    profile.ativo = not profile.ativo
    profile.save(update_fields=['ativo', 'updated_at'])
    messages.success(request, 'Status do perfil atualizado.')
    return redirect('social_automation:profile_list')


@staff_required
def image_list(request, profile_id):
    profile = _profile_or_404(profile_id)
    images = profile.base_images.all()
    page_obj = _paginate(request, images, 24)
    return render(request, 'social_automation/image_list.html', {'profile': profile, 'page_obj': page_obj})


@staff_required
def image_create(request, profile_id):
    profile = _profile_or_404(profile_id)
    if request.method == 'POST':
        form = SocialBaseImageForm(request.POST, request.FILES)
        if form.is_valid():
            image = form.save(commit=False)
            image.profile = profile
            image.save()
            messages.success(request, 'Imagem-base adicionada com sucesso.')
            return redirect('social_automation:image_list', profile_id=profile.id)
    else:
        form = SocialBaseImageForm()
    return render(request, 'social_automation/image_form.html', {'form': form, 'profile': profile})


@staff_required
def image_update(request, image_id):
    image = get_object_or_404(SocialBaseImage.objects.select_related('profile'), pk=image_id)
    if request.method == 'POST':
        form = SocialBaseImageForm(request.POST, request.FILES, instance=image)
        if form.is_valid():
            form.save()
            messages.success(request, 'Imagem-base atualizada com sucesso.')
            return redirect('social_automation:image_list', profile_id=image.profile_id)
    else:
        form = SocialBaseImageForm(instance=image)
    return render(request, 'social_automation/image_form.html', {'form': form, 'profile': image.profile, 'image': image})


@staff_required
@require_POST
def image_toggle(request, image_id):
    image = get_object_or_404(SocialBaseImage.objects.select_related('profile'), pk=image_id)
    image.ativa = not image.ativa
    image.save(update_fields=['ativa', 'updated_at'])
    messages.success(request, 'Status da imagem atualizado.')
    return redirect('social_automation:image_list', profile_id=image.profile_id)


@staff_required
def content_list(request, profile_id=None):
    profile = _profile_or_404(profile_id) if profile_id else None
    queryset = _content_queryset()
    if profile:
        queryset = queryset.filter(profile=profile)

    filtros = {
        'profile': request.GET.get('profile', ''),
        'status': request.GET.get('status', ''),
        'busca': request.GET.get('busca', '').strip(),
        'ordenacao': request.GET.get('ordenacao', 'recentes'),
    }
    if filtros['profile'] and not profile:
        queryset = queryset.filter(profile_id=filtros['profile'])
    if filtros['status']:
        queryset = queryset.filter(status=filtros['status'])
    if filtros['busca']:
        queryset = queryset.filter(Q(frase__icontains=filtros['busca']) | Q(legenda__icontains=filtros['busca']))

    ordenacoes = {
        'recentes': '-created_at',
        'antigos': 'created_at',
        'agendamento': 'scheduled_at',
    }
    queryset = queryset.order_by(ordenacoes.get(filtros['ordenacao'], '-created_at'), '-id')
    page_obj = _paginate(request, queryset, 25)
    return render(
        request,
        'social_automation/content_list.html',
        {
            'profile': profile,
            'page_obj': page_obj,
            'profiles': SocialProfile.objects.order_by('nome'),
            'status_choices': SocialContent.Status.choices,
            'filtros': filtros,
        },
    )


@staff_required
def content_create(request, profile_id=None):
    profile = _profile_or_404(profile_id) if profile_id else None
    if request.method == 'POST':
        form = SocialContentForm(request.POST, request.FILES, profile=profile)
        if form.is_valid():
            content = form.save()
            criar_evento_criacao(content, request.user)
            if content.base_image:
                try:
                    renderizar_midia_social(content)
                except SocialRenderError as exc:
                    messages.warning(request, f'Rascunho salvo, mas o card final nao foi renderizado: {exc}')
            messages.success(request, 'Rascunho criado com sucesso.')
            return redirect('social_automation:content_detail', content_id=content.id)
    else:
        form = SocialContentForm(profile=profile)
    return render(request, 'social_automation/content_form.html', {'form': form, 'profile': profile, 'titulo': 'Novo rascunho'})


@staff_required
def content_update(request, content_id):
    content = get_object_or_404(_content_queryset(), pk=content_id)
    if not content.pode_editar_operacionalmente:
        messages.error(request, 'Este conteudo nao pode ser editado pela interface operacional.')
        return redirect('social_automation:content_detail', content_id=content.id)
    if request.method == 'POST':
        frase_original = content.frase
        base_image_original_id = content.base_image_id
        form = SocialContentForm(request.POST, request.FILES, instance=content)
        if form.is_valid():
            content = form.save()
            registrar_edicao(content, request.user)
            if content.base_image and (content.frase != frase_original or content.base_image_id != base_image_original_id):
                try:
                    renderizar_midia_social(content)
                    messages.success(request, 'Conteudo atualizado e card renderizado novamente.')
                except SocialRenderError as exc:
                    messages.warning(request, f'Conteudo atualizado, mas o card final nao foi renderizado: {exc}')
                    return redirect('social_automation:content_detail', content_id=content.id)
            else:
                messages.success(request, 'Conteudo atualizado com sucesso.')
            return redirect('social_automation:content_detail', content_id=content.id)
    else:
        form = SocialContentForm(instance=content)
    return render(request, 'social_automation/content_form.html', {'form': form, 'content': content, 'titulo': 'Editar conteudo'})


@staff_required
def content_detail(request, content_id):
    content = get_object_or_404(_content_queryset(), pk=content_id)
    schedule_form = SocialScheduleForm(profile=content.profile) if content.status == SocialContent.Status.APROVADO else None
    events = content.events.select_related('usuario')[:20]
    return render(
        request,
        'social_automation/content_detail.html',
        {
            'content': content,
            'events': events,
            'schedule_form': schedule_form,
            'instagram_expected_username': settings.INSTAGRAM_EXPECTED_USERNAME or content.profile.username,
        },
    )


@staff_required
def profile_generate(request, profile_id):
    profile = _profile_or_404(profile_id)
    resultado = None
    if request.method == 'POST':
        form = SocialGenerateForm(request.POST)
        if form.is_valid():
            try:
                resultado = gerar_lote_conteudos(
                    profile=profile,
                    quantidade=form.cleaned_data['quantidade'],
                    tema=form.cleaned_data['tema'],
                    usuario=request.user,
                )
                if resultado.criados:
                    messages.success(request, f'{resultado.criados} conteudo(s) gerado(s) como rascunho.')
                if resultado.duplicados or resultado.bloqueados or resultado.falhas:
                    messages.warning(
                        request,
                        f'Ignorados: {resultado.duplicados} duplicado(s), {resultado.bloqueados} bloqueado(s), {resultado.falhas} falha(s).',
                    )
            except (OpenAINotConfigured, OpenAIUnavailable, ValidationError) as exc:
                _handle_validation_error(request, exc)
    else:
        form = SocialGenerateForm()
    return render(request, 'social_automation/generate_form.html', {'profile': profile, 'form': form, 'resultado': resultado})


@staff_required
@require_POST
def content_render(request, content_id):
    content = get_object_or_404(_content_queryset(), pk=content_id)
    try:
        renderizar_midia_social(content)
        messages.success(request, 'Midia renderizada novamente.')
    except SocialRenderError as exc:
        messages.error(request, str(exc))
    return redirect('social_automation:content_detail', content_id=content.id)


def public_final_image(request, token):
    if request.method not in {'GET', 'HEAD'}:
        return HttpResponseNotAllowed(['GET', 'HEAD'])
    try:
        content = validar_token_midia_temporaria(token)
    except ValidationError as exc:
        raise Http404 from exc
    if not content.final_image:
        raise Http404
    response = FileResponse(
        content.final_image.storage.open(content.final_image.name, 'rb'),
        content_type='image/jpeg',
        as_attachment=False,
        filename='instagram-card.jpg',
    )
    response['Cache-Control'] = 'private, max-age=0, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def ig_final_image(request, content_id, signature):
    if request.method not in {'GET', 'HEAD'}:
        return HttpResponseNotAllowed(['GET', 'HEAD'])
    try:
        content = validar_assinatura_midia_meta(content_id, signature)
    except ValidationError as exc:
        raise Http404 from exc
    if not content.final_image:
        raise Http404
    with content.final_image.storage.open(content.final_image.name, 'rb') as arquivo:
        image_bytes = arquivo.read()
    logger.info('signed_media_fetch content_id=%s method=%s bytes=%s', content.id, request.method, len(image_bytes))
    body = b'' if request.method == 'HEAD' else image_bytes
    response = HttpResponse(body, content_type='image/jpeg')
    response['Content-Length'] = str(len(image_bytes))
    response['Cache-Control'] = 'private, max-age=0, no-store'
    return response


def ig_final_video(request, content_id, signature):
    if request.method not in {'GET', 'HEAD'}:
        return HttpResponseNotAllowed(['GET', 'HEAD'])
    try:
        content = validar_assinatura_video_meta(content_id, signature)
    except ValidationError as exc:
        raise Http404 from exc
    if not content.final_video:
        raise Http404
    with content.final_video.storage.open(content.final_video.name, 'rb') as arquivo:
        video_bytes = arquivo.read()
    logger.info('signed_video_fetch content_id=%s method=%s bytes=%s', content.id, request.method, len(video_bytes))
    body = b'' if request.method == 'HEAD' else video_bytes
    response = HttpResponse(body, content_type='video/mp4')
    response['Content-Length'] = str(len(video_bytes))
    response['Cache-Control'] = 'private, max-age=0, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@staff_required
@require_POST
def content_publish_instagram(request, content_id):
    content = get_object_or_404(_content_queryset(), pk=content_id)
    try:
        publicar_conteudo_instagram(content, request.user)
        messages.success(request, 'Conteudo publicado no Instagram com sucesso.')
    except InstagramContainerPending as exc:
        messages.warning(request, str(exc))
    except (InstagramConfigurationError, InstagramAPIError, InstagramPublishError) as exc:
        messages.error(request, str(exc))
    return redirect('social_automation:content_detail', content_id=content.id)


@staff_required
def instagram_health(request, profile_id):
    profile = _profile_or_404(profile_id)
    try:
        conta = obter_conta_instagram()
        messages.success(request, f'Instagram conectado: @{conta.get("username") or "-"}')
    except (InstagramConfigurationError, InstagramAPIError) as exc:
        messages.error(request, str(exc))
    return redirect('social_automation:profile_detail', profile_id=profile.id)


@staff_required
@require_POST
def content_approve(request, content_id):
    content = get_object_or_404(SocialContent, pk=content_id)
    try:
        aprovar_conteudo(content, request.user)
        messages.success(request, 'Conteudo aprovado.')
    except ValidationError as exc:
        _handle_validation_error(request, exc)
    return redirect('social_automation:content_detail', content_id=content.id)


@staff_required
@require_POST
def content_reject(request, content_id):
    content = get_object_or_404(SocialContent, pk=content_id)
    try:
        rejeitar_conteudo(content, request.user)
        messages.success(request, 'Conteudo rejeitado.')
    except ValidationError as exc:
        _handle_validation_error(request, exc)
    return redirect('social_automation:content_detail', content_id=content.id)


@staff_required
@require_POST
def content_restore(request, content_id):
    content = get_object_or_404(SocialContent, pk=content_id)
    try:
        restaurar_rascunho(content, request.user)
        messages.success(request, 'Conteudo restaurado para rascunho.')
    except ValidationError as exc:
        _handle_validation_error(request, exc)
    return redirect('social_automation:content_detail', content_id=content.id)


@staff_required
@require_POST
def content_schedule(request, content_id):
    content = get_object_or_404(SocialContent.objects.select_related('profile'), pk=content_id)
    form = SocialScheduleForm(request.POST, profile=content.profile)
    if form.is_valid():
        try:
            agendar_conteudo(content, form.cleaned_data['scheduled_at'], request.user)
            messages.success(request, 'Conteudo agendado.')
        except ValidationError as exc:
            _handle_validation_error(request, exc)
    else:
        messages.error(request, 'Corrija a data e hora do agendamento.')
    return redirect('social_automation:content_detail', content_id=content.id)


@staff_required
@require_POST
def content_unschedule(request, content_id):
    content = get_object_or_404(SocialContent, pk=content_id)
    try:
        desagendar_conteudo(content, request.user)
        messages.success(request, 'Conteudo desagendado.')
    except ValidationError as exc:
        _handle_validation_error(request, exc)
    return redirect('social_automation:content_detail', content_id=content.id)


@staff_required
@require_POST
def content_delete(request, content_id):
    content = get_object_or_404(SocialContent, pk=content_id)
    if not content.pode_excluir_operacionalmente:
        messages.error(request, 'Este conteudo nao pode ser excluido pela interface operacional.')
        return redirect('social_automation:content_detail', content_id=content.id)
    content.delete()
    messages.success(request, 'Conteudo excluido.')
    return redirect('social_automation:content_list')


@staff_required
@require_POST
def content_bulk_approve(request):
    ids = request.POST.getlist('content_ids')
    aprovados = 0
    for content in SocialContent.objects.filter(id__in=ids, status=SocialContent.Status.RASCUNHO):
        try:
            aprovar_conteudo(content, request.user)
            aprovados += 1
        except ValidationError:
            continue
    messages.success(request, f'{aprovados} rascunho(s) aprovado(s).')
    return redirect(request.POST.get('next') or reverse('social_automation:content_list'))
