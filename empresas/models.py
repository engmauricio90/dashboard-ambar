from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


def empresa_logo_upload_to(instance, filename):
    slug = instance.slug or 'sem-slug'
    return f'empresas/{slug}/branding/logo/{filename}'


def empresa_cabecalho_upload_to(instance, filename):
    slug = instance.slug or 'sem-slug'
    return f'empresas/{slug}/branding/cabecalho/{filename}'


def empresa_rodape_upload_to(instance, filename):
    slug = instance.slug or 'sem-slug'
    return f'empresas/{slug}/branding/rodape/{filename}'


class Empresa(models.Model):
    nome = models.CharField(max_length=160)
    razao_social = models.CharField(max_length=180, blank=True)
    nome_fantasia = models.CharField(max_length=180, blank=True)
    cnpj = models.CharField(max_length=20, blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    estado = models.CharField(max_length=2, blank=True)
    cep = models.CharField(max_length=20, blank=True)
    telefone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    slug = models.SlugField(max_length=80, unique=True)
    logo = models.ImageField(upload_to=empresa_logo_upload_to, blank=True, null=True)
    cabecalho_documentos = models.ImageField(upload_to=empresa_cabecalho_upload_to, blank=True, null=True)
    rodape_documentos = models.ImageField(upload_to=empresa_rodape_upload_to, blank=True, null=True)
    texto_rodape = models.TextField(blank=True)
    cor_primaria = models.CharField(
        max_length=7,
        blank=True,
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Informe uma cor hexadecimal valida, como #1f2937.')],
    )
    cor_secundaria = models.CharField(
        max_length=7,
        blank=True,
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Informe uma cor hexadecimal valida, como #e5e7eb.')],
    )
    ativa = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    responsavel_tecnico = models.CharField(max_length=160, blank=True)
    crea_responsavel = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'

    def __str__(self):
        return self.nome

    @property
    def nome_documento(self):
        return self.razao_social or self.nome_fantasia or self.nome

    @property
    def linhas_institucionais(self):
        linhas = []
        if self.cnpj:
            linhas.append(f'CNPJ: {self.cnpj}')
        endereco = ', '.join(item for item in [self.endereco, self.cidade, self.estado, self.cep] if item)
        if endereco:
            linhas.append(endereco)
        contato = ' | '.join(item for item in [self.telefone, self.email] if item)
        if contato:
            linhas.append(contato)
        return linhas


class UsuarioEmpresa(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='empresas_vinculadas')
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='usuarios_vinculados')
    grupo = models.ForeignKey(
        'auth.Group',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='vinculos_empresas',
    )
    obras_permitidas = models.ManyToManyField(
        'obras.Obra',
        blank=True,
        related_name='usuarios_empresas_permitidos',
    )
    ativo = models.BooleanField(default=True)
    administrador_empresa = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['empresa__nome', 'usuario__username']
        verbose_name = 'Usuario da empresa'
        verbose_name_plural = 'Usuarios das empresas'
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'empresa'], name='unique_usuario_empresa'),
        ]

    def __str__(self):
        return f'{self.usuario} - {self.empresa}'
