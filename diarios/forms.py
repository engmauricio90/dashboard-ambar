from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from obras.forms import BootstrapForm, BootstrapModelForm

from .models import (
    ChecklistDiario,
    DiarioObra,
    EfetivoDiario,
    EquipamentoDiario,
    FotoDiario,
    OcorrenciaDiario,
)


class OptionalExtraFormMixin:
    meaningful_fields = []
    ignored_values = {}

    def _raw_value(self, field_name):
        if getattr(self, 'files', None) and self.prefix:
            file_value = self.files.get(f'{self.prefix}-{field_name}')
            if file_value:
                return file_value
        if not self.data or not self.prefix:
            return None
        return self.data.get(f'{self.prefix}-{field_name}')

    def has_changed(self):
        if self.instance and self.instance.pk:
            return super().has_changed()
        if self.data and self.prefix and self.meaningful_fields:
            for field_name in self.meaningful_fields:
                value = self._raw_value(field_name)
                if value in (None, ''):
                    continue
                if str(value) in self.ignored_values.get(field_name, set()):
                    continue
                return super().has_changed()
            return False
        return super().has_changed()


class DiarioObraFiltroForm(BootstrapForm):
    obra = forms.CharField(required=False)
    data_inicial = forms.DateField(required=False, widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    data_final = forms.DateField(required=False, widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    status = forms.ChoiceField(required=False, choices=[('', 'Todos')] + DiarioObra.STATUS_CHOICES)
    responsavel = forms.CharField(required=False)
    situacao_obra = forms.ChoiceField(required=False, choices=[('', 'Todas')] + DiarioObra.SITUACAO_CHOICES)
    possui_ocorrencias = forms.BooleanField(required=False, label='Com ocorrencias')
    possui_fotos = forms.BooleanField(required=False, label='Com fotos')

    def clean(self):
        cleaned_data = super().clean()
        data_inicial = cleaned_data.get('data_inicial')
        data_final = cleaned_data.get('data_final')
        if data_inicial and data_final and data_inicial > data_final:
            raise ValidationError('A data inicial nao pode ser maior que a data final.')
        return cleaned_data


class DiarioObraForm(BootstrapModelForm):
    class Meta:
        model = DiarioObra
        fields = [
            'obra',
            'data',
            'responsavel_preenchimento',
            'responsavel_tecnico',
            'condicao_climatica',
            'turno',
            'situacao_obra',
            'descricao_servicos',
            'observacoes',
            'ocorrencias_interferencias',
            'pendencias',
            'orientacoes',
            'houve_visita',
            'visitante_nome',
            'status',
        ]
        widgets = {
            'data': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'descricao_servicos': forms.Textarea(attrs={'rows': 4}),
            'observacoes': forms.Textarea(attrs={'rows': 3}),
            'ocorrencias_interferencias': forms.Textarea(attrs={'rows': 3}),
            'pendencias': forms.Textarea(attrs={'rows': 3}),
            'orientacoes': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'data': 'Data do diario',
            'responsavel_preenchimento': 'Responsavel pelo preenchimento',
            'responsavel_tecnico': 'Responsavel tecnico',
            'condicao_climatica': 'Condicao climatica',
            'situacao_obra': 'Situacao da obra no dia',
            'descricao_servicos': 'Descricao geral dos servicos executados',
            'ocorrencias_interferencias': 'Ocorrencias / interferencias',
            'houve_visita': 'Houve visita de fiscalizacao/cliente/terceiro',
            'visitante_nome': 'Nome do visitante/fiscal',
        }

    def __init__(self, *args, usuario=None, pode_alterar_status=True, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)
        if not pode_alterar_status:
            self.fields['status'].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        obra = cleaned_data.get('obra')
        data = cleaned_data.get('data')
        if obra and data:
            queryset = DiarioObra.objects.filter(obra=obra, data=data)
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise ValidationError('Ja existe diario para esta obra nesta data.')
        return cleaned_data


class EfetivoDiarioForm(OptionalExtraFormMixin, BootstrapModelForm):
    meaningful_fields = ['funcao', 'quantidade']
    ignored_values = {
        'quantidade': {'1'},
    }

    class Meta:
        model = EfetivoDiario
        fields = ['funcao', 'quantidade']


class EquipamentoDiarioForm(OptionalExtraFormMixin, BootstrapModelForm):
    meaningful_fields = ['tipo', 'quantidade', 'situacao']
    ignored_values = {
        'quantidade': {'1'},
    }

    class Meta:
        model = EquipamentoDiario
        fields = ['tipo', 'quantidade', 'situacao']


class OcorrenciaDiarioForm(OptionalExtraFormMixin, BootstrapModelForm):
    meaningful_fields = ['descricao', 'providencia', 'responsavel_providencia', 'prazo_solucao']

    class Meta:
        model = OcorrenciaDiario
        fields = [
            'tipo',
            'descricao',
            'impacto_prazo',
            'impacto_financeiro',
            'providencia',
            'responsavel_providencia',
            'prazo_solucao',
            'status',
        ]
        widgets = {
            'descricao': forms.Textarea(attrs={'rows': 2}),
            'providencia': forms.Textarea(attrs={'rows': 2}),
            'prazo_solucao': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }


class ChecklistDiarioForm(BootstrapModelForm):
    class Meta:
        model = ChecklistDiario
        fields = ['item', 'resultado', 'observacoes']


class FotoDiarioForm(OptionalExtraFormMixin, BootstrapModelForm):
    meaningful_fields = ['imagem', 'legenda']

    class Meta:
        model = FotoDiario
        fields = ['imagem', 'legenda']

    def clean_imagem(self):
        imagem = self.cleaned_data.get('imagem')
        content_type = getattr(imagem, 'content_type', '')
        if imagem and content_type and not content_type.startswith('image/'):
            raise ValidationError('Envie apenas arquivos de imagem.')
        return imagem


EfetivoDiarioFormSet = inlineformset_factory(
    DiarioObra,
    EfetivoDiario,
    form=EfetivoDiarioForm,
    extra=0,
    can_delete=True,
)

EquipamentoDiarioFormSet = inlineformset_factory(
    DiarioObra,
    EquipamentoDiario,
    form=EquipamentoDiarioForm,
    extra=0,
    can_delete=True,
)

OcorrenciaDiarioFormSet = inlineformset_factory(
    DiarioObra,
    OcorrenciaDiario,
    form=OcorrenciaDiarioForm,
    extra=0,
    can_delete=True,
)

ChecklistDiarioFormSet = inlineformset_factory(
    DiarioObra,
    ChecklistDiario,
    form=ChecklistDiarioForm,
    extra=0,
    can_delete=True,
)

FotoDiarioFormSet = inlineformset_factory(
    DiarioObra,
    FotoDiario,
    form=FotoDiarioForm,
    extra=0,
    can_delete=True,
)
