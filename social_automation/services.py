from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import formats, timezone

from .models import SocialContent, SocialContentEvent


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
    if content.status != SocialContent.Status.APROVADO:
        raise ValidationError('Somente conteudos aprovados podem ser agendados.')
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
