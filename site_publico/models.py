from django.db import models


class PublicLead(models.Model):
    class BillingPreference(models.TextChoices):
        MENSAL = 'MENSAL', 'Mensal'
        SEMESTRAL = 'SEMESTRAL', 'Semestral'
        ANUAL = 'ANUAL', 'Anual'

    class Status(models.TextChoices):
        NOVO = 'NOVO', 'Novo'
        CONTATADO = 'CONTATADO', 'Contatado'
        DEMONSTRACAO_AGENDADA = 'DEMONSTRACAO_AGENDADA', 'Demonstração agendada'
        PROPOSTA = 'PROPOSTA', 'Proposta'
        GANHO = 'GANHO', 'Ganho'
        PERDIDO = 'PERDIDO', 'Perdido'

    class ComoControlaHoje(models.TextChoices):
        EXCEL = 'EXCEL', 'Excel'
        ERP = 'ERP', 'ERP'
        SOFTWARE_OBRAS = 'SOFTWARE_OBRAS', 'Software de obras'
        CONTROLES_PROPRIOS = 'CONTROLES_PROPRIOS', 'Controles próprios'
        WHATSAPP_PLANILHAS = 'WHATSAPP_PLANILHAS', 'WhatsApp + planilhas'
        OUTRO = 'OUTRO', 'Outro'

    class PrincipalDificuldade(models.TextChoices):
        MEDICOES_FATURAMENTO = 'MEDICOES_FATURAMENTO', 'Medições e faturamento'
        CUSTOS_OBRA = 'CUSTOS_OBRA', 'Custos da obra'
        FINANCEIRO = 'FINANCEIRO', 'Financeiro'
        COMPRAS = 'COMPRAS', 'Compras'
        DIARIO_CAMPO = 'DIARIO_CAMPO', 'Diário / campo'
        VISAO_RESULTADO = 'VISAO_RESULTADO', 'Visão de resultado'
        INFORMACOES_ESPALHADAS = 'INFORMACOES_ESPALHADAS', 'Informações espalhadas'
        OUTRO = 'OUTRO', 'Outro'

    nome = models.CharField(max_length=120)
    empresa = models.CharField(max_length=160)
    email = models.EmailField()
    telefone = models.CharField(max_length=32)
    telefone_normalizado = models.CharField(max_length=20, blank=True)
    cargo_funcao = models.CharField(max_length=120, blank=True)
    quantidade_obras = models.PositiveIntegerField(null=True, blank=True)
    como_controla_hoje = models.CharField(max_length=32, choices=ComoControlaHoje.choices, blank=True)
    principal_dificuldade = models.CharField(max_length=32, choices=PrincipalDificuldade.choices, blank=True)
    mensagem = models.TextField(blank=True)
    billing_preference = models.CharField(max_length=16, choices=BillingPreference.choices, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NOVO)
    observacao_comercial = models.TextField(blank=True)
    utm_source = models.CharField(max_length=120, blank=True)
    utm_medium = models.CharField(max_length=120, blank=True)
    utm_campaign = models.CharField(max_length=160, blank=True)
    utm_content = models.CharField(max_length=160, blank=True)
    utm_term = models.CharField(max_length=160, blank=True)
    landing_path = models.CharField(max_length=300, blank=True)
    referrer = models.URLField(max_length=500, blank=True)
    gclid = models.CharField(max_length=200, blank=True)
    fbclid = models.CharField(max_length=200, blank=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['utm_source', '-created_at']),
            models.Index(fields=['utm_campaign', '-created_at']),
        ]

    def __str__(self):
        return f'{self.nome} - {self.empresa}'

    @property
    def origem_resumida(self):
        if self.utm_source and self.utm_campaign:
            return f'{self.utm_source} / {self.utm_campaign}'
        return self.utm_source or self.referrer or 'Direto'
