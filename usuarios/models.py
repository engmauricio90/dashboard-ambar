from django.conf import settings
from django.db import models

from obras.models import Obra


class PerfilUsuario(models.Model):
    SETOR_CHOICES = [
        ('diretoria', 'Diretoria'),
        ('financeiro', 'Financeiro'),
        ('engenharia', 'Engenharia'),
        ('compras', 'Compras'),
        ('administrativo', 'Administrativo'),
        ('obras', 'Obras'),
        ('consulta', 'Consulta'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    telefone = models.CharField(max_length=40, blank=True)
    cargo = models.CharField(max_length=120, blank=True)
    setor = models.CharField(max_length=30, choices=SETOR_CHOICES, blank=True)
    avatar = models.ImageField(upload_to='usuarios/avatares/', blank=True, null=True)
    obras = models.ManyToManyField(Obra, blank=True, related_name='usuarios_vinculados')
    dashboard_inicial = models.CharField(max_length=120, blank=True)
    itens_por_pagina = models.PositiveIntegerField(default=25)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil de usuario'
        verbose_name_plural = 'Perfis de usuarios'

    def __str__(self):
        return self.user.get_full_name() or self.user.username
