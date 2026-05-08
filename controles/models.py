from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class VeiculoMaquina(models.Model):
    TIPO_CHOICES = [
        ('carro', 'Carro'),
        ('caminhao', 'Caminhao'),
        ('maquina', 'Maquina'),
        ('equipamento', 'Equipamento'),
        ('outro', 'Outro'),
    ]
    STATUS_CHOICES = [
        ('ativo', 'Ativo'),
        ('inativo', 'Inativo'),
    ]

    placa = models.CharField(max_length=20, unique=True)
    descricao = models.CharField(max_length=150)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='carro')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ativo')
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['placa']
        verbose_name = 'Veiculo/Maquina'
        verbose_name_plural = 'Veiculos/Maquinas'

    def save(self, *args, **kwargs):
        self.placa = self.placa.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.placa} - {self.descricao}'


class RegistroAbastecimento(models.Model):
    veiculo = models.ForeignKey(
        VeiculoMaquina,
        on_delete=models.PROTECT,
        related_name='abastecimentos',
    )
    data_abastecimento = models.DateField()
    posto = models.CharField(max_length=150)
    responsavel = models.CharField(max_length=120)
    litros = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    valor_litro = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_abastecimento', '-id']
        verbose_name = 'Registro de abastecimento'
        verbose_name_plural = 'Registros de abastecimento'

    @property
    def valor_calculado(self):
        if self.litros is None:
            return Decimal('0')
        return self.litros * self.valor_litro

    def __str__(self):
        return f'{self.veiculo} - {self.data_abastecimento}'


class BombonaCombustivel(models.Model):
    STATUS_CHOICES = [
        ('ativa', 'Ativa'),
        ('inativa', 'Inativa'),
        ('manutencao', 'Manutencao'),
    ]

    identificacao = models.CharField(max_length=80, unique=True)
    capacidade_litros = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    localizacao = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ativa')
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['identificacao']
        verbose_name = 'Bombona de combustivel'
        verbose_name_plural = 'Bombonas de combustivel'

    def save(self, *args, **kwargs):
        self.identificacao = self.identificacao.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.identificacao


class OrdemCompraCombustivel(models.Model):
    DESTINO_VEICULO = 'veiculo'
    DESTINO_BOMBONA = 'bombona'
    TIPO_DESTINO_CHOICES = [
        (DESTINO_VEICULO, 'Veiculo/Maquina'),
        (DESTINO_BOMBONA, 'Bombona'),
    ]
    COMBUSTIVEL_CHOICES = [
        ('diesel', 'Diesel'),
        ('gasolina', 'Gasolina'),
        ('etanol', 'Etanol'),
        ('arla', 'ARLA'),
        ('outro', 'Outro'),
    ]
    STATUS_CHOICES = [
        ('rascunho', 'Rascunho'),
        ('solicitada', 'Solicitada'),
        ('aprovada', 'Aprovada'),
        ('parcialmente_faturada', 'Parcialmente faturada'),
        ('faturada', 'Faturada'),
        ('conferida', 'Conferida'),
        ('encerrada', 'Encerrada'),
        ('cancelada', 'Cancelada'),
    ]

    numero = models.CharField(max_length=40, unique=True, blank=True)
    data_ordem = models.DateField(default=timezone.localdate)
    fornecedor = models.CharField(max_length=150)
    fornecedor_cadastro = models.ForeignKey(
        'financeiro.Fornecedor',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='ordens_combustivel',
    )
    solicitante = models.CharField(max_length=120, blank=True)
    tipo_combustivel = models.CharField(max_length=20, choices=COMBUSTIVEL_CHOICES, default='diesel')
    tipo_destino = models.CharField(max_length=20, choices=TIPO_DESTINO_CHOICES, default=DESTINO_VEICULO)
    veiculo = models.ForeignKey(
        VeiculoMaquina,
        on_delete=models.PROTECT,
        related_name='ordens_combustivel',
        blank=True,
        null=True,
    )
    bombona = models.ForeignKey(
        BombonaCombustivel,
        on_delete=models.PROTECT,
        related_name='ordens_combustivel',
        blank=True,
        null=True,
    )
    quantidade_litros = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_litro_previsto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_total_previsto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='solicitada')
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_ordem', '-id']
        verbose_name = 'Ordem de compra de combustivel'
        verbose_name_plural = 'Ordens de compra de combustivel'

    def clean(self):
        super().clean()
        if self.tipo_destino == self.DESTINO_VEICULO:
            if not self.veiculo_id:
                raise ValidationError({'veiculo': 'Informe o veiculo/maquina da ordem.'})
            if self.bombona_id:
                raise ValidationError({'bombona': 'Nao informe bombona quando o destino for veiculo/maquina.'})
        if self.tipo_destino == self.DESTINO_BOMBONA:
            if not self.bombona_id:
                raise ValidationError({'bombona': 'Informe a bombona da ordem.'})
            if self.veiculo_id:
                raise ValidationError({'veiculo': 'Nao informe veiculo/maquina quando o destino for bombona.'})

    def save(self, *args, **kwargs):
        if self.fornecedor_cadastro_id:
            self.fornecedor = self.fornecedor_cadastro.nome
        if not self.valor_total_previsto and self.quantidade_litros and self.valor_litro_previsto:
            self.valor_total_previsto = self.quantidade_litros * self.valor_litro_previsto
        if not self.numero:
            year = (self.data_ordem or timezone.localdate()).year
            prefix = f'OC-COMB-{year}-'
            last = (
                self.__class__.objects.filter(numero__startswith=prefix)
                .order_by('-numero')
                .values_list('numero', flat=True)
                .first()
            )
            next_number = 1
            if last:
                try:
                    next_number = int(last.rsplit('-', 1)[-1]) + 1
                except ValueError:
                    next_number = self.__class__.objects.filter(numero__startswith=prefix).count() + 1
            self.numero = f'{prefix}{next_number:04d}'
        super().save(*args, **kwargs)

    @property
    def destino_display(self):
        if self.tipo_destino == self.DESTINO_BOMBONA:
            return self.bombona
        return self.veiculo

    @property
    def total_litros_faturados(self):
        return sum((nota.litros for nota in self.notas_fiscais.all()), Decimal('0'))

    @property
    def total_faturado(self):
        return sum((nota.valor_total for nota in self.notas_fiscais.all()), Decimal('0'))

    @property
    def saldo_litros(self):
        return self.quantidade_litros - self.total_litros_faturados

    @property
    def diferenca_valor(self):
        return self.total_faturado - self.valor_total_previsto

    def __str__(self):
        return f'{self.numero} - {self.destino_display}'


class NotaFiscalCombustivel(models.Model):
    STATUS_CHOICES = [
        ('emitida', 'Emitida'),
        ('recebida', 'Recebida'),
        ('conferida', 'Conferida'),
        ('cancelada', 'Cancelada'),
    ]

    ordem = models.ForeignKey(
        OrdemCompraCombustivel,
        on_delete=models.CASCADE,
        related_name='notas_fiscais',
    )
    numero = models.CharField(max_length=50)
    data_emissao = models.DateField()
    litros = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_litro = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='emitida')
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_emissao', '-id']
        verbose_name = 'Nota fiscal de combustivel'
        verbose_name_plural = 'Notas fiscais de combustivel'
        constraints = [
            models.UniqueConstraint(
                fields=['ordem', 'numero'],
                name='unique_nf_combustivel_por_ordem',
            )
        ]

    def save(self, *args, **kwargs):
        if not self.valor_total and self.litros and self.valor_litro:
            self.valor_total = self.litros * self.valor_litro
        super().save(*args, **kwargs)

    def __str__(self):
        return f'NF {self.numero} - {self.ordem.numero}'


class OrdemCompraGeral(models.Model):
    STATUS_CHOICES = [
        ('rascunho', 'Rascunho'),
        ('emitida', 'Emitida'),
        ('aprovada', 'Aprovada'),
        ('parcialmente_entregue', 'Parcialmente entregue'),
        ('entregue', 'Entregue'),
        ('faturada', 'Faturada'),
        ('encerrada', 'Encerrada'),
        ('cancelada', 'Cancelada'),
    ]

    numero = models.CharField(max_length=40, unique=True, blank=True)
    data_emissao = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='emitida')
    comprador = models.CharField(max_length=120, blank=True)
    obra = models.ForeignKey(
        'obras.Obra',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='ordens_compra_gerais',
    )
    centro_custo = models.ForeignKey(
        'financeiro.CentroCusto',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='ordens_compra_gerais',
    )
    categoria_despesa = models.CharField(max_length=30, default='material')
    empresa_razao_social = models.CharField(max_length=180, default='AMBAR ENGENHARIA')
    empresa_cnpj = models.CharField(max_length=30, blank=True)
    empresa_endereco = models.CharField(max_length=255, blank=True)
    fornecedor = models.CharField(max_length=180)
    fornecedor_cadastro = models.ForeignKey(
        'financeiro.Fornecedor',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='ordens_compra_gerais',
    )
    fornecedor_endereco = models.CharField(max_length=255, blank=True)
    fornecedor_bairro = models.CharField(max_length=120, blank=True)
    fornecedor_cidade = models.CharField(max_length=120, blank=True)
    fornecedor_uf = models.CharField(max_length=2, blank=True)
    fornecedor_cpf_cnpj = models.CharField(max_length=30, blank=True)
    fornecedor_cep = models.CharField(max_length=20, blank=True)
    fornecedor_fone = models.CharField(max_length=40, blank=True)
    fornecedor_ie = models.CharField(max_length=40, blank=True)
    condicoes_pagamento = models.TextField(blank=True)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_emissao', '-id']
        verbose_name = 'Ordem de compra geral'
        verbose_name_plural = 'Ordens de compra gerais'

    def save(self, *args, **kwargs):
        if self.fornecedor_cadastro_id:
            fornecedor = self.fornecedor_cadastro
            self.fornecedor = fornecedor.nome
            self.fornecedor_cpf_cnpj = fornecedor.cpf_cnpj
            self.fornecedor_ie = fornecedor.ie_identidade
            self.fornecedor_endereco = fornecedor.endereco
            self.fornecedor_cidade = fornecedor.municipio
            self.fornecedor_cep = fornecedor.cep
            self.fornecedor_fone = fornecedor.telefone
        if not self.numero:
            year = (self.data_emissao or timezone.localdate()).year
            suffix = f'/{year}'
            last = (
                self.__class__.objects.filter(numero__endswith=suffix)
                .order_by('-numero')
                .values_list('numero', flat=True)
                .first()
            )
            next_number = 1
            if last:
                try:
                    next_number = int(last.split('/', 1)[0]) + 1
                except ValueError:
                    next_number = self.__class__.objects.filter(numero__endswith=suffix).count() + 1
            self.numero = f'{next_number:03d}/{year}'
        super().save(*args, **kwargs)

    @property
    def total(self):
        return sum((item.valor_total for item in self.itens.all()), Decimal('0'))

    @property
    def total_faturado(self):
        return sum((nota.valor_total for nota in self.notas_fiscais.all() if nota.status != NotaFiscalOrdemCompraGeral.STATUS_CANCELADA), Decimal('0'))

    @property
    def saldo_financeiro(self):
        return self.total - self.total_faturado

    @property
    def percentual_faturado(self):
        if self.total > 0:
            return (self.total_faturado / self.total) * 100
        return Decimal('0')

    def __str__(self):
        return f'OC {self.numero} - {self.fornecedor}'


class ItemOrdemCompraGeral(models.Model):
    ordem = models.ForeignKey(
        OrdemCompraGeral,
        on_delete=models.CASCADE,
        related_name='itens',
    )
    item = models.PositiveIntegerField(default=1)
    descricao = models.CharField(max_length=255)
    quantidade = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unidade = models.CharField(max_length=20, default='un')
    valor_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    data_entrega = models.DateField(blank=True, null=True)

    class Meta:
        ordering = ['item', 'id']
        verbose_name = 'Item da ordem de compra'
        verbose_name_plural = 'Itens da ordem de compra'

    def save(self, *args, **kwargs):
        if not self.valor_total and self.quantidade and self.valor_unitario:
            self.valor_total = self.quantidade * self.valor_unitario
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.item:02d} - {self.descricao}'

    @property
    def quantidade_faturada(self):
        return sum(
            (nota.quantidade for nota in self.notas_fiscais.all() if nota.status != NotaFiscalOrdemCompraGeral.STATUS_CANCELADA),
            Decimal('0'),
        )

    @property
    def saldo_quantidade(self):
        return self.quantidade - self.quantidade_faturada

    @property
    def valor_faturado(self):
        return sum(
            (nota.valor_total for nota in self.notas_fiscais.all() if nota.status != NotaFiscalOrdemCompraGeral.STATUS_CANCELADA),
            Decimal('0'),
        )

    @property
    def diferenca_valor(self):
        return self.valor_faturado - self.valor_total


class NotaFiscalOrdemCompraGeral(models.Model):
    STATUS_RECEBIDA = 'recebida'
    STATUS_CONFERIDA = 'conferida'
    STATUS_LANCADA_FINANCEIRO = 'lancada_financeiro'
    STATUS_CANCELADA = 'cancelada'
    STATUS_CHOICES = [
        (STATUS_RECEBIDA, 'Recebida'),
        (STATUS_CONFERIDA, 'Conferida'),
        (STATUS_LANCADA_FINANCEIRO, 'Lancada no financeiro'),
        (STATUS_CANCELADA, 'Cancelada'),
    ]

    ordem = models.ForeignKey(
        OrdemCompraGeral,
        on_delete=models.CASCADE,
        related_name='notas_fiscais',
    )
    item = models.ForeignKey(
        ItemOrdemCompraGeral,
        on_delete=models.PROTECT,
        related_name='notas_fiscais',
    )
    conta_pagar = models.ForeignKey(
        'financeiro.ContaPagar',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='notas_ordem_compra',
    )
    numero = models.CharField(max_length=50)
    data_emissao = models.DateField()
    data_vencimento = models.DateField(blank=True, null=True)
    quantidade = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_RECEBIDA)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_emissao', '-id']
        verbose_name = 'Nota fiscal de ordem de compra'
        verbose_name_plural = 'Notas fiscais de ordens de compra'
        constraints = [
            models.UniqueConstraint(fields=['ordem', 'numero', 'item'], name='unique_nf_oc_geral_por_item')
        ]

    def save(self, *args, **kwargs):
        if self.item_id and not self.valor_unitario:
            self.valor_unitario = self.item.valor_unitario
        if not self.valor_total and self.quantidade and self.valor_unitario:
            self.valor_total = self.quantidade * self.valor_unitario
        super().save(*args, **kwargs)

    def __str__(self):
        return f'NF {self.numero} - {self.ordem.numero}'


class HistoricoOrdemCombustivel(models.Model):
    ordem = models.ForeignKey(
        OrdemCompraCombustivel,
        on_delete=models.CASCADE,
        related_name='historico',
    )
    data_hora = models.DateTimeField(auto_now_add=True)
    evento = models.CharField(max_length=80)
    descricao = models.TextField()
    status_anterior = models.CharField(max_length=30, blank=True)
    status_novo = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ['-data_hora', '-id']
        verbose_name = 'Historico da ordem de combustivel'
        verbose_name_plural = 'Historicos das ordens de combustivel'

    def __str__(self):
        return f'{self.ordem.numero} - {self.evento}'


class EquipamentoLocadoCatalogo(models.Model):
    STATUS_CHOICES = [
        ('ativo', 'Ativo'),
        ('inativo', 'Inativo'),
    ]

    nome = models.CharField(max_length=150)
    categoria = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ativo')
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Equipamento locado'
        verbose_name_plural = 'Catalogo de equipamentos locados'

    def __str__(self):
        return self.nome


class LocadoraEquipamento(models.Model):
    nome = models.CharField(max_length=150, unique=True)
    contato = models.CharField(max_length=120, blank=True)
    telefone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Locadora'
        verbose_name_plural = 'Locadoras'

    def __str__(self):
        return self.nome


class LocacaoEquipamento(models.Model):
    STATUS_CHOICES = [
        ('locado', 'Na obra'),
        ('aguardando_entrega', 'Ag. entrega'),
        ('retirada_solicitada', 'Ag. coleta'),
        ('retirado', 'Coletado'),
        ('cancelado', 'Cancelado'),
    ]

    equipamento = models.ForeignKey(
        EquipamentoLocadoCatalogo,
        on_delete=models.PROTECT,
        related_name='locacoes',
    )
    locadora = models.ForeignKey(
        LocadoraEquipamento,
        on_delete=models.PROTECT,
        related_name='locacoes',
    )
    obra = models.ForeignKey(
        'obras.Obra',
        on_delete=models.PROTECT,
        related_name='locacoes_equipamentos',
    )
    data_locacao = models.DateField(verbose_name='Data aluguel')
    solicitante = models.CharField(max_length=120, blank=True, verbose_name='Quem locou')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='locado')
    numero_contrato = models.CharField(max_length=150, blank=True, verbose_name='Contrato')
    quantidade = models.PositiveIntegerField(default=1, verbose_name='Qntd')
    data_solicitacao_retirada = models.DateField(blank=True, null=True)
    data_retirada = models.DateField(blank=True, null=True, verbose_name='Data coleta')
    prazo = models.CharField(max_length=120, blank=True)
    valor_referencia = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Valor')
    observacoes = models.TextField(blank=True, verbose_name='Observacao')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_locacao', '-id']
        verbose_name = 'Locacao de equipamento'
        verbose_name_plural = 'Locacoes de equipamentos'

    @property
    def em_aberto(self):
        return self.status in {'locado', 'retirada_solicitada'}

    def __str__(self):
        return f'{self.equipamento} - {self.obra}'


class MaquinaLocacaoCatalogo(models.Model):
    STATUS_CHOICES = [
        ('ativa', 'Ativa'),
        ('inativa', 'Inativa'),
    ]

    nome = models.CharField(max_length=150, unique=True)
    categoria = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ativa')
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Maquina para locacao'
        verbose_name_plural = 'Catalogo de maquinas para locacao'

    def __str__(self):
        return self.nome


class FornecedorMaquinaLocacao(models.Model):
    nome = models.CharField(max_length=150, unique=True)
    contato = models.CharField(max_length=120, blank=True)
    telefone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Fornecedor de maquina'
        verbose_name_plural = 'Fornecedores de maquinas'

    def __str__(self):
        return self.nome


class OrdemServicoLocacaoMaquina(models.Model):
    STATUS_CHOICES = [
        ('rascunho', 'Rascunho'),
        ('solicitada', 'Solicitada'),
        ('aprovada', 'Aprovada'),
        ('aguardando_mobilizacao', 'Aguardando mobilizacao'),
        ('em_operacao', 'Em operacao'),
        ('paralisada', 'Paralisada'),
        ('desmobilizacao_solicitada', 'Desmobilizacao solicitada'),
        ('desmobilizada', 'Desmobilizada'),
        ('faturada', 'Faturada'),
        ('conferida', 'Conferida'),
        ('encerrada', 'Encerrada'),
        ('cancelada', 'Cancelada'),
    ]
    TIPO_COBRANCA_CHOICES = [
        ('por_hora', 'Por hora'),
        ('diaria', 'Diaria'),
        ('semanal', 'Semanal'),
        ('mensal', 'Mensal'),
        ('empreitada', 'Empreitada'),
    ]

    numero = models.CharField(max_length=40, unique=True, blank=True)
    data_solicitacao = models.DateField(default=timezone.localdate)
    obra = models.ForeignKey(
        'obras.Obra',
        on_delete=models.PROTECT,
        related_name='ordens_locacao_maquinas',
    )
    fornecedor = models.ForeignKey(
        FornecedorMaquinaLocacao,
        on_delete=models.PROTECT,
        related_name='ordens',
    )
    fornecedor_cadastro = models.ForeignKey(
        'financeiro.Fornecedor',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='ordens_locacao_maquinas',
    )
    maquina = models.ForeignKey(
        MaquinaLocacaoCatalogo,
        on_delete=models.PROTECT,
        related_name='ordens',
    )
    solicitante = models.CharField(max_length=120, blank=True)
    responsavel = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default='solicitada')
    tipo_cobranca = models.CharField(max_length=20, choices=TIPO_COBRANCA_CHOICES, default='por_hora')
    data_prevista_inicio = models.DateField(blank=True, null=True)
    data_prevista_fim = models.DateField(blank=True, null=True)
    data_mobilizacao = models.DateField(blank=True, null=True)
    data_inicio_operacao = models.DateField(blank=True, null=True)
    data_solicitacao_desmobilizacao = models.DateField(blank=True, null=True)
    data_desmobilizacao = models.DateField(blank=True, null=True)
    valor_hora = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_diaria = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_mensal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    franquia_horas = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_mobilizacao = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_desmobilizacao = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_previsto_manual = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    operador_incluso = models.BooleanField(default=False)
    combustivel_incluso = models.BooleanField(default=False)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_solicitacao', '-id']
        verbose_name = 'OS de locacao de maquina'
        verbose_name_plural = 'OS de locacao de maquinas'

    def save(self, *args, **kwargs):
        if self.fornecedor_cadastro_id:
            fornecedor, _ = FornecedorMaquinaLocacao.objects.get_or_create(
                nome=self.fornecedor_cadastro.nome,
                defaults={
                    'telefone': self.fornecedor_cadastro.telefone,
                    'observacoes': f'Criado a partir do cadastro central. Documento: {self.fornecedor_cadastro.cpf_cnpj}',
                },
            )
            self.fornecedor = fornecedor
        for field_name in [
            'valor_hora',
            'valor_diaria',
            'valor_mensal',
            'franquia_horas',
            'valor_mobilizacao',
            'valor_desmobilizacao',
        ]:
            if getattr(self, field_name) is None:
                setattr(self, field_name, Decimal('0'))
        if not self.numero:
            year = (self.data_solicitacao or timezone.localdate()).year
            prefix = f'OS-MAQ-{year}-'
            last = (
                self.__class__.objects.filter(numero__startswith=prefix)
                .order_by('-numero')
                .values_list('numero', flat=True)
                .first()
            )
            next_number = 1
            if last:
                try:
                    next_number = int(last.rsplit('-', 1)[-1]) + 1
                except ValueError:
                    next_number = self.__class__.objects.filter(numero__startswith=prefix).count() + 1
            self.numero = f'{prefix}{next_number:04d}'
        super().save(*args, **kwargs)

    @property
    def total_horas_apontadas(self):
        return sum((apontamento.horas_trabalhadas for apontamento in self.apontamentos.all()), Decimal('0'))

    @property
    def total_horas_paradas(self):
        return sum((apontamento.horas_paradas for apontamento in self.apontamentos.all()), Decimal('0'))

    @property
    def total_horas_faturadas(self):
        return sum((nota.horas_faturadas for nota in self.notas_fiscais.all()), Decimal('0'))

    @property
    def total_faturado(self):
        return sum((nota.valor_total for nota in self.notas_fiscais.all()), Decimal('0'))

    @property
    def saldo_horas(self):
        return self.total_horas_apontadas - self.total_horas_faturadas

    @property
    def valor_operacao_previsto(self):
        if self.valor_previsto_manual is not None:
            return self.valor_previsto_manual
        if self.tipo_cobranca == 'por_hora':
            return self.total_horas_apontadas * self.valor_hora
        return Decimal('0')

    @property
    def valor_previsto_total(self):
        return self.valor_operacao_previsto + self.valor_mobilizacao + self.valor_desmobilizacao

    @property
    def diferenca_valor(self):
        return self.total_faturado - self.valor_previsto_total

    def __str__(self):
        return f'{self.numero} - {self.maquina} - {self.obra}'


class ApontamentoMaquinaLocacao(models.Model):
    ordem = models.ForeignKey(
        OrdemServicoLocacaoMaquina,
        on_delete=models.CASCADE,
        related_name='apontamentos',
    )
    data = models.DateField()
    horimetro_inicial = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    horimetro_final = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    horas_trabalhadas = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    horas_paradas = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    motivo_parada = models.CharField(max_length=255, blank=True)
    operador = models.CharField(max_length=120, blank=True)
    responsavel_apontamento = models.CharField(max_length=120, blank=True)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Apontamento de maquina'
        verbose_name_plural = 'Apontamentos de maquinas'

    def save(self, *args, **kwargs):
        if self.horas_trabalhadas is None:
            self.horas_trabalhadas = Decimal('0')
        if self.horas_paradas is None:
            self.horas_paradas = Decimal('0')
        if (
            not self.horas_trabalhadas
            and self.horimetro_inicial is not None
            and self.horimetro_final is not None
            and self.horimetro_final >= self.horimetro_inicial
        ):
            self.horas_trabalhadas = self.horimetro_final - self.horimetro_inicial
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.ordem.numero} - {self.data}'


class NotaFiscalLocacaoMaquina(models.Model):
    STATUS_CHOICES = [
        ('emitida', 'Emitida'),
        ('recebida', 'Recebida'),
        ('conferida', 'Conferida'),
        ('cancelada', 'Cancelada'),
    ]

    ordem = models.ForeignKey(
        OrdemServicoLocacaoMaquina,
        on_delete=models.CASCADE,
        related_name='notas_fiscais',
    )
    numero = models.CharField(max_length=50)
    data_emissao = models.DateField()
    periodo_inicio = models.DateField(blank=True, null=True)
    periodo_fim = models.DateField(blank=True, null=True)
    horas_faturadas = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_maquina = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_mobilizacao = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_desmobilizacao = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='emitida')
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_emissao', '-id']
        verbose_name = 'NF de locacao de maquina'
        verbose_name_plural = 'NFs de locacao de maquinas'
        constraints = [
            models.UniqueConstraint(
                fields=['ordem', 'numero'],
                name='unique_nf_locacao_maquina_por_ordem',
            )
        ]

    def save(self, *args, **kwargs):
        for field_name in ['horas_faturadas', 'valor_maquina', 'valor_mobilizacao', 'valor_desmobilizacao']:
            if getattr(self, field_name) is None:
                setattr(self, field_name, Decimal('0'))
        if not self.valor_total:
            self.valor_total = self.valor_maquina + self.valor_mobilizacao + self.valor_desmobilizacao
        super().save(*args, **kwargs)

    def __str__(self):
        return f'NF {self.numero} - {self.ordem.numero}'


class HistoricoLocacaoMaquina(models.Model):
    ordem = models.ForeignKey(
        OrdemServicoLocacaoMaquina,
        on_delete=models.CASCADE,
        related_name='historico',
    )
    data_hora = models.DateTimeField(auto_now_add=True)
    evento = models.CharField(max_length=80)
    descricao = models.TextField()
    status_anterior = models.CharField(max_length=40, blank=True)
    status_novo = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ['-data_hora', '-id']
        verbose_name = 'Historico de locacao de maquina'
        verbose_name_plural = 'Historicos de locacao de maquinas'

    def __str__(self):
        return f'{self.ordem.numero} - {self.evento}'


class OrcamentoRadarObra(models.Model):
    SITUACAO_CHOICES = [
        ('aguardando_resposta', 'Aguardando resposta'),
        ('em_revisao', 'Em revisao'),
        ('fechada', 'Fechada'),
        ('nao_foi_para_frente', 'Nao foi para frente'),
        ('cancelada', 'Cancelada'),
    ]

    numero = models.CharField(max_length=50, unique=True)
    cliente = models.CharField(max_length=150)
    descricao = models.TextField()
    data_orcamento = models.DateField()
    situacao = models.CharField(max_length=30, choices=SITUACAO_CHOICES, default='aguardando_resposta')
    valor_estimado = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    responsavel = models.CharField(max_length=120, blank=True)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_orcamento', '-id']
        verbose_name = 'Radar de obra'
        verbose_name_plural = 'Radar de obras'

    def __str__(self):
        return f'{self.numero} - {self.cliente}'


class ContratoConcretagem(models.Model):
    STATUS_CHOICES = [
        ('ativo', 'Ativo'),
        ('encerrado', 'Encerrado'),
        ('cancelado', 'Cancelado'),
    ]

    obra = models.ForeignKey(
        'obras.Obra',
        on_delete=models.PROTECT,
        related_name='contratos_concretagem',
    )
    numero_contrato = models.CharField(max_length=80, blank=True)
    fornecedor = models.CharField(max_length=150)
    fornecedor_cadastro = models.ForeignKey(
        'financeiro.Fornecedor',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='contratos_concretagem',
    )
    descricao = models.CharField(max_length=255)
    data_inicio = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ativo')
    custo_m3_concreto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    custo_bomba = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adicional_noturno = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adicional_sabado = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adicional_m3_faltante = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    volume_minimo_m3 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data_inicio', '-id']
        verbose_name = 'Contrato de concretagem'
        verbose_name_plural = 'Contratos de concretagem'

    @property
    def total_previsto(self):
        return sum((faturamento.valor_previsto for faturamento in self.faturamentos.all()), Decimal('0'))

    @property
    def total_faturado(self):
        return sum((faturamento.valor_cobrado for faturamento in self.faturamentos.all()), Decimal('0'))

    @property
    def diferenca_total(self):
        return self.total_faturado - self.total_previsto

    def __str__(self):
        return f'{self.obra} - {self.fornecedor}'

    def save(self, *args, **kwargs):
        if self.fornecedor_cadastro_id:
            self.fornecedor = self.fornecedor_cadastro.nome
        super().save(*args, **kwargs)


class SolicitanteConcretagem(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    ativo = models.BooleanField(default=True)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Solicitante de concretagem'
        verbose_name_plural = 'Solicitantes de concretagem'

    def __str__(self):
        return self.nome


class FaturamentoConcretagem(models.Model):
    STATUS_CHOICES = [
        ('solicitada', 'Solicitada'),
        ('executada', 'Executada'),
        ('conferida', 'Conferida'),
        ('faturada', 'Faturada'),
        ('cancelada', 'Cancelada'),
    ]
    FCK_CHOICES = [
        ('20_mpa', '20 Mpa'),
        ('25_mpa', '25 Mpa'),
        ('30_mpa', '30 Mpa'),
        ('35_mpa', '35 Mpa'),
        ('acima_35_mpa', 'Acima de 35 Mpa'),
    ]
    TIPO_BOMBA_CHOICES = [
        ('bomba_estacionaria', 'Bomba estacionaria'),
        ('bomba_lanca', 'Bomba lanca'),
    ]

    contrato = models.ForeignKey(
        ContratoConcretagem,
        on_delete=models.CASCADE,
        related_name='faturamentos',
    )
    data_faturamento = models.DateField(verbose_name='Data da concretagem')
    responsavel_solicitacao = models.CharField(max_length=120, blank=True)
    solicitante = models.ForeignKey(
        SolicitanteConcretagem,
        on_delete=models.PROTECT,
        related_name='faturamentos',
        blank=True,
        null=True,
        verbose_name='Responsavel solicitacao',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='solicitada')
    volume_m3 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fck_traco = models.CharField(max_length=20, choices=FCK_CHOICES, blank=True, verbose_name='FCK/Traco')
    tipo_bomba = models.CharField(max_length=30, choices=TIPO_BOMBA_CHOICES, blank=True)
    usou_bomba = models.BooleanField(default=False)
    adicional_noturno_aplicado = models.BooleanField(default=False)
    adicional_sabado_aplicado = models.BooleanField(default=False)
    volume_faltante_m3 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_previsto_manual = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    valor_cobrado = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Valor faturado')
    numero_documento = models.CharField(max_length=80, blank=True, verbose_name='Nota fiscal')
    data_conferencia = models.DateField(blank=True, null=True)
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_faturamento', '-id']
        verbose_name = 'Faturamento de concretagem'
        verbose_name_plural = 'Faturamentos de concretagem'

    @property
    def valor_concreto(self):
        return self.volume_m3 * self.contrato.custo_m3_concreto

    @property
    def valor_bomba(self):
        if self.usou_bomba:
            return self.contrato.custo_bomba
        return Decimal('0')

    @property
    def valor_adicional_noturno(self):
        if self.adicional_noturno_aplicado:
            return self.contrato.adicional_noturno
        return Decimal('0')

    @property
    def valor_adicional_sabado(self):
        if self.adicional_sabado_aplicado:
            return self.contrato.adicional_sabado
        return Decimal('0')

    @property
    def valor_m3_faltante(self):
        return self.volume_faltante_m3 * self.contrato.adicional_m3_faltante

    @property
    def valor_previsto(self):
        if self.valor_previsto_manual is not None:
            return self.valor_previsto_manual
        return (
            self.valor_concreto
            + self.valor_bomba
            + self.valor_adicional_noturno
            + self.valor_adicional_sabado
            + self.valor_m3_faltante
        )

    @property
    def diferenca(self):
        return self.valor_cobrado - self.valor_previsto

    @property
    def responsavel_display(self):
        if self.solicitante:
            return self.solicitante.nome
        return self.responsavel_solicitacao

    def __str__(self):
        return f'{self.contrato} - {self.data_faturamento}'
