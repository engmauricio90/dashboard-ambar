from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date

from controles.models import OrcamentoRadarObra


class Proposta(models.Model):
    SITUACAO_CHOICES = OrcamentoRadarObra.SITUACAO_CHOICES

    numero_sequencial = models.PositiveIntegerField(editable=False)
    ano = models.PositiveIntegerField(editable=False)
    cliente = models.CharField(max_length=150)
    tipo_execucao = models.CharField(max_length=200)
    data_proposta = models.DateField(default=timezone.localdate)
    servico_incluso = models.TextField(verbose_name='Servico incluido na proposta')
    prazo_execucao = models.CharField(max_length=200, blank=True)
    forma_pagamento = models.TextField(blank=True)
    observacoes = models.TextField(blank=True)
    incluir_planilha = models.BooleanField(default=True)
    planilha_imagem = models.ImageField(upload_to='propostas/planilhas/', blank=True, null=True)
    bdi_percentual = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='BDI interno (%)')
    local_fechamento = models.CharField(max_length=120, default='Campo Bom/RS')
    data_encerramento = models.DateField(blank=True, null=True)
    engenheiro_nome = models.CharField(max_length=120, default='Eng. Civil Patrick Ruppenthal de Lima')
    engenheiro_crea = models.CharField(max_length=80, default='CREA/RS: 198.404')
    situacao = models.CharField(max_length=30, choices=SITUACAO_CHOICES, default='aguardando_resposta')
    radar = models.OneToOneField(
        OrcamentoRadarObra,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='proposta_comercial',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-ano', '-numero_sequencial']
        verbose_name = 'Proposta comercial'
        verbose_name_plural = 'Propostas comerciais'
        constraints = [
            models.UniqueConstraint(fields=['numero_sequencial', 'ano'], name='unique_numero_proposta_por_ano'),
        ]

    def save(self, *args, **kwargs):
        if isinstance(self.data_proposta, str):
            self.data_proposta = parse_date(self.data_proposta)
        if isinstance(self.data_encerramento, str):
            self.data_encerramento = parse_date(self.data_encerramento)

        if not self.pk:
            ano = self.data_proposta.year if self.data_proposta else timezone.localdate().year
            ultimo_numero = (
                Proposta.objects.filter(ano=ano).aggregate(models.Max('numero_sequencial'))['numero_sequencial__max']
                or 0
            )
            self.ano = ano
            self.numero_sequencial = ultimo_numero + 1
        elif self.data_proposta:
            self.ano = self.data_proposta.year

        if not self.data_encerramento:
            self.data_encerramento = self.data_proposta

        super().save(*args, **kwargs)

    @property
    def numero_formatado(self):
        return f'{self.numero_sequencial:03d}/{self.ano}'

    @property
    def titulo_documento(self):
        return f'PROPOSTA Nr {self.numero_formatado}'

    @property
    def total_resumo(self):
        return sum((item.valor for item in self.itens_resumo.all()), Decimal('0'))

    @property
    def total_planilha(self):
        return sum((item.total_cliente for item in self.itens_planilha.all()), Decimal('0'))

    @property
    def total_final(self):
        return self.total_planilha or self.total_resumo

    def sincronizar_radar(self):
        defaults = {
            'cliente': self.cliente,
            'descricao': self.tipo_execucao,
            'data_orcamento': self.data_proposta,
            'situacao': self.situacao,
            'valor_estimado': self.total_final,
            'responsavel': self.engenheiro_nome,
            'observacoes': f'Gerado automaticamente pela proposta {self.numero_formatado}.',
        }
        radar, _ = OrcamentoRadarObra.objects.update_or_create(
            pk=self.radar_id,
            defaults={'numero': self.numero_formatado, **defaults},
        )
        if self.radar_id != radar.id:
            self.radar = radar
            self.save(update_fields=['radar', 'updated_at'])

    def __str__(self):
        return f'{self.numero_formatado} - {self.cliente}'


class PropostaResumoItem(models.Model):
    proposta = models.ForeignKey(
        Proposta,
        on_delete=models.CASCADE,
        related_name='itens_resumo',
    )
    ordem = models.PositiveIntegerField(default=1)
    descricao = models.CharField(max_length=255)
    quantidade_descricao = models.CharField(max_length=40, default='1 vb')
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ['ordem', 'id']
        verbose_name = 'Item resumido da proposta'
        verbose_name_plural = 'Itens resumidos da proposta'

    def __str__(self):
        return self.descricao


class PropostaPlanilhaItem(models.Model):
    proposta = models.ForeignKey(
        Proposta,
        on_delete=models.CASCADE,
        related_name='itens_planilha',
    )
    ordem = models.PositiveIntegerField(default=1, verbose_name='Nr item')
    descricao = models.CharField(max_length=255)
    unidade = models.CharField(max_length=20, verbose_name='Und')
    quantidade = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    preco_unit_material = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name='Preco unit material/equipamento',
    )
    preco_unit_mao_obra = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name='Preco unit mao de obra',
    )

    class Meta:
        ordering = ['ordem', 'id']
        verbose_name = 'Item da planilha orcamentaria'
        verbose_name_plural = 'Itens da planilha orcamentaria'

    @property
    def custo_unit_sem_bdi(self):
        return self.preco_unit_material + self.preco_unit_mao_obra

    @property
    def preco_unit_cliente(self):
        multiplicador = Decimal('1') + (self.proposta.bdi_percentual / Decimal('100'))
        return self.custo_unit_sem_bdi * multiplicador

    @property
    def total_cliente(self):
        return self.preco_unit_cliente * self.quantidade

    def __str__(self):
        return f'{self.ordem} - {self.descricao}'
