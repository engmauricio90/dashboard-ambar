from decimal import Decimal

from django.db import models
from django.db.models import Sum


def _sum_decimal(values):
    return sum(values, Decimal('0'))


class Obra(models.Model):
    STATUS_CHOICES = [
        ('em_andamento', 'Em andamento'),
        ('concluida', 'Concluida'),
        ('paralisada', 'Paralisada'),
    ]

    nome_obra = models.CharField(max_length=150)
    cliente = models.CharField(max_length=150, blank=True, null=True)
    status_obra = models.CharField(max_length=20, choices=STATUS_CHOICES, default='em_andamento')
    responsavel = models.CharField(max_length=100, blank=True, null=True)
    data_inicio = models.DateField(blank=True, null=True)
    observacoes = models.TextField(blank=True, null=True)

    # Campos legados mantidos apenas para preservacao historica do banco.
    valor_contrato = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    aditivos = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    projecao_despesa = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    despesa_real = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retencoes_tecnicas = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    impostos = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_notas = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def _prefetched_items(self, relation_name):
        cache = getattr(self, '_prefetched_objects_cache', {})
        return cache.get(relation_name)

    def _aggregate_value(self, aggregate_path):
        aggregated = self.__class__.objects.filter(pk=self.pk).aggregate(total=Sum(aggregate_path))['total']
        return aggregated or Decimal('0')

    def _notas_fiscais_ativas(self):
        notas = self._prefetched_items('notas_fiscais')
        if notas is not None:
            return [nota for nota in notas if nota.status != NotaFiscal.STATUS_CANCELADA]
        return None

    @property
    def total_aditivos(self):
        aditivos = self._prefetched_items('aditivos_registrados')
        if aditivos is not None:
            return _sum_decimal(
                aditivo.valor
                for aditivo in aditivos
                if aditivo.tipo == AditivoContrato.TIPO_ADITIVO
            )
        return (
            self.aditivos_registrados.filter(tipo=AditivoContrato.TIPO_ADITIVO).aggregate(total=Sum('valor'))['total']
            or Decimal('0')
        )

    @property
    def total_supressoes(self):
        aditivos = self._prefetched_items('aditivos_registrados')
        if aditivos is not None:
            return _sum_decimal(
                aditivo.valor
                for aditivo in aditivos
                if aditivo.tipo == AditivoContrato.TIPO_SUPRESSAO
            )
        return (
            self.aditivos_registrados.filter(tipo=AditivoContrato.TIPO_SUPRESSAO).aggregate(total=Sum('valor'))['total']
            or Decimal('0')
        )

    @property
    def total_movimentacoes_contratuais(self):
        return self.total_aditivos - self.total_supressoes

    @property
    def total_despesa_real(self):
        despesas = self._prefetched_items('despesas_registradas')
        if despesas is not None:
            return _sum_decimal(despesa.valor for despesa in despesas)
        return self._aggregate_value('despesas_registradas__valor')

    @property
    def total_retencoes_nf(self):
        notas = self._notas_fiscais_ativas()
        if notas is not None:
            return _sum_decimal(nota.total_retencoes for nota in notas)
        return (
            self.notas_fiscais.exclude(status=NotaFiscal.STATUS_CANCELADA)
            .aggregate(total=Sum('retencoes__valor'))['total']
            or Decimal('0')
        )

    @property
    def total_retencoes_inss(self):
        notas = self._notas_fiscais_ativas()
        if notas is not None:
            return _sum_decimal(nota.total_retencoes_inss for nota in notas)
        return (
            self.notas_fiscais.exclude(status=NotaFiscal.STATUS_CANCELADA)
            .filter(retencoes__tipo=RetencaoNotaFiscal.TIPO_INSS)
            .aggregate(total=Sum('retencoes__valor'))['total']
            or Decimal('0')
        )

    @property
    def total_retencoes_nf_sem_inss(self):
        return self.total_retencoes_nf - self.total_retencoes_inss

    @property
    def total_retencoes_tecnicas(self):
        retencoes_tecnicas = self._prefetched_items('retencoes_tecnicas_registradas')
        if retencoes_tecnicas is not None:
            return _sum_decimal(retencao.valor_saldo for retencao in retencoes_tecnicas)
        retencoes = self.retencoes_tecnicas_registradas.all()
        return _sum_decimal(retencao.valor_saldo for retencao in retencoes)

    @property
    def total_retencoes(self):
        return self.total_retencoes_nf + self.total_retencoes_tecnicas

    @property
    def total_impostos(self):
        notas = self._notas_fiscais_ativas()
        if notas is not None:
            return _sum_decimal(nota.total_impostos for nota in notas)
        return (
            self.notas_fiscais.exclude(status=NotaFiscal.STATUS_CANCELADA)
            .aggregate(total=Sum('impostos__valor'))['total']
            or Decimal('0')
        )

    @property
    def total_notas_fiscais(self):
        notas = self._notas_fiscais_ativas()
        if notas is not None:
            return _sum_decimal(nota.valor_bruto for nota in notas)
        return (
            self.notas_fiscais.exclude(status=NotaFiscal.STATUS_CANCELADA)
            .aggregate(total=Sum('valor_bruto'))['total']
            or Decimal('0')
        )

    @property
    def total_recebido_liquido(self):
        return self.total_notas_fiscais - self.total_retencoes - self.total_impostos

    @property
    def contrato_atualizado(self):
        return self.valor_contrato + self.total_aditivos - self.total_supressoes

    @property
    def saldo_contratual(self):
        return self.contrato_atualizado - self.total_notas_fiscais

    @property
    def projecao_resultado(self):
        return (
            self.contrato_atualizado
            - self.projecao_despesa
            - self.total_impostos
            - self.total_retencoes
        )

    @property
    def resultado_real(self):
        return (
            self.total_notas_fiscais
            - self.total_despesa_real
            - self.total_impostos
            - self.total_retencoes
        )

    @property
    def percentual_faturado(self):
        if self.contrato_atualizado > 0:
            return (self.total_notas_fiscais / self.contrato_atualizado) * 100
        return Decimal('0')

    @property
    def margem_projetada(self):
        if self.contrato_atualizado > 0:
            return (self.projecao_resultado / self.contrato_atualizado) * 100
        return Decimal('0')

    @property
    def margem_real(self):
        if self.total_notas_fiscais > 0:
            return (self.resultado_real / self.total_notas_fiscais) * 100
        return Decimal('0')

    def __str__(self):
        return self.nome_obra


class AditivoContrato(models.Model):
    TIPO_ADITIVO = 'aditivo'
    TIPO_SUPRESSAO = 'supressao'
    TIPO_CHOICES = [
        (TIPO_ADITIVO, 'Aditivo'),
        (TIPO_SUPRESSAO, 'Supressao'),
    ]

    obra = models.ForeignKey(
        Obra,
        on_delete=models.CASCADE,
        related_name='aditivos_registrados',
    )
    data_referencia = models.DateField()
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_ADITIVO)
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_referencia', '-id']
        verbose_name = 'Aditivo de contrato'
        verbose_name_plural = 'Aditivos de contrato'

    def __str__(self):
        return f'{self.obra.nome_obra} - {self.descricao}'


class NotaFiscal(models.Model):
    STATUS_EMITIDA = 'emitida'
    STATUS_CANCELADA = 'cancelada'
    STATUS_RECEBIDA = 'recebida'
    STATUS_CHOICES = [
        (STATUS_EMITIDA, 'Emitida'),
        (STATUS_CANCELADA, 'Cancelada'),
        (STATUS_RECEBIDA, 'Recebida'),
    ]

    obra = models.ForeignKey(
        Obra,
        on_delete=models.CASCADE,
        related_name='notas_fiscais',
    )
    numero = models.CharField(max_length=50)
    data_emissao = models.DateField()
    valor_bruto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    observacoes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='emitida')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_emissao', '-id']
        verbose_name = 'Nota fiscal'
        verbose_name_plural = 'Notas fiscais'
        constraints = [
            models.UniqueConstraint(
                fields=['obra', 'numero'],
                name='unique_numero_nota_por_obra',
            )
        ]

    def _prefetched_items(self, relation_name):
        cache = getattr(self, '_prefetched_objects_cache', {})
        return cache.get(relation_name)

    @property
    def total_retencoes(self):
        retencoes = self._prefetched_items('retencoes')
        if retencoes is not None:
            return _sum_decimal(retencao.valor for retencao in retencoes)
        return self.retencoes.aggregate(total=Sum('valor'))['total'] or Decimal('0')

    @property
    def total_retencoes_inss(self):
        retencoes = self._prefetched_items('retencoes')
        if retencoes is not None:
            return _sum_decimal(
                retencao.valor
                for retencao in retencoes
                if retencao.tipo == RetencaoNotaFiscal.TIPO_INSS
            )
        return (
            self.retencoes.filter(tipo=RetencaoNotaFiscal.TIPO_INSS).aggregate(total=Sum('valor'))['total']
            or Decimal('0')
        )

    @property
    def total_retencoes_sem_inss(self):
        return self.total_retencoes - self.total_retencoes_inss

    @property
    def total_impostos(self):
        impostos = self._prefetched_items('impostos')
        if impostos is not None:
            return _sum_decimal(imposto.valor for imposto in impostos)
        return self.impostos.aggregate(total=Sum('valor'))['total'] or Decimal('0')

    @property
    def valor_liquido(self):
        return self.valor_bruto - self.total_retencoes - self.total_impostos

    def __str__(self):
        return f'NF {self.numero} - {self.obra.nome_obra}'


class RetencaoNotaFiscal(models.Model):
    TIPO_INSS = 'inss'
    TIPO_ISS = 'iss'
    TIPO_IRRF = 'irrf'
    TIPO_PIS_COFINS_CSLL = 'pis_cofins_csll'
    TIPO_OUTRA = 'outra'
    TIPO_CHOICES = [
        (TIPO_INSS, 'INSS'),
        (TIPO_ISS, 'ISS'),
        (TIPO_IRRF, 'IRRF'),
        (TIPO_PIS_COFINS_CSLL, 'PIS/COFINS/CSLL'),
        (TIPO_OUTRA, 'Outra'),
    ]

    nota_fiscal = models.ForeignKey(
        NotaFiscal,
        on_delete=models.CASCADE,
        related_name='retencoes',
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, default=TIPO_OUTRA)
    descricao = models.CharField(max_length=255, blank=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Retencao da nota fiscal'
        verbose_name_plural = 'Retencoes da nota fiscal'

    def __str__(self):
        return f'{self.get_tipo_display()} - NF {self.nota_fiscal.numero}'


class ImpostoNotaFiscal(models.Model):
    TIPO_CHOICES = [
        ('simples', 'Simples'),
        ('pis', 'PIS'),
        ('cofins', 'COFINS'),
        ('csll', 'CSLL'),
        ('irpj', 'IRPJ'),
        ('iss', 'ISS'),
        ('outro', 'Outro'),
    ]

    nota_fiscal = models.ForeignKey(
        NotaFiscal,
        on_delete=models.CASCADE,
        related_name='impostos',
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='outro')
    descricao = models.CharField(max_length=255, blank=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Imposto da nota fiscal'
        verbose_name_plural = 'Impostos da nota fiscal'

    def __str__(self):
        return f'{self.get_tipo_display()} - NF {self.nota_fiscal.numero}'


class DespesaObra(models.Model):
    CATEGORIA_CHOICES = [
        ('mao_de_obra', 'Mao de obra'),
        ('material', 'Material'),
        ('equipamento', 'Equipamento'),
        ('terceiro', 'Terceiro'),
        ('administrativa', 'Administrativa'),
        ('outra', 'Outra'),
    ]

    obra = models.ForeignKey(
        Obra,
        on_delete=models.CASCADE,
        related_name='despesas_registradas',
    )
    data_referencia = models.DateField()
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES, default='outra')
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_referencia', '-id']
        verbose_name = 'Despesa da obra'
        verbose_name_plural = 'Despesas da obra'

    def __str__(self):
        return f'{self.obra.nome_obra} - {self.descricao}'


class RetencaoTecnicaObra(models.Model):
    TIPO_RETENCAO = 'retencao'
    TIPO_DEVOLUCAO = 'devolucao'
    TIPO_CHOICES = [
        (TIPO_RETENCAO, 'Retencao'),
        (TIPO_DEVOLUCAO, 'Devolucao'),
    ]

    obra = models.ForeignKey(
        Obra,
        on_delete=models.CASCADE,
        related_name='retencoes_tecnicas_registradas',
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_RETENCAO)
    data_referencia = models.DateField()
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    data_prevista_devolucao = models.DateField(blank=True, null=True)
    data_devolucao = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_referencia', '-id']
        verbose_name = 'Retencao tecnica da obra'
        verbose_name_plural = 'Retencoes tecnicas da obra'

    def __str__(self):
        return f'{self.obra.nome_obra} - {self.descricao}'

    @property
    def valor_saldo(self):
        if self.tipo == self.TIPO_DEVOLUCAO:
            return -self.valor
        return self.valor

    @property
    def valor_evento(self):
        return -self.valor_saldo
