from decimal import Decimal

from django.db import models, transaction

from obras.models import DespesaObra, NotaFiscal, Obra, RetencaoNotaFiscal, RetencaoTecnicaObra


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
    obra = models.ForeignKey(Obra, on_delete=models.SET_NULL, blank=True, null=True, related_name='contas_pagar')
    centro_custo = models.ForeignKey(
        CentroCusto,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='contas_pagar',
    )
    categoria = models.CharField(max_length=30, choices=DespesaObra.CATEGORIA_CHOICES, default='outra')
    descricao = models.CharField(max_length=255)
    data_emissao = models.DateField()
    data_vencimento = models.DateField()
    data_pagamento = models.DateField(blank=True, null=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ABERTO)
    observacoes = models.TextField(blank=True)
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

    @property
    def esta_baixada(self):
        return self.status == self.STATUS_PAGO

    def __str__(self):
        return f'{self.fornecedor} - R$ {self.valor}'

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            self.sincronizar_obra()

    def sincronizar_obra(self):
        if not self.obra or self.status == self.STATUS_CANCELADO:
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
