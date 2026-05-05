from decimal import Decimal

from django.db import models
from django.db.models import Sum

from obras.models import Obra


def _sum_decimal(values):
    return sum(values, Decimal('0'))


class OrcamentoMedicao(models.Model):
    TIPO_CONSTRUTORA = 'construtora'
    TIPO_EMPREITEIRO = 'empreiteiro'
    TIPO_CHOICES = [
        (TIPO_CONSTRUTORA, 'Construtora'),
        (TIPO_EMPREITEIRO, 'Empreiteiro'),
    ]

    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name='orcamentos_medicao')
    nome = models.CharField(max_length=180)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_CONSTRUTORA)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Orcamento de medicao'
        verbose_name_plural = 'Orcamentos de medicao'

    def __str__(self):
        return f'{self.nome} - {self.obra.nome_obra}'

    def _aggregate(self, expression):
        return self.itens.aggregate(total=Sum(expression))['total'] or Decimal('0')

    @property
    def total_material(self):
        return _sum_decimal(item.total_material for item in self.itens.all())

    @property
    def total_mao_obra(self):
        return _sum_decimal(item.total_mao_obra for item in self.itens.all())

    @property
    def total_equipamentos(self):
        return _sum_decimal(item.total_equipamentos for item in self.itens.all())

    @property
    def total_orcamento(self):
        return self.total_material + self.total_mao_obra + self.total_equipamentos


class ItemOrcamentoMedicao(models.Model):
    orcamento = models.ForeignKey(OrcamentoMedicao, on_delete=models.CASCADE, related_name='itens')
    item = models.CharField(max_length=40)
    descricao = models.CharField(max_length=255)
    unidade = models.CharField(max_length=20, blank=True)
    quantidade = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    preco_unitario_material = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    preco_unitario_mao_obra = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    preco_unitario_equipamentos = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']
        verbose_name = 'Item de orcamento de medicao'
        verbose_name_plural = 'Itens de orcamento de medicao'

    def __str__(self):
        return f'{self.item} - {self.descricao}'

    @property
    def preco_unitario_total(self):
        return self.preco_unitario_material + self.preco_unitario_mao_obra + self.preco_unitario_equipamentos

    @property
    def total_material(self):
        return self.quantidade * self.preco_unitario_material

    @property
    def total_mao_obra(self):
        return self.quantidade * self.preco_unitario_mao_obra

    @property
    def total_equipamentos(self):
        return self.quantidade * self.preco_unitario_equipamentos

    @property
    def valor_total(self):
        return self.quantidade * self.preco_unitario_total


class MedicaoConstrutora(models.Model):
    orcamento = models.ForeignKey(OrcamentoMedicao, on_delete=models.CASCADE, related_name='medicoes_construtora')
    numero = models.PositiveIntegerField(default=1)
    periodo_inicio = models.DateField()
    periodo_fim = models.DateField()
    data_medicao = models.DateField()
    retencao_tecnica = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retencao_tecnica_percentual = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    issqn = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    issqn_percentual = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    inss = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    inss_percentual = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    desconto_adicional = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    desconto_adicional_percentual = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    faturamento_direto = models.BooleanField(default=False)
    descricao_faturamento_direto = models.CharField(max_length=255, blank=True)
    valor_faturamento_direto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_medicao', '-numero', '-id']
        verbose_name = 'Medicao da construtora'
        verbose_name_plural = 'Medicoes da construtora'
        constraints = [
            models.UniqueConstraint(fields=['orcamento', 'numero'], name='unique_medicao_construtora_numero')
        ]

    def __str__(self):
        return f'Medicao {self.numero} - {self.orcamento}'

    @property
    def subtotal_periodo(self):
        return _sum_decimal(item.valor_periodo for item in self.itens.all())

    @property
    def total_bruto(self):
        return self.subtotal_periodo + self.valor_faturamento_direto

    @property
    def total_descontos(self):
        return self.retencao_tecnica + self.issqn + self.inss + self.desconto_adicional

    @property
    def total_liquido(self):
        return self.total_bruto - self.total_descontos


class ItemMedicaoConstrutora(models.Model):
    medicao = models.ForeignKey(MedicaoConstrutora, on_delete=models.CASCADE, related_name='itens')
    item_orcamento = models.ForeignKey(ItemOrcamentoMedicao, on_delete=models.CASCADE, related_name='medicoes_construtora')
    quantidade_periodo = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    class Meta:
        ordering = ['item_orcamento_id']
        verbose_name = 'Item de medicao da construtora'
        verbose_name_plural = 'Itens de medicao da construtora'
        constraints = [
            models.UniqueConstraint(fields=['medicao', 'item_orcamento'], name='unique_item_medicao_construtora')
        ]

    @property
    def quantidade_acumulada_anterior(self):
        total = (
            ItemMedicaoConstrutora.objects.filter(
                item_orcamento=self.item_orcamento,
                medicao__orcamento=self.medicao.orcamento,
                medicao__data_medicao__lt=self.medicao.data_medicao,
            )
            .exclude(medicao=self.medicao)
            .aggregate(total=Sum('quantidade_periodo'))['total']
        )
        return total or Decimal('0')

    @property
    def quantidade_acumulada_atual(self):
        return self.quantidade_acumulada_anterior + self.quantidade_periodo

    @property
    def saldo_quantidade(self):
        return self.item_orcamento.quantidade - self.quantidade_acumulada_atual

    @property
    def valor_periodo(self):
        return self.quantidade_periodo * self.item_orcamento.preco_unitario_total


class MedicaoEmpreiteiro(models.Model):
    TIPO_SIMPLES = 'simples'
    TIPO_CUMULATIVA = 'cumulativa'
    TIPO_CHOICES = [
        (TIPO_SIMPLES, 'Simples'),
        (TIPO_CUMULATIVA, 'Cumulativa'),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_SIMPLES)
    obra = models.ForeignKey(Obra, on_delete=models.SET_NULL, blank=True, null=True, related_name='medicoes_empreiteiros')
    orcamento = models.ForeignKey(
        OrcamentoMedicao,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='medicoes_empreiteiro',
    )
    empreiteiro = models.CharField(max_length=180)
    cpf_cnpj = models.CharField(max_length=30, blank=True)
    pix = models.CharField(max_length=120, blank=True)
    numero = models.PositiveIntegerField(default=1)
    periodo_inicio = models.DateField()
    periodo_fim = models.DateField()
    data_medicao = models.DateField()
    retencao_tecnica = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retencao_tecnica_percentual = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    desconto_adicional = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    desconto_adicional_percentual = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_medicao', '-numero', '-id']
        verbose_name = 'Medicao de empreiteiro'
        verbose_name_plural = 'Medicoes de empreiteiros'

    def __str__(self):
        return f'{self.empreiteiro} - Medicao {self.numero}'

    @property
    def subtotal_periodo(self):
        return _sum_decimal(item.valor_periodo for item in self.itens.all())

    @property
    def total_descontos(self):
        return self.retencao_tecnica + self.desconto_adicional

    @property
    def total_liquido(self):
        return self.subtotal_periodo - self.total_descontos


class ItemMedicaoEmpreiteiro(models.Model):
    medicao = models.ForeignKey(MedicaoEmpreiteiro, on_delete=models.CASCADE, related_name='itens')
    item_orcamento = models.ForeignKey(
        ItemOrcamentoMedicao,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='medicoes_empreiteiro',
    )
    item = models.CharField(max_length=40, blank=True)
    descricao = models.CharField(max_length=255)
    unidade = models.CharField(max_length=20, blank=True)
    quantidade_periodo = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']
        verbose_name = 'Item de medicao de empreiteiro'
        verbose_name_plural = 'Itens de medicao de empreiteiro'

    def save(self, *args, **kwargs):
        if self.item_orcamento_id:
            self.item = self.item_orcamento.item
            self.descricao = self.item_orcamento.descricao
            self.unidade = self.item_orcamento.unidade
            if not self.valor_unitario:
                self.valor_unitario = self.item_orcamento.preco_unitario_total
        super().save(*args, **kwargs)

    @property
    def valor_periodo(self):
        return (self.quantidade_periodo or Decimal('0')) * (self.valor_unitario or Decimal('0'))

    @property
    def quantidade_acumulada_anterior(self):
        if not self.item_orcamento_id or not self.medicao.orcamento_id:
            return Decimal('0')
        total = (
            ItemMedicaoEmpreiteiro.objects.filter(
                item_orcamento=self.item_orcamento,
                medicao__orcamento=self.medicao.orcamento,
                medicao__data_medicao__lt=self.medicao.data_medicao,
            )
            .exclude(medicao=self.medicao)
            .aggregate(total=Sum('quantidade_periodo'))['total']
        )
        return total or Decimal('0')

    @property
    def quantidade_acumulada_atual(self):
        return self.quantidade_acumulada_anterior + self.quantidade_periodo

    @property
    def saldo_quantidade(self):
        if not self.item_orcamento_id:
            return Decimal('0')
        return self.item_orcamento.quantidade - self.quantidade_acumulada_atual
