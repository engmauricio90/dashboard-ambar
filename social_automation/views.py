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
from .forms import (
    SocialAICarouselForm,
    SocialBaseImageForm,
    SocialCarouselSlideFormSet,
    SocialCarouselTemplateForm,
    SocialContentForm,
    SocialGenerateForm,
    SocialProfileForm,
    SocialScheduleForm,
    SocialVisualIdentityForm,
)
from .autonomous_carousel import gerar_carrossel_autonomo
from .image_analysis import analyze_social_image
from .image_generation import SocialImagePrompt, build_social_image_prompt, generate_social_image
from .generation import gerar_lote_conteudos
from .instagram import (
    InstagramAPIError,
    InstagramConfigurationError,
    InstagramContainerPending,
    InstagramPublishError,
    build_instagram_oauth_url,
    criar_ou_atualizar_conexao_instagram,
    exchange_instagram_code,
    obter_conta_instagram,
    publicar_conteudo_instagram,
    validar_conexao_instagram,
    validar_assinatura_midia_meta,
    validar_assinatura_carousel_slide_meta,
    validar_assinatura_video_meta,
    validar_token_midia_temporaria,
)
from .models import SocialBaseImage, SocialCarouselSlide, SocialCarouselTemplate, SocialContent, SocialInstagramConnection, SocialProfile, SocialVisualIdentity
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

CAROUSEL_LAYOUT_PREVIEWS = ['HERO_LEFT', 'HERO_RIGHT', 'TEXT_TOP', 'TEXT_BOTTOM', 'CENTER_CARD', 'SPLIT_LEFT', 'SPLIT_RIGHT', 'MINIMAL', 'FULL_TEXT']


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
    return SocialContent.objects.select_related('profile', 'base_image', 'carousel_template').prefetch_related('carousel_slides')


def _profile_or_404(profile_id):
    return get_object_or_404(SocialProfile, pk=profile_id)


def _handle_validation_error(request, exc):
    messages.error(request, '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc))


@staff_required
def home(request):
    perfis = list(SocialProfile.objects.annotate(total_fila=Count('contents')).order_by('nome')[:6])
    perfis_status = [(profile, automacao_status_profile(profile)) for profile in perfis]
    contexto = {
        'perfis_ativos': SocialProfile.objects.filter(ativo=True).count(),
        'rascunhos': SocialContent.objects.filter(status=SocialContent.Status.RASCUNHO).count(),
        'agendados': SocialContent.objects.filter(status=SocialContent.Status.AGENDADO).count(),
        'erros': SocialContent.objects.filter(status=SocialContent.Status.ERRO).count(),
        'perfis': perfis,
        'perfis_status': perfis_status,
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
def profile_visual_identity(request, profile_id):
    profile = _profile_or_404(profile_id)
    identity = profile.visual_identities.filter(is_default=True).first() or profile.visual_identities.first()
    if request.method == 'POST':
        form = SocialVisualIdentityForm(request.POST, request.FILES, instance=identity)
        if form.is_valid():
            identity = form.save(commit=False)
            identity.profile = profile
            identity.save()
            messages.success(request, 'Identidade visual atualizada com sucesso.')
            return redirect('social_automation:profile_detail', profile_id=profile.id)
    else:
        initial = {'brand_name': profile.nome}
        form = SocialVisualIdentityForm(instance=identity, initial=initial)
    return render(request, 'social_automation/profile_visual_identity_form.html', {'form': form, 'profile': profile})


@staff_required
def profile_detail(request, profile_id):
    profile = _profile_or_404(profile_id)
    instagram_connection = getattr(profile, 'instagram_connection', None)
    contents = profile.contents.select_related('base_image').order_by('-created_at')[:8]
    contexto = {
        'profile': profile,
        'total_imagens': profile.base_images.count(),
        'total_conteudos': profile.contents.count(),
        'rascunhos': profile.contents.filter(status=SocialContent.Status.RASCUNHO).count(),
        'agendados': profile.contents.filter(status=SocialContent.Status.AGENDADO).count(),
        'erros': profile.contents.filter(status=SocialContent.Status.ERRO).count(),
        'contents': contents,
        'instagram_connection': instagram_connection,
        'instagram_configurado': bool(instagram_connection and instagram_connection.is_active),
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
def carousel_template_list(request, profile_id):
    profile = _profile_or_404(profile_id)
    templates = profile.carousel_templates.order_by('-is_default', 'name')
    return render(request, 'social_automation/carousel_template_list.html', {'profile': profile, 'templates': templates})


@staff_required
def carousel_template_create(request, profile_id):
    profile = _profile_or_404(profile_id)
    if request.method == 'POST':
        form = SocialCarouselTemplateForm(request.POST, request.FILES)
        if form.is_valid():
            template = form.save(commit=False)
            template.profile = profile
            template.save()
            messages.success(request, 'Template de carrossel criado com sucesso.')
            return redirect('social_automation:carousel_template_list', profile_id=profile.id)
    else:
        form = SocialCarouselTemplateForm()
    return render(
        request,
        'social_automation/carousel_template_form.html',
        {'form': form, 'profile': profile, 'titulo': 'Novo template de carrossel', 'layout_previews': CAROUSEL_LAYOUT_PREVIEWS},
    )


@staff_required
def carousel_template_update(request, template_id):
    template = get_object_or_404(SocialCarouselTemplate.objects.select_related('profile'), pk=template_id)
    if request.method == 'POST':
        form = SocialCarouselTemplateForm(request.POST, request.FILES, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, 'Template de carrossel atualizado com sucesso.')
            return redirect('social_automation:carousel_template_list', profile_id=template.profile_id)
    else:
        form = SocialCarouselTemplateForm(instance=template)
    return render(
        request,
        'social_automation/carousel_template_form.html',
        {'form': form, 'profile': template.profile, 'template': template, 'titulo': 'Editar template de carrossel', 'layout_previews': CAROUSEL_LAYOUT_PREVIEWS},
    )


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
            slide_formset = SocialCarouselSlideFormSet(request.POST, request.FILES, instance=content)
            if content.is_carousel and not slide_formset.is_valid():
                content.delete()
                return render(request, 'social_automation/content_form.html', {'form': form, 'slide_formset': slide_formset, 'profile': profile, 'titulo': 'Novo rascunho'})
            if content.is_carousel:
                slide_formset.save()
            criar_evento_criacao(content, request.user)
            if content.is_carousel or content.base_image:
                try:
                    renderizar_midia_social(content)
                except SocialRenderError as exc:
                    if content.is_reel:
                        logger.warning('reel_render_ui_error content_id=%s exception_class=%s message=%s', content.id, type(exc).__name__, str(exc)[:180])
                        messages.warning(request, 'Rascunho salvo, mas nao foi possivel gerar o Reel. Verifique os logs ou tente novamente.')
                    else:
                        messages.warning(request, f'Rascunho salvo, mas o card final nao foi renderizado: {exc}')
            messages.success(request, 'Rascunho criado com sucesso.')
            return redirect('social_automation:content_detail', content_id=content.id)
    else:
        form = SocialContentForm(profile=profile)
        slide_formset = SocialCarouselSlideFormSet()
    return render(request, 'social_automation/content_form.html', {'form': form, 'slide_formset': slide_formset, 'profile': profile, 'titulo': 'Novo rascunho'})


@staff_required
def content_update(request, content_id):
    content = get_object_or_404(_content_queryset(), pk=content_id)
    if not content.pode_editar_operacionalmente:
        messages.error(request, 'Este conteudo nao pode ser editado pela interface operacional.')
        return redirect('social_automation:content_detail', content_id=content.id)
    if request.method == 'POST':
        frase_original = content.frase
        base_image_original_id = content.base_image_id
        template_original_id = content.carousel_template_id
        form = SocialContentForm(request.POST, request.FILES, instance=content)
        slide_formset = SocialCarouselSlideFormSet(request.POST, request.FILES, instance=content)
        if form.is_valid() and (form.cleaned_data.get('media_type') != SocialContent.MediaType.CAROUSEL or slide_formset.is_valid()):
            content = form.save()
            if content.is_carousel:
                slide_formset.save()
            registrar_edicao(content, request.user)
            should_render = content.is_carousel or (
                content.base_image and (content.frase != frase_original or content.base_image_id != base_image_original_id)
            )
            if content.is_carousel and content.carousel_template_id == template_original_id and content.frase == frase_original:
                should_render = True
            if should_render:
                try:
                    renderizar_midia_social(content)
                    messages.success(request, 'Conteudo atualizado e card renderizado novamente.')
                except SocialRenderError as exc:
                    if content.is_reel:
                        logger.warning('reel_render_ui_error content_id=%s exception_class=%s message=%s', content.id, type(exc).__name__, str(exc)[:180])
                        messages.warning(request, 'Conteudo atualizado, mas nao foi possivel gerar o Reel. Verifique os logs ou tente novamente.')
                    else:
                        messages.warning(request, f'Conteudo atualizado, mas o card final nao foi renderizado: {exc}')
                    return redirect('social_automation:content_detail', content_id=content.id)
            else:
                messages.success(request, 'Conteudo atualizado com sucesso.')
            return redirect('social_automation:content_detail', content_id=content.id)
    else:
        form = SocialContentForm(instance=content)
        slide_formset = SocialCarouselSlideFormSet(instance=content)
    return render(request, 'social_automation/content_form.html', {'form': form, 'slide_formset': slide_formset, 'content': content, 'titulo': 'Editar conteudo'})


@staff_required
def content_detail(request, content_id):
    content = get_object_or_404(_content_queryset(), pk=content_id)
    schedule_form = SocialScheduleForm(profile=content.profile) if content.status == SocialContent.Status.APROVADO else None
    events = content.events.select_related('usuario')[:20]
    instagram_connection = getattr(content.profile, 'instagram_connection', None)
    return render(
        request,
        'social_automation/content_detail.html',
        {
            'content': content,
            'events': events,
            'schedule_form': schedule_form,
            'instagram_expected_username': instagram_connection.username if instagram_connection and instagram_connection.is_active else content.profile.username,
            'instagram_connection': instagram_connection,
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
def profile_generate_carousel_ai(request, profile_id):
    profile = _profile_or_404(profile_id)
    resultado = None
    if request.method == 'POST':
        form = SocialAICarouselForm(request.POST, profile=profile)
        if form.is_valid():
            try:
                resultado = gerar_carrossel_autonomo(
                    profile,
                    tema=form.cleaned_data.get('tema') or '',
                    slides=form.cleaned_data.get('slides') or profile.carousel_default_slide_count,
                    usuario=request.user,
                )
                messages.success(request, 'Carrossel gerado como rascunho.')
                return redirect('social_automation:content_detail', content_id=resultado.content.id)
            except (OpenAINotConfigured, OpenAIUnavailable, ValidationError, SocialRenderError) as exc:
                _handle_validation_error(request, exc)
    else:
        form = SocialAICarouselForm(profile=profile)
    return render(request, 'social_automation/generate_carousel_ai_form.html', {'profile': profile, 'form': form, 'resultado': resultado})


@staff_required
@require_POST
def carousel_slide_generate_image(request, slide_id):
    slide = get_object_or_404(SocialCarouselSlide.objects.select_related('content', 'content__profile'), pk=slide_id)
    content = slide.content
    if not content.pode_editar_operacionalmente:
        messages.error(request, 'Conteudo publicado nao pode gerar nova imagem.')
        return redirect('social_automation:content_detail', content_id=content.id)
    try:
        prompt_text = build_social_image_prompt(
            content.profile,
            purpose='CAROUSEL_SLIDE',
            visual_intent=slide.semantic_visual_intent or 'CLEAN',
            media_intent=slide.media_intent or slide.title,
            desired_text_zone=slide.visual_intent,
            aspect_ratio=content.carousel_template.aspect_ratio if content.carousel_template else 'SQUARE',
            context={'slide_id': slide.id, 'title': slide.title},
        )
        image = generate_social_image(
            SocialImagePrompt(
                profile_id=content.profile_id,
                prompt=prompt_text,
                aspect_ratio=content.carousel_template.aspect_ratio if content.carousel_template else 'SQUARE',
                purpose='CAROUSEL_SLIDE',
                metadata={'slide_id': slide.id, 'visual_intent': slide.semantic_visual_intent, 'media_intent': slide.media_intent},
            )
        )
        try:
            analyze_social_image(content.profile, image, persist=True)
        except OpenAIUnavailable:
            pass
        slide.source_base_image = image
        slide.save(update_fields=['source_base_image', 'updated_at'])
        renderizar_midia_social(content)
        messages.success(request, 'Imagem do slide gerada e carrossel renderizado novamente.')
    except (OpenAINotConfigured, OpenAIUnavailable, ValidationError, SocialRenderError) as exc:
        _handle_validation_error(request, exc)
    return redirect('social_automation:content_detail', content_id=content.id)


@staff_required
@require_POST
def content_render(request, content_id):
    content = get_object_or_404(_content_queryset(), pk=content_id)
    if content.status == SocialContent.Status.PUBLICADO:
        messages.error(request, 'Conteudo publicado nao pode ser renderizado novamente. Duplique para criar uma nova versao.')
        return redirect('social_automation:content_detail', content_id=content.id)
    try:
        renderizar_midia_social(content)
        messages.success(request, 'Midia renderizada novamente.')
    except SocialRenderError as exc:
        if content.is_reel:
            logger.warning('reel_render_ui_error content_id=%s exception_class=%s message=%s', content.id, type(exc).__name__, str(exc)[:180])
            messages.error(request, 'Nao foi possivel gerar o Reel. Verifique os logs ou tente novamente.')
        else:
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


def ig_carousel_slide(request, content_id, slide_id, signature):
    if request.method not in {'GET', 'HEAD'}:
        return HttpResponseNotAllowed(['GET', 'HEAD'])
    try:
        slide = validar_assinatura_carousel_slide_meta(content_id, slide_id, signature)
    except ValidationError as exc:
        raise Http404 from exc
    if not slide.rendered_image:
        raise Http404
    with slide.rendered_image.storage.open(slide.rendered_image.name, 'rb') as arquivo:
        image_bytes = arquivo.read()
    logger.info('signed_carousel_slide_fetch content_id=%s slide_id=%s method=%s bytes=%s', content_id, slide.id, request.method, len(image_bytes))
    body = b'' if request.method == 'HEAD' else image_bytes
    response = HttpResponse(body, content_type='image/jpeg')
    response['Content-Length'] = str(len(image_bytes))
    response['Cache-Control'] = 'private, max-age=0, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@staff_required
def carousel_slide_preview(request, slide_id):
    slide = get_object_or_404(SocialCarouselSlide.objects.select_related('content', 'content__profile'), pk=slide_id)
    if not slide.rendered_image:
        raise Http404
    return FileResponse(
        slide.rendered_image.storage.open(slide.rendered_image.name, 'rb'),
        content_type='image/jpeg',
        as_attachment=False,
        filename=f'carousel-slide-{slide.order}.jpg',
    )


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
    connection = getattr(profile, 'instagram_connection', None)
    if not connection or not connection.is_active:
        messages.error(request, 'Instagram nao conectado neste perfil.')
        return redirect('social_automation:profile_detail', profile_id=profile.id)
    try:
        conta = validar_conexao_instagram(connection)
        messages.success(request, f'Instagram conectado: @{conta.get("username") or "-"}')
    except (InstagramConfigurationError, InstagramAPIError) as exc:
        connection.mark_validation(ok=False, error=str(exc))
        messages.error(request, str(exc))
    return redirect('social_automation:profile_detail', profile_id=profile.id)


@staff_required
def instagram_connect_start(request, profile_id):
    profile = _profile_or_404(profile_id)
    state = secrets.token_urlsafe(32)
    request.session['social_instagram_oauth_state'] = {
        'state': state,
        'profile_id': profile.id,
        'user_id': request.user.id,
    }
    try:
        return redirect(build_instagram_oauth_url(state, request=request))
    except InstagramConfigurationError as exc:
        messages.error(request, str(exc))
        return redirect('social_automation:profile_detail', profile_id=profile.id)


@staff_required
def instagram_callback(request):
    expected = request.session.pop('social_instagram_oauth_state', None) or {}
    state = request.GET.get('state') or ''
    code = request.GET.get('code') or ''
    if not expected or not secrets.compare_digest(expected.get('state', ''), state) or expected.get('user_id') != request.user.id:
        return HttpResponseForbidden('State OAuth invalido.')
    profile = _profile_or_404(expected.get('profile_id'))
    if not code:
        messages.error(request, 'A Meta nao retornou codigo de autorizacao.')
        return redirect('social_automation:profile_detail', profile_id=profile.id)
    try:
        token_data = exchange_instagram_code(code, request=request)
        connection = criar_ou_atualizar_conexao_instagram(
            profile,
            access_token=token_data['access_token'],
            instagram_user_id=token_data.get('user_id') or '',
        )
        messages.success(request, f'Instagram conectado em @{connection.username}.')
    except (InstagramConfigurationError, InstagramAPIError) as exc:
        messages.error(request, str(exc))
    return redirect('social_automation:profile_detail', profile_id=profile.id)


@staff_required
@require_POST
def instagram_disconnect(request, profile_id):
    profile = _profile_or_404(profile_id)
    connection = getattr(profile, 'instagram_connection', None)
    if connection:
        connection.is_active = False
        connection.save(update_fields=['is_active', 'updated_at'])
        profile.contents.exclude(instagram_container_id='').update(instagram_container_id='', instagram_container_fingerprint='')
        messages.success(request, 'Instagram desconectado deste perfil.')
    else:
        messages.info(request, 'Este perfil ainda nao possui conexao Instagram.')
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
