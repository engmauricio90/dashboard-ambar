from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import formats, timezone

from .models import SocialCarouselSlide, SocialContent, SocialContentEvent, SocialPublishAttempt


def registrar_evento(content, acao, usuario=None, detalhe=''):
    return SocialContentEvent.objects.create(content=content, acao=acao, usuario=usuario, detalhe=detalhe[:255])


@transaction.atomic
def criar_evento_criacao(content, usuario=None):
    registrar_evento(content, SocialContentEvent.Acao.CRIADO, usuario)
    return content


@transaction.atomic
def registrar_edicao(content, usuario=None):
    registrar_evento(content, SocialContentEvent.Acao.EDITADO, usuario)
    return content


@transaction.atomic
def aprovar_conteudo(content, usuario=None):
    content = SocialContent.objects.select_for_update().get(pk=content.pk)
    if content.status != SocialContent.Status.RASCUNHO:
        raise ValidationError('Somente rascunhos podem ser aprovados.')
    content.status = SocialContent.Status.APROVADO
    content.save(update_fields=['status', 'updated_at'])
    registrar_evento(content, SocialContentEvent.Acao.APROVADO, usuario)
    return content


@transaction.atomic
def rejeitar_conteudo(content, usuario=None):
    content = SocialContent.objects.select_for_update().get(pk=content.pk)
    if content.status not in {SocialContent.Status.RASCUNHO, SocialContent.Status.APROVADO}:
        raise ValidationError('Somente rascunhos ou aprovados podem ser rejeitados.')
    content.status = SocialContent.Status.REJEITADO
    content.scheduled_at = None
    content.save(update_fields=['status', 'scheduled_at', 'updated_at'])
    registrar_evento(content, SocialContentEvent.Acao.REJEITADO, usuario)
    return content


@transaction.atomic
def restaurar_rascunho(content, usuario=None):
    content = SocialContent.objects.select_for_update().get(pk=content.pk)
    if content.status != SocialContent.Status.REJEITADO:
        raise ValidationError('Somente conteudos rejeitados podem voltar para rascunho.')
    content.status = SocialContent.Status.RASCUNHO
    content.save(update_fields=['status', 'updated_at'])
    registrar_evento(content, SocialContentEvent.Acao.RESTAURADO, usuario)
    return content


@transaction.atomic
def agendar_conteudo(content, scheduled_at, usuario=None):
    content = SocialContent.objects.select_for_update().get(pk=content.pk)
    if content.status not in {SocialContent.Status.APROVADO, SocialContent.Status.RETRY_LIBERADO_MANUAL}:
        raise ValidationError('Somente conteudos aprovados ou liberados manualmente podem ser agendados.')
    if scheduled_at <= timezone.now():
        raise ValidationError('Informe uma data e hora futura.')
    content.status = SocialContent.Status.AGENDADO
    content.scheduled_at = scheduled_at
    content.save(update_fields=['status', 'scheduled_at', 'updated_at'])
    detalhe = f'Agendado para {formats.date_format(timezone.localtime(scheduled_at), "SHORT_DATETIME_FORMAT")}'
    registrar_evento(content, SocialContentEvent.Acao.AGENDADO, usuario, detalhe)
    return content


@transaction.atomic
def desagendar_conteudo(content, usuario=None):
    content = SocialContent.objects.select_for_update().get(pk=content.pk)
    if content.status != SocialContent.Status.AGENDADO:
        raise ValidationError('Somente conteudos agendados podem ser desagendados.')
    content.status = SocialContent.Status.APROVADO
    content.scheduled_at = None
    content.save(update_fields=['status', 'scheduled_at', 'updated_at'])
    registrar_evento(content, SocialContentEvent.Acao.DESAGENDADO, usuario)
    return content


@transaction.atomic
def confirmar_nao_publicado_e_liberar_tentativa(content, usuario=None):
    content = SocialContent.objects.select_for_update().get(pk=content.pk)
    if content.status == SocialContent.Status.RETRY_LIBERADO_MANUAL:
        return content
    if content.status != SocialContent.Status.PUBLISH_CONFIRMATION_PENDING:
        raise ValidationError('Somente publicacoes pendentes de confirmacao podem ser liberadas por conferencia manual.')
    if content.external_post_id:
        raise ValidationError('Este conteudo ja possui ID externo e nao pode ser liberado como nao publicado.')
    if content.publish_attempts.filter(provider=SocialPublishAttempt.Provider.INSTAGRAM, status=SocialPublishAttempt.Status.CONFIRMED).exists():
        raise ValidationError('Existe tentativa confirmada para este conteudo.')
    attempt = (
        content.publish_attempts.select_for_update()
        .filter(provider=SocialPublishAttempt.Provider.INSTAGRAM, status=SocialPublishAttempt.Status.AMBIGUOUS)
        .order_by('-started_at', '-id')
        .first()
    )
    if not attempt:
        raise ValidationError('Nenhuma tentativa ambigua ativa foi encontrada para liberar.')

    now = timezone.now()
    metadata = dict(attempt.metadata or {})
    metadata.setdefault('operator_resolution', {})
    metadata['operator_resolution'].update(
        {
            'action': 'not_published_confirmed_by_operator',
            'operator_user_id': usuario.id if usuario and usuario.is_authenticated else None,
            'operator_username': usuario.get_username() if usuario and usuario.is_authenticated else '',
            'confirmed_at': now.isoformat(),
            'previous_container_id': attempt.container_id,
        }
    )
    attempt.status = SocialPublishAttempt.Status.NOT_PUBLISHED_CONFIRMED_BY_OPERATOR
    attempt.provider_response_at = attempt.provider_response_at or now
    attempt.metadata = metadata
    attempt.save(update_fields=['status', 'provider_response_at', 'metadata', 'updated_at'])

    content.status = SocialContent.Status.RETRY_LIBERADO_MANUAL
    content.scheduled_at = None
    content.erro = 'Nova tentativa liberada manualmente. Publique agora ou agende novamente.'
    content.instagram_container_id = ''
    content.instagram_container_fingerprint = ''
    content.save(update_fields=['status', 'scheduled_at', 'erro', 'instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
    if content.is_carousel:
        SocialCarouselSlide.objects.filter(content=content, is_active=True).exclude(instagram_container_id='').update(
            instagram_container_id='',
            instagram_container_fingerprint='',
            updated_at=now,
        )
    registrar_evento(
        content,
        SocialContentEvent.Acao.PUBLISH_NOT_PUBLISHED_OPERATOR,
        usuario,
        f'Operador confirmou que a publicacao nao estava no Instagram; tentativa #{attempt.id}; container {attempt.container_id or "-"}.',
    )
    return content
