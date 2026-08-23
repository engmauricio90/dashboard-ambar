from zoneinfo import available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def social_base_image_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return f'social/{profile_id}/base/{filename}'


def social_final_image_upload_to(instance, filename):
    profile_id = instance.profile_id or 'sem-perfil'
    return f'social/{profile_id}/posts/{filename}'


def validate_timezone_name(value):
    if value not in available_timezones():
        raise ValidationError('Timezone invalido.')


def validate_horarios_publicacao(value):
    if not isinstance(value, list):
        raise ValidationError('Informe uma lista de horarios.')
    for horario in value:
        if not isinstance(horario, str):
            raise ValidationError('Cada horario deve ser texto no formato HH:MM.')
        partes = horario.split(':')
        if len(partes) != 2 or not all(parte.isdigit() for parte in partes):
            raise ValidationError('Use horarios no formato HH:MM.')
        hora, minuto = [int(parte) for parte in partes]
        if hora > 23 or minuto > 59:
            raise ValidationError('Use horarios validos no formato HH:MM.')


class SocialProfile(models.Model):
    class Plataforma(models.TextChoices):
        INSTAGRAM = 'instagram', 'Instagram'

    class ModoOperacao(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        SEMIAUTOMATICO = 'semiautomatico', 'Semiautomatico'
        AUTOMATICO = 'automatico', 'Automatico'

    nome = models.CharField(max_length=120)
    username = models.CharField(max_length=120)
    plataforma = models.CharField(max_length=30, choices=Plataforma.choices, default=Plataforma.INSTAGRAM)
    ativo = models.BooleanField(default=True)
    timezone = models.CharField(max_length=80, default='America/Sao_Paulo', validators=[validate_timezone_name])
    modo_operacao = models.CharField(max_length=30, choices=ModoOperacao.choices, default=ModoOperacao.SEMIAUTOMATICO)
    posts_por_dia = models.PositiveSmallIntegerField(default=2)
    horarios_publicacao = models.JSONField(default=list, validators=[validate_horarios_publicacao])
    estilo = models.TextField(blank=True)
    instrucoes_ia = models.TextField(blank=True)
    responder_comentarios = models.BooleanField(default=False)
    limite_respostas = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']
        indexes = [
            models.Index(fields=['ativo', 'plataforma']),
        ]

    def __str__(self):
        return f'{self.nome} ({self.username})'


class SocialBaseImage(models.Model):
    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='base_images')
    arquivo = models.ImageField(upload_to=social_base_image_upload_to)
    nome = models.CharField(max_length=120)
    tags = models.CharField(max_length=255, blank=True)
    ativa = models.BooleanField(default=True)
    vezes_usada = models.PositiveIntegerField(default=0)
    ultima_utilizacao = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['profile', 'ativa']),
        ]

    def __str__(self):
        return f'{self.profile.username} - {self.nome}'


class SocialContent(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = 'rascunho', 'Rascunho'
        APROVADO = 'aprovado', 'Aprovado'
        AGENDADO = 'agendado', 'Agendado'
        PUBLICANDO = 'publicando', 'Publicando'
        PUBLICADO = 'publicado', 'Publicado'
        ERRO = 'erro', 'Erro'
        REJEITADO = 'rejeitado', 'Rejeitado'

    profile = models.ForeignKey(SocialProfile, on_delete=models.CASCADE, related_name='contents')
    base_image = models.ForeignKey(SocialBaseImage, on_delete=models.SET_NULL, blank=True, null=True, related_name='contents')
    final_image = models.ImageField(upload_to=social_final_image_upload_to, blank=True, null=True)
    frase = models.CharField(max_length=500)
    legenda = models.TextField(blank=True)
    hashtags = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.RASCUNHO)
    scheduled_at = models.DateTimeField(blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True)
    external_post_id = models.CharField(max_length=120, blank=True)
    external_permalink = models.URLField(blank=True)
    erro = models.TextField(blank=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    ultima_tentativa = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['profile', 'status']),
            models.Index(fields=['status', 'scheduled_at']),
        ]

    def __str__(self):
        return f'{self.profile.username} - {self.frase[:60]}'

    @property
    def pode_editar_operacionalmente(self):
        return self.status in {
            self.Status.RASCUNHO,
            self.Status.APROVADO,
            self.Status.AGENDADO,
            self.Status.ERRO,
        }

    @property
    def pode_excluir_operacionalmente(self):
        return self.status in {self.Status.RASCUNHO, self.Status.REJEITADO, self.Status.APROVADO}


class SocialContentEvent(models.Model):
    class Acao(models.TextChoices):
        CRIADO = 'criado', 'Criado'
        EDITADO = 'editado', 'Editado'
        APROVADO = 'aprovado', 'Aprovado'
        REJEITADO = 'rejeitado', 'Rejeitado'
        AGENDADO = 'agendado', 'Agendado'
        DESAGENDADO = 'desagendado', 'Desagendado'
        RESTAURADO = 'restaurado', 'Restaurado'
        EXCLUIDO = 'excluido', 'Excluido'

    content = models.ForeignKey(SocialContent, on_delete=models.CASCADE, related_name='events')
    acao = models.CharField(max_length=30, choices=Acao.choices)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
    detalhe = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['content', '-created_at']),
        ]

    def __str__(self):
        return f'{self.content_id} - {self.get_acao_display()}'
