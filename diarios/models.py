from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from obras.models import Obra


class DiarioObra(models.Model):
    CLIMA_ENSOLARADO = 'ensolarado'
    CLIMA_NUBLADO = 'nublado'
    CLIMA_CHUVOSO = 'chuvoso'
    CLIMA_PARCIALMENTE_NUBLADO = 'parcialmente_nublado'
    CLIMA_INTERRUPCAO_CHUVA = 'interrupcao_chuva'
    CLIMA_CHOICES = [
        (CLIMA_ENSOLARADO, 'Ensolarado'),
        (CLIMA_NUBLADO, 'Nublado'),
        (CLIMA_CHUVOSO, 'Chuvoso'),
        (CLIMA_PARCIALMENTE_NUBLADO, 'Parcialmente nublado'),
        (CLIMA_INTERRUPCAO_CHUVA, 'Interrupcao por chuva'),
    ]

    TURNO_MANHA = 'manha'
    TURNO_TARDE = 'tarde'
    TURNO_INTEGRAL = 'integral'
    TURNO_NOITE = 'noite'
    TURNO_CHOICES = [
        (TURNO_MANHA, 'Manha'),
        (TURNO_TARDE, 'Tarde'),
        (TURNO_INTEGRAL, 'Integral'),
        (TURNO_NOITE, 'Noite'),
    ]

    SITUACAO_ANDAMENTO = 'em_andamento'
    SITUACAO_PARALISADA = 'paralisada'
    SITUACAO_SEM_ATIVIDADE = 'sem_atividade'
    SITUACAO_FINALIZADA_PARCIAL = 'finalizada_parcialmente'
    SITUACAO_CHOICES = [
        (SITUACAO_ANDAMENTO, 'Em andamento'),
        (SITUACAO_PARALISADA, 'Paralisada'),
        (SITUACAO_SEM_ATIVIDADE, 'Sem atividade'),
        (SITUACAO_FINALIZADA_PARCIAL, 'Finalizada parcialmente'),
    ]

    STATUS_RASCUNHO = 'rascunho'
    STATUS_FINALIZADO = 'finalizado'
    STATUS_REVISADO = 'revisado'
    STATUS_CANCELADO = 'cancelado'
    STATUS_CHOICES = [
        (STATUS_RASCUNHO, 'Rascunho'),
        (STATUS_FINALIZADO, 'Finalizado'),
        (STATUS_REVISADO, 'Revisado'),
        (STATUS_CANCELADO, 'Cancelado'),
    ]

    obra = models.ForeignKey(Obra, on_delete=models.CASCADE, related_name='diarios')
    data = models.DateField(verbose_name='Data do diario')
    responsavel_preenchimento = models.CharField(max_length=150)
    responsavel_tecnico = models.CharField(max_length=150, blank=True)
    condicao_climatica = models.CharField(max_length=30, choices=CLIMA_CHOICES, blank=True)
    turno = models.CharField(max_length=20, choices=TURNO_CHOICES, default=TURNO_INTEGRAL)
    situacao_obra = models.CharField(max_length=30, choices=SITUACAO_CHOICES, blank=True)
    descricao_servicos = models.TextField(blank=True)
    observacoes = models.TextField(blank=True)
    ocorrencias_interferencias = models.TextField(blank=True)
    pendencias = models.TextField(blank=True)
    orientacoes = models.TextField(blank=True)
    houve_visita = models.BooleanField(default=False)
    visitante_nome = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RASCUNHO)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='diarios_criados',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='diarios_alterados',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-data', '-id']
        constraints = [
            models.UniqueConstraint(fields=['obra', 'data'], name='unique_diario_por_obra_data'),
        ]
        verbose_name = 'Diario de obra'
        verbose_name_plural = 'Diarios de obra'

    @property
    def total_efetivo(self):
        return sum(item.quantidade for item in self.efetivos.all())

    @property
    def total_horas_efetivo(self):
        return sum((item.total_horas for item in self.efetivos.all()), Decimal('0'))

    @property
    def total_equipamentos(self):
        return sum(item.quantidade for item in self.equipamentos.all())

    @property
    def pode_editar(self):
        return self.status == self.STATUS_RASCUNHO

    def validar_finalizacao(self):
        if not self.responsavel_preenchimento:
            raise ValidationError('Informe o responsavel pelo preenchimento.')
        if not self.situacao_obra:
            raise ValidationError('Informe a situacao da obra.')
        if not self.condicao_climatica:
            raise ValidationError('Informe a condicao climatica.')
        if not self.descricao_servicos and not self.frentes.exists():
            raise ValidationError('Informe a descricao geral ou ao menos uma frente de servico.')

    def __str__(self):
        return f'{self.obra} - {self.data:%d/%m/%Y}'


class FrenteServicoDiario(models.Model):
    SITUACAO_EXECUTADO = 'executado'
    SITUACAO_EM_EXECUCAO = 'em_execucao'
    SITUACAO_PARCIAL = 'parcialmente_executado'
    SITUACAO_NAO_EXECUTADO = 'nao_executado'
    SITUACAO_REFEITO = 'refeito_correcao'
    SITUACAO_CHOICES = [
        (SITUACAO_EXECUTADO, 'Executado'),
        (SITUACAO_EM_EXECUCAO, 'Em execucao'),
        (SITUACAO_PARCIAL, 'Parcialmente executado'),
        (SITUACAO_NAO_EXECUTADO, 'Nao executado'),
        (SITUACAO_REFEITO, 'Refeito / correcao'),
    ]

    diario = models.ForeignKey(DiarioObra, on_delete=models.CASCADE, related_name='frentes')
    nome = models.CharField(max_length=150)
    descricao = models.TextField(blank=True)
    local_trecho = models.CharField(max_length=180, blank=True)
    percentual_executado = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    observacoes = models.TextField(blank=True)
    situacao = models.CharField(max_length=30, choices=SITUACAO_CHOICES, default=SITUACAO_EM_EXECUCAO)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.nome


class EfetivoDiario(models.Model):
    FUNCAO_CHOICES = [
        ('engenheiro', 'Engenheiro'),
        ('mestre_obras', 'Mestre de obras'),
        ('encarregado', 'Encarregado'),
        ('pedreiro', 'Pedreiro'),
        ('servente', 'Servente'),
        ('carpinteiro', 'Carpinteiro'),
        ('armador', 'Armador'),
        ('operador_maquina', 'Operador de maquina'),
        ('motorista', 'Motorista'),
        ('eletricista', 'Eletricista'),
        ('encanador', 'Encanador'),
        ('pintor', 'Pintor'),
        ('topografo', 'Topografo'),
        ('auxiliar', 'Auxiliar'),
        ('outros', 'Outros'),
    ]

    diario = models.ForeignKey(DiarioObra, on_delete=models.CASCADE, related_name='efetivos')
    funcao = models.CharField(max_length=40, choices=FUNCAO_CHOICES)
    nome_colaborador = models.CharField(max_length=150, blank=True)
    empresa_equipe = models.CharField(max_length=150, blank=True)
    quantidade = models.PositiveIntegerField(default=1)
    horario_entrada = models.TimeField(blank=True, null=True)
    horario_saida = models.TimeField(blank=True, null=True)
    total_horas = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    observacoes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['id']

    def save(self, *args, **kwargs):
        if self.horario_entrada and self.horario_saida:
            entrada = self.horario_entrada.hour * 60 + self.horario_entrada.minute
            saida = self.horario_saida.hour * 60 + self.horario_saida.minute
            if saida >= entrada:
                self.total_horas = Decimal(saida - entrada) / Decimal('60') * self.quantidade
        super().save(*args, **kwargs)


class EquipamentoDiario(models.Model):
    EQUIPAMENTO_CHOICES = [
        ('escavadeira_hidraulica', 'Escavadeira hidraulica'),
        ('retroescavadeira', 'Retroescavadeira'),
        ('rolo_compactador', 'Rolo compactador'),
        ('caminhao_cacamba', 'Caminhao cacamba'),
        ('caminhao_munck', 'Caminhao munck'),
        ('betoneira', 'Betoneira'),
        ('compactador_solo', 'Compactador de solo'),
        ('bobcat', 'Bobcat'),
        ('caminhao_pipa', 'Caminhao pipa'),
        ('motoniveladora', 'Motoniveladora'),
        ('pa_carregadeira', 'Pa carregadeira'),
        ('placa_vibratoria', 'Placa vibratoria'),
        ('outros', 'Outros'),
    ]
    SITUACAO_CHOICES = [
        ('operando', 'Operando'),
        ('parado', 'Parado'),
        ('manutencao', 'Manutencao'),
        ('mobilizado', 'Mobilizado'),
        ('desmobilizado', 'Desmobilizado'),
    ]

    diario = models.ForeignKey(DiarioObra, on_delete=models.CASCADE, related_name='equipamentos')
    tipo = models.CharField(max_length=50, choices=EQUIPAMENTO_CHOICES)
    identificacao = models.CharField(max_length=120, blank=True)
    empresa_proprietario = models.CharField(max_length=150, blank=True)
    quantidade = models.PositiveIntegerField(default=1)
    horimetro_inicial = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    horimetro_final = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total_horas = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    situacao = models.CharField(max_length=30, choices=SITUACAO_CHOICES, default='operando')
    observacoes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['id']

    def save(self, *args, **kwargs):
        if self.horimetro_inicial is not None and self.horimetro_final is not None:
            self.total_horas = max(self.horimetro_final - self.horimetro_inicial, Decimal('0'))
        super().save(*args, **kwargs)


class MaterialDiario(models.Model):
    MOVIMENTO_CHOICES = [
        ('recebido', 'Recebido'),
        ('utilizado', 'Utilizado'),
        ('devolvido', 'Devolvido'),
    ]

    diario = models.ForeignKey(DiarioObra, on_delete=models.CASCADE, related_name='materiais')
    material = models.CharField(max_length=150)
    unidade = models.CharField(max_length=30, blank=True)
    quantidade = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    fornecedor = models.CharField(max_length=150, blank=True)
    nota_fiscal = models.CharField(max_length=80, blank=True)
    movimento = models.CharField(max_length=20, choices=MOVIMENTO_CHOICES, default='recebido')
    observacoes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['id']


class OcorrenciaDiario(models.Model):
    TIPO_CHOICES = [
        ('chuva', 'Chuva'),
        ('falta_material', 'Falta de material'),
        ('falta_projeto', 'Falta de projeto'),
        ('interferencia_rede', 'Interferencia de rede existente'),
        ('retrabalho', 'Retrabalho'),
        ('acidente_incidente', 'Acidente/incidente'),
        ('visita_fiscalizacao', 'Visita de fiscalizacao'),
        ('alteracao_escopo', 'Alteracao de escopo'),
        ('parada_equipe', 'Parada de equipe'),
        ('equipamento_parado', 'Equipamento parado'),
        ('atraso_fornecedor', 'Atraso de fornecedor'),
        ('outros', 'Outros'),
    ]
    IMPACTO_CHOICES = [('sim', 'Sim'), ('nao', 'Nao'), ('parcial', 'Parcial')]
    STATUS_CHOICES = [
        ('aberta', 'Aberta'),
        ('em_andamento', 'Em andamento'),
        ('resolvida', 'Resolvida'),
        ('cancelada', 'Cancelada'),
    ]

    diario = models.ForeignKey(DiarioObra, on_delete=models.CASCADE, related_name='ocorrencias')
    tipo = models.CharField(max_length=40, choices=TIPO_CHOICES)
    descricao = models.TextField()
    impacto_prazo = models.CharField(max_length=10, choices=IMPACTO_CHOICES, default='nao')
    impacto_financeiro = models.CharField(max_length=10, choices=IMPACTO_CHOICES, default='nao')
    providencia = models.TextField(blank=True)
    responsavel_providencia = models.CharField(max_length=150, blank=True)
    prazo_solucao = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='aberta')

    class Meta:
        ordering = ['id']


class ChecklistDiario(models.Model):
    ITEM_EPI = 'epi'
    ITEM_CHOICES = [
        (ITEM_EPI, 'Uso de EPI pela equipe'),
        ('sinalizacao', 'Sinalizacao da obra adequada'),
        ('limpeza', 'Organizacao e limpeza do canteiro'),
        ('equipamentos', 'Equipamentos em boas condicoes'),
        ('sem_acidente', 'Nao houve acidente/incidente'),
        ('conforme_projeto', 'Servicos executados conforme projeto'),
        ('niveis', 'Conferencia de niveis/alinhamentos'),
        ('materiais', 'Controle de materiais'),
        ('residuos', 'Controle de residuos'),
        ('clima', 'Condicoes climaticas adequadas'),
    ]
    RESULTADO_CHOICES = [
        ('conforme', 'Conforme'),
        ('nao_conforme', 'Nao conforme'),
        ('nao_aplica', 'Nao se aplica'),
    ]

    diario = models.ForeignKey(DiarioObra, on_delete=models.CASCADE, related_name='checklist')
    item = models.CharField(max_length=40, choices=ITEM_CHOICES)
    resultado = models.CharField(max_length=20, choices=RESULTADO_CHOICES, default='conforme')
    observacoes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['diario', 'item'], name='unique_item_checklist_diario'),
        ]


class FotoDiario(models.Model):
    diario = models.ForeignKey(DiarioObra, on_delete=models.CASCADE, related_name='fotos')
    imagem = models.ImageField(upload_to='diarios/fotos/%Y/%m/')
    legenda = models.CharField(max_length=180, blank=True)
    frente_servico = models.ForeignKey(
        FrenteServicoDiario,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='fotos',
    )
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']


class HistoricoDiario(models.Model):
    ACAO_CRIADO = 'criado'
    ACAO_EDITADO = 'editado'
    ACAO_FINALIZADO = 'finalizado'
    ACAO_REABERTO = 'reaberto'
    ACAO_CANCELADO = 'cancelado'
    ACAO_FOTO_ADICIONADA = 'foto_adicionada'
    ACAO_FOTO_REMOVIDA = 'foto_removida'
    ACAO_CHOICES = [
        (ACAO_CRIADO, 'Criado'),
        (ACAO_EDITADO, 'Editado'),
        (ACAO_FINALIZADO, 'Finalizado'),
        (ACAO_REABERTO, 'Reaberto'),
        (ACAO_CANCELADO, 'Cancelado'),
        (ACAO_FOTO_ADICIONADA, 'Foto adicionada'),
        (ACAO_FOTO_REMOVIDA, 'Foto removida'),
    ]

    diario = models.ForeignKey(DiarioObra, on_delete=models.CASCADE, related_name='historico')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
    acao = models.CharField(max_length=30, choices=ACAO_CHOICES)
    descricao = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
