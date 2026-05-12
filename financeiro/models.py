from decimal import Decimal

from django.db import models, transaction
from django.db.models import Q

from obras.models import DespesaObra, NotaFiscal, Obra, RetencaoNotaFiscal, RetencaoTecnicaObra


class Fornecedor(models.Model):
    nome = models.CharField(max_length=180)
    cpf_cnpj = models.CharField(max_length=30, blank=True)
    ie_identidade = models.CharField(max_length=40, blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    municipio = models.CharField(max_length=120, blank=True)
    cep = models.CharField(max_length=20, blank=True)
    telefone = models.CharField(max_length=40, blank=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Fornecedor'
        verbose_name_plural = 'Fornecedores'
        constraints = [
            models.UniqueConstraint(
                fields=['nome', 'cpf_cnpj'],
                name='unique_fornecedor_nome_documento',
            )
        ]

    def __str__(self):
        if self.cpf_cnpj:
            return f'{self.nome} - {self.cpf_cnpj}'
        return self.nome


class CentroCusto(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    descricao = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Centro de custo'
        verbose_name_plural = 'Centros de custo'

    def __str__(self):
        return self.nome


class ContaReceber(models.Model):
    STATUS_ABERTO = 'aberto'
    STATUS_RECEBIDO = 'recebido'
    STATUS_CANCELADO = 'cancelado'
    STATUS_CHOICES = [
        (STATUS_ABERTO, 'Em aberto'),
        (STATUS_RECEBIDO, 'Recebido'),
        (STATUS_CANCELADO, 'Cancelado'),
    ]

    cliente = models.CharField(max_length=150)
    obra = models.ForeignKey(Obra, on_delete=models.SET_NULL, blank=True, null=True, related_name='contas_receber')
    centro_custo = models.ForeignKey(
        CentroCusto,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='contas_receber',
    )
    numero_nf = models.CharField(max_length=50, blank=True)
    descricao = models.CharField(max_length=255)
    data_emissao = models.DateField()
    data_vencimento = models.DateField()
    data_recebimento = models.DateField(blank=True, null=True)
    valor_bruto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    issqn_retido = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    inss_retido = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retencao_tecnica = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    outras_retencoes = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ABERTO)
    observacoes = models.TextField(blank=True)
    nota_fiscal = models.OneToOneField(
        NotaFiscal,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='conta_receber_origem',
    )
    retencao_tecnica_obra = models.OneToOneField(
        RetencaoTecnicaObra,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='conta_receber_origem',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['data_vencimento', 'id']
        verbose_name = 'Conta a receber'
        verbose_name_plural = 'Contas a receber'

    @property
    def valor_retido_nf(self):
        return self.issqn_retido + self.inss_retido + self.outras_retencoes

    @property
    def valor_liquido(self):
        return self.valor_bruto - self.valor_retido_nf - self.retencao_tecnica

    @property
    def esta_baixada(self):
        return self.status == self.STATUS_RECEBIDO

    def __str__(self):
        return f'{self.descricao} - R$ {self.valor_bruto}'

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            self.sincronizar_obra()

    def sincronizar_obra(self):
        if not self.obra or not self.numero_nf:
            return

        status_nf = 'cancelada' if self.status == self.STATUS_CANCELADO else 'emitida'
        if self.status == self.STATUS_RECEBIDO:
            status_nf = 'recebida'

        nota, _ = NotaFiscal.objects.update_or_create(
            obra=self.obra,
            numero=self.numero_nf,
            defaults={
                'data_emissao': self.data_emissao,
                'valor_bruto': self.valor_bruto,
                'status': status_nf,
                'observacoes': self.observacoes or f'Gerada pelo financeiro: {self.descricao}',
            },
        )

        updates = {}
        if self.nota_fiscal_id != nota.id:
            updates['nota_fiscal'] = nota

        self._sincronizar_retencao_nf(nota, RetencaoNotaFiscal.TIPO_ISS, 'ISSQN retido', self.issqn_retido)
        self._sincronizar_retencao_nf(nota, RetencaoNotaFiscal.TIPO_INSS, 'INSS retido', self.inss_retido)
        self._sincronizar_retencao_nf(nota, RetencaoNotaFiscal.TIPO_OUTRA, 'Outras retencoes', self.outras_retencoes)

        retencao_tecnica = self._sincronizar_retencao_tecnica()
        if self.retencao_tecnica_obra_id != getattr(retencao_tecnica, 'id', None):
            updates['retencao_tecnica_obra'] = retencao_tecnica

        if updates:
            ContaReceber.objects.filter(pk=self.pk).update(**updates)
            for field, value in updates.items():
                setattr(self, field, value)

    def _sincronizar_retencao_nf(self, nota, tipo, descricao, valor):
        valor = valor or Decimal('0')
        existente = nota.retencoes.filter(tipo=tipo, descricao=descricao).first()
        if valor <= 0:
            if existente:
                existente.delete()
            return
        RetencaoNotaFiscal.objects.update_or_create(
            nota_fiscal=nota,
            tipo=tipo,
            descricao=descricao,
            defaults={'valor': valor},
        )

    def _sincronizar_retencao_tecnica(self):
        valor = self.retencao_tecnica or Decimal('0')
        if valor <= 0:
            if self.retencao_tecnica_obra_id:
                self.retencao_tecnica_obra.delete()
            return None

        if self.retencao_tecnica_obra_id:
            retencao = self.retencao_tecnica_obra
            retencao.obra = self.obra
            retencao.tipo = RetencaoTecnicaObra.TIPO_RETENCAO
            retencao.data_referencia = self.data_emissao
            retencao.descricao = f'Retencao tecnica NF {self.numero_nf}'
            retencao.valor = valor
            retencao.save()
            return retencao

        return RetencaoTecnicaObra.objects.create(
            obra=self.obra,
            tipo=RetencaoTecnicaObra.TIPO_RETENCAO,
            data_referencia=self.data_emissao,
            descricao=f'Retencao tecnica NF {self.numero_nf}',
            valor=valor,
        )


class ContaPagar(models.Model):
    STATUS_ABERTO = 'aberto'
    STATUS_PAGO = 'pago'
    STATUS_CANCELADO = 'cancelado'
    STATUS_CHOICES = [
        (STATUS_ABERTO, 'Em aberto'),
        (STATUS_PAGO, 'Pago'),
        (STATUS_CANCELADO, 'Cancelado'),
    ]

    fornecedor = models.CharField(max_length=150)
    fornecedor_cadastro = models.ForeignKey(
        Fornecedor,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='contas_pagar',
    )
    obra = models.ForeignKey(Obra, on_delete=models.SET_NULL, blank=True, null=True, related_name='contas_pagar')
    centro_custo = models.ForeignKey(
        CentroCusto,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='contas_pagar',
    )
    categoria = models.CharField(max_length=30, choices=DespesaObra.CATEGORIA_CHOICES, default='outra')
    ordem_compra = models.ForeignKey(
        'controles.OrdemCompraGeral',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='contas_pagar',
    )
    item_ordem_compra = models.ForeignKey(
        'controles.ItemOrdemCompraGeral',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='contas_pagar',
    )
    numero_nf = models.CharField(max_length=50, blank=True)
    quantidade_oc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_unitario_oc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descricao = models.CharField(max_length=255)
    data_emissao = models.DateField()
    data_vencimento = models.DateField()
    data_pagamento = models.DateField(blank=True, null=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valor_pago = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ABERTO)
    observacoes = models.TextField(blank=True)
    origem_importacao = models.CharField(max_length=50, blank=True)
    codigo_externo = models.CharField(max_length=120, blank=True)
    despesa_obra = models.OneToOneField(
        DespesaObra,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='conta_pagar_origem',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['data_vencimento', 'id']
        verbose_name = 'Conta a pagar'
        verbose_name_plural = 'Contas a pagar'
        constraints = [
            models.UniqueConstraint(
                fields=['origem_importacao', 'codigo_externo'],
                condition=~Q(origem_importacao='') & ~Q(codigo_externo=''),
                name='unique_conta_pagar_origem_codigo_externo',
            )
        ]

    @property
    def esta_baixada(self):
        return self.status == self.STATUS_PAGO

    @property
    def valor_pago_efetivo(self):
        if self.status == self.STATUS_PAGO and self.valor_pago:
            return self.valor_pago
        return self.valor

    @property
    def diferenca_pagamento(self):
        if self.status != self.STATUS_PAGO:
            return Decimal('0')
        return self.valor_pago_efetivo - self.valor

    def __str__(self):
        return f'{self.fornecedor} - R$ {self.valor}'

    def save(self, *args, **kwargs):
        if self.fornecedor_cadastro_id:
            self.fornecedor = self.fornecedor_cadastro.nome
        if self.ordem_compra_id:
            self.obra = self.obra or self.ordem_compra.obra
            self.centro_custo = self.centro_custo or self.ordem_compra.centro_custo
            self.categoria = self.categoria or self.ordem_compra.categoria_despesa
        if self.quantidade_oc is None:
            self.quantidade_oc = Decimal('0')
        if self.valor_unitario_oc is None:
            self.valor_unitario_oc = Decimal('0')
        if self.status == self.STATUS_PAGO and not self.valor_pago:
            self.valor_pago = self.valor
        with transaction.atomic():
            super().save(*args, **kwargs)
            self.sincronizar_obra()
            self.sincronizar_ordem_compra()

    def sincronizar_obra(self):
        if self.status == self.STATUS_CANCELADO:
            if self.despesa_obra_id:
                self.despesa_obra.delete()
                ContaPagar.objects.filter(pk=self.pk).update(despesa_obra=None)
                self.despesa_obra = None
            return

        if not self.obra:
            return

        if self.despesa_obra_id:
            despesa = self.despesa_obra
            despesa.obra = self.obra
            despesa.data_referencia = self.data_emissao
            despesa.categoria = self.categoria
            despesa.descricao = self.descricao
            despesa.valor = self.valor
            despesa.save()
        else:
            despesa = DespesaObra.objects.create(
                obra=self.obra,
                data_referencia=self.data_emissao,
                categoria=self.categoria,
                descricao=self.descricao,
                valor=self.valor,
            )
            ContaPagar.objects.filter(pk=self.pk).update(despesa_obra=despesa)
            self.despesa_obra = despesa

    def sincronizar_ordem_compra(self):
        from controles.models import NotaFiscalOrdemCompraGeral

        if self.status == self.STATUS_CANCELADO:
            self.notas_ordem_compra.update(status=NotaFiscalOrdemCompraGeral.STATUS_CANCELADA)
            return

        if not self.ordem_compra_id or not self.numero_nf:
            self.notas_ordem_compra.all().delete()
            return

        itens = list(self.itens_ordem_compra.select_related('item_ordem_compra'))
        if not itens and self.item_ordem_compra_id and self.quantidade_oc:
            itens = [
                ItemContaPagarOrdemCompra(
                    conta=self,
                    item_ordem_compra=self.item_ordem_compra,
                    quantidade=self.quantidade_oc,
                )
            ]

        item_ids = [item.item_ordem_compra_id for item in itens if item.item_ordem_compra_id]
        self.notas_ordem_compra.exclude(item_id__in=item_ids).delete()
        for item_conta in itens:
            item_oc = item_conta.item_ordem_compra
            if not item_oc:
                continue
            NotaFiscalOrdemCompraGeral.objects.update_or_create(
                conta_pagar=self,
                item=item_oc,
                defaults={
                    'ordem': self.ordem_compra,
                    'numero': self.numero_nf,
                    'data_emissao': self.data_emissao,
                    'data_vencimento': self.data_vencimento,
                    'quantidade': item_conta.quantidade,
                    'valor_unitario': item_oc.valor_unitario,
                    'valor_total': item_conta.valor_total,
                    'status': NotaFiscalOrdemCompraGeral.STATUS_LANCADA_FINANCEIRO,
                    'observacoes': self.observacoes,
                },
            )

    def recalcular_valor_por_itens_oc(self):
        total = sum((item.valor_total for item in self.itens_ordem_compra.select_related('item_ordem_compra')), Decimal('0'))
        if total:
            self.valor = total
            if self.status == self.STATUS_PAGO and not self.valor_pago:
                self.valor_pago = total


class ItemContaPagarOrdemCompra(models.Model):
    conta = models.ForeignKey(
        ContaPagar,
        on_delete=models.CASCADE,
        related_name='itens_ordem_compra',
    )
    item_ordem_compra = models.ForeignKey(
        'controles.ItemOrdemCompraGeral',
        on_delete=models.PROTECT,
        related_name='itens_contas_pagar',
    )
    quantidade = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']
        verbose_name = 'Item de OC da conta a pagar'
        verbose_name_plural = 'Itens de OC das contas a pagar'
        constraints = [
            models.UniqueConstraint(fields=['conta', 'item_ordem_compra'], name='unique_item_oc_por_conta_pagar')
        ]

    @property
    def valor_unitario(self):
        return self.item_ordem_compra.valor_unitario

    @property
    def valor_total(self):
        return self.quantidade * self.valor_unitario
